"""Правка распознанного текста по словарю терминов.

Код находит кандидатов (term_matcher), LLM только подтверждает или отклоняет каждого и
называет термин в нужной форме — свободных правок нет. Ответ проверяется (validate_fix),
правка применяется к копии, исходное слово сохраняется в поле "orig".
"""

import asyncio
import copy
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .term_lexicon import Lexicon, plain
from .term_matcher import Candidate, find_candidates, reply_ranges, split_tail_punct

logger = logging.getLogger("meridian.batch")

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Кандидатов в одном запросе.
CHUNK_SIZE = 60
# Сколько символов реплики показываем вокруг кандидата.
CONTEXT_CHARS = 150
# Сколько символов соседних реплик показываем до и после.
NEIGHBOR_CHARS = 120
# Допуск validate_fix: «to» не длиннее формы больше чем на столько букв.
MAX_EXTRA_LETTERS = 4

SYSTEM_PROMPT = """Ты — корректор распознанной речи строительных переговоров.
Распознавание иногда искажает отраслевые слова: «машины места» вместо «машино-места»,
«ростверг» вместо «ростверк», «опал убка» вместо «опалубка».
Для каждого кандидата реши, искажён ли здесь словарный термин.
Исправляй ТОЛЬКО если отмеченное слово в этом месте бессмысленно, не существует
или явно не вяжется с контекстом, а термин звучит похоже и подходит по смыслу.
НЕ исправляй нормальное слово, которое подходит по смыслу, даже если термин тоже подошёл бы
(«по смете этого объекта», «он же заказчик» — оставить). Не меняй форму правильно распознанного слова.
Если сомневаешься — не включай. Обычно подтверждается меньшинство кандидатов.
Ответ — ОДИН JSON-объект без markdown и пояснений."""


def validate_fix(candidate: Candidate, to: Any) -> bool:
    """Правка допустима, только если «to» — то же слово, что и словарная форма, в другой грамматике."""
    if not isinstance(to, str):
        return False
    to = to.strip()
    if not to or any(c.isdigit() for c in to):
        return False
    if len(to.split()) > len(candidate.form.split()) + 1:
        return False
    to_plain = plain(to)
    if not to_plain or to_plain == plain(candidate.text):
        return False
    form_plain = plain(candidate.form)
    if not to_plain.startswith(form_plain[:max(len(form_plain) - 2, 3)]):
        return False
    return len(to_plain) <= len(form_plain) + MAX_EXTRA_LETTERS


def _first_letter_upper(text: str) -> bool:
    for ch in text:
        if ch.isalpha():
            return ch.isupper()
    return False


def apply_corrections(transcription: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Вернуть копию распознавания с применёнными правками; вход не меняется.

    Каждая правка заменяет words[w0:w1] одним словом. Пересекающиеся и выходящие за
    границы правки пропускаются.
    """
    result = copy.deepcopy(transcription)
    words = result.get("words") or []
    limit = len(words)
    for item in sorted(items, key=lambda it: it.get("w0", -1), reverse=True):
        w0, w1, to = item.get("w0"), item.get("w1"), item.get("to")
        if not isinstance(w0, int) or not isinstance(w1, int) or not isinstance(to, str):
            continue
        to = to.strip()
        if not to or w0 < 0 or w0 >= w1 or w1 > limit:
            continue
        src = words[w0:w1]
        _, tail = split_tail_punct(src[-1].get("text", ""))
        if _first_letter_upper(src[0].get("text", "")) and to[0].islower():
            to = to[0].upper() + to[1:]
        merged = dict(src[0])
        merged["text"] = to + tail
        if "end" in src[-1]:
            merged["end"] = src[-1]["end"]
        merged["orig"] = " ".join(w.get("text", "") for w in src)
        words[w0:w1] = [merged]
        limit = w0
    if words:
        result["text"] = " ".join(w.get("text", "") for w in words)
    return result


def effective_transcription(job: Any) -> Optional[Dict[str, Any]]:
    """Распознавание задачи с применёнными правками словаря; None — распознавания нет.

    Исходный transcription_json не меняется. Битые правки — предупреждение и исходник;
    битый сам transcription_json вызывающий обрабатывает как раньше (json.loads бросает).
    """
    if not job.transcription_json:
        return None
    data = json.loads(job.transcription_json)
    raw = getattr(job, "transcription_corrections_json", None)
    if not raw or not isinstance(data, dict):
        return data
    try:
        items = (json.loads(raw) or {}).get("items")
    except (ValueError, TypeError, AttributeError):
        logger.warning("job %s: transcription_corrections_json не разобран", getattr(job, "id", None))
        return data
    if not isinstance(items, list) or not items:
        return data
    return apply_corrections(data, [it for it in items if isinstance(it, dict)])


def _clip_left(text: str, size: int) -> str:
    if len(text) <= size:
        return text
    cut = text[-size:]
    return "…" + (cut.split(" ", 1)[1] if " " in cut else cut)


def _clip_right(text: str, size: int) -> str:
    if len(text) <= size:
        return text
    cut = text[:size]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "…"


class TermCorrector:
    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "google/gemini-3-flash-preview"):
        self.api_key = api_key
        self.model = model

    async def correct(self, transcription: Dict[str, Any], lexicon: Lexicon,
                      timeout: int = 120) -> Optional[Dict[str, Any]]:
        """Подготовить правки: {"v","lexicon","items"}. None — если все запросы к LLM упали."""
        words = transcription.get("words") or []
        result: Dict[str, Any] = {"v": 1, "lexicon": lexicon.version, "items": []}
        candidates = await asyncio.to_thread(find_candidates, words, lexicon)
        if not candidates:
            return result
        logger.info("[TermFix] кандидатов: %d", len(candidates))

        ranges = reply_ranges(words)
        ok_chunks = 0
        chunks = 0
        for pos in range(0, len(candidates), CHUNK_SIZE):
            chunk = candidates[pos:pos + CHUNK_SIZE]
            chunks += 1
            fixes = await asyncio.to_thread(self._ask_chunk, chunk, words, ranges, timeout)
            if fixes is None:
                continue
            ok_chunks += 1
            result["items"].extend(self._accept(chunk, fixes))
        if ok_chunks == 0:
            logger.error("[TermFix] все запросы (%d) к LLM не удались", chunks)
            return None
        logger.info("[TermFix] принято правок: %d из %d", len(result["items"]), len(candidates))
        return result

    @staticmethod
    def _accept(chunk: List[Candidate], fixes: List[Tuple[int, str]]) -> List[Dict[str, Any]]:
        """Оставить правки с известным id, прошедшие validate_fix."""
        by_id = {c.id: c for c in chunk}
        items: List[Dict[str, Any]] = []
        seen: set = set()
        unknown = invalid = 0
        for cid, to in fixes:
            cand = by_id.get(cid)
            if cand is None or cid in seen:
                unknown += 1
                continue
            if not validate_fix(cand, to):
                invalid += 1
                continue
            seen.add(cid)
            items.append({"w0": cand.w0, "w1": cand.w1, "from": cand.text,
                          "to": to.strip(), "term": cand.term})
        if unknown or invalid:
            logger.info("[TermFix] отброшено: неизвестных id %d, не прошли проверку %d",
                        unknown, invalid)
        return items

    def _build_prompt(self, chunk: List[Candidate], words: List[Dict[str, Any]],
                      ranges: List[Tuple[int, int]]) -> str:
        lines = []
        for c in chunk:
            s, e = ranges[c.seg]
            _, tail = split_tail_punct(words[c.w1 - 1].get("text", ""))
            left = _clip_left(" ".join(w.get("text", "") for w in words[s:c.w0]), CONTEXT_CHARS)
            right = _clip_right(" ".join(w.get("text", "") for w in words[c.w1:e]), CONTEXT_CHARS)
            context = f"{left} [[{c.text}]]{tail} {right}".strip()
            prev = next_ = ""
            if c.seg > 0:
                ps, pe = ranges[c.seg - 1]
                prev = _clip_left(" ".join(w.get("text", "") for w in words[ps:pe]), NEIGHBOR_CHARS)
            if c.seg + 1 < len(ranges):
                ns, ne = ranges[c.seg + 1]
                next_ = _clip_right(" ".join(w.get("text", "") for w in words[ns:ne]), NEIGHBOR_CHARS)
            lines.append(f"{c.id}. термин: {c.term} | до: {prev} | реплика: {context} | после: {next_}")
        return (
            "Кандидат отмечен в реплике [[двойными скобками]]. Верни JSON: "
            '{"fixes":[{"id":3,"to":"машино-места"}]}. Включай только подтверждённых '
            'кандидатов; если ни один не подтверждён — {"fixes":[]}.\n\n'
            "КАНДИДАТЫ:\n" + "\n".join(lines)
        )

    def _ask_chunk(self, chunk: List[Candidate], words: List[Dict[str, Any]],
                   ranges: List[Tuple[int, int]], timeout: int) -> Optional[List[Tuple[int, str]]]:
        """Один запрос. None — сбой (сеть/LLM/не JSON); [] — модель ничего не подтвердила."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._build_prompt(chunk, words, ranges)},
            ],
            "temperature": 0,
            "max_tokens": 4096,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/meridian",
            "X-Title": "Meridian - AI Negotiation Helper",
        }
        try:
            response = self._request_with_retry(headers, payload, timeout)
            if not response or response.status_code != 200:
                if response:
                    logger.error("[TermFix] OpenRouter %s", response.status_code)
                return None
            content = (response.json().get("choices") or [{}])[0].get("message", {}).get("content")
            return self._parse(content)
        except Exception as e:
            logger.error("[TermFix] ошибка запроса: %s", e)
            return None

    @staticmethod
    def _parse(content: Optional[str]) -> Optional[List[Tuple[int, str]]]:
        """Ответ модели → [(id, to)]. Не JSON → None; чужая структура → пусто."""
        if not content:
            return None
        raw = content.strip()
        # Модель иногда всё же оборачивает JSON в ```json ... ```
        fenced = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
        if fenced:
            raw = fenced.group(1).strip()
        try:
            data: Any = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("[TermFix] невалидный JSON от модели: %s", e)
            return None
        fixes = data.get("fixes") if isinstance(data, dict) else None
        if not isinstance(fixes, list):
            return []
        out: List[Tuple[int, str]] = []
        for fx in fixes:
            if not isinstance(fx, dict):
                continue
            try:
                cid = int(fx.get("id"))
            except (TypeError, ValueError):
                continue
            to = fx.get("to")
            if isinstance(to, str):
                out.append((cid, to))
        return out

    def _request_with_retry(self, headers: dict, payload: dict, timeout: int):
        # OpenRouter гео-блокирует РФ (IP прод-сервера) → тот же egress-прокси, что у протокола.
        from ...config import get_settings
        proxy = get_settings().openrouter_proxy_url
        proxies = {"http": proxy, "https": proxy} if proxy else None
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(
                    self.API_URL, headers=headers, json=payload, timeout=timeout,
                    proxies=proxies,
                )
                if response.status_code not in RETRYABLE_STATUSES:
                    return response
                logger.warning("[TermFix] retry %d/%d: status %s",
                               attempt + 1, MAX_RETRIES, response.status_code)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                logger.warning("[TermFix] retry %d/%d: %s", attempt + 1, MAX_RETRIES, e)
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
        return None
