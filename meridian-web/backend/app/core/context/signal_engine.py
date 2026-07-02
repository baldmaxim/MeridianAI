"""Signal Engine — контекстная классификация переговорной ситуации (Этап 1).

В отличие от keyword/event-триггеров, Signal Engine оценивает СМЫСЛ переговорной
ситуации через LLM и решает, нужна ли подсказка вообще. Возвращает NegotiationSignal.

Без keyword-matching как fallback: если LLM недоступен или ответ невалиден —
осознанное молчание (should_prompt=false, situation_type="none", used_fallback=true).
"""

import asyncio
import json
import logging
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

logger = logging.getLogger("meridian.signal")

# Допустимые типы карточек (синхронно со схемой suggestion_prompts)
_ALLOWED_CARD_TYPES = {
    "say_now", "ask", "counter", "risk", "fixation",
    "trade_concession", "pause", "clarify", "summarize",
}

_MAX_TEXT_LEN = 500


class NegotiationSignal(BaseModel):
    """Классификация текущей переговорной ситуации. Все поля имеют дефолты —
    «пустой» сигнал означает молчание (should_prompt=false)."""

    model_config = ConfigDict(extra="ignore")

    should_prompt: bool = False
    situation_type: Literal[
        "price_pressure",
        "deadline_pressure",
        "liability_shift",
        "scope_change",
        "verbal_agreement_risk",
        "concession_requested",
        "contradiction",
        "stalling",
        "missing_evidence",
        "opportunity_to_fix_terms",
        "none",
    ] = "none"
    phase: Literal[
        "opening",
        "clarifying",
        "bargaining",
        "risk_fixing",
        "closing",
        "unknown",
    ] = "unknown"
    speaker_side: Literal[
        "our_side",
        "counterparty",
        "third_party",
        "unknown",
    ] = "unknown"
    intent: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    urgency: float = 0.0
    confidence: float = 0.0
    actionability: float = 0.0
    novelty_key: str = "none"
    recommended_card_types: list[str] = []
    reasoning_summary: str = ""

    @field_validator("urgency", "confidence", "actionability", mode="before")
    @classmethod
    def _clamp_scores(cls, v: Any) -> float:
        """Привести score к диапазону 0..1; нечисловое → 0.0."""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        if f != f:  # NaN
            return 0.0
        return max(0.0, min(1.0, f))

    @field_validator("recommended_card_types", mode="before")
    @classmethod
    def _filter_card_types(cls, v: Any) -> list[str]:
        """Оставить только допустимые типы карточек; мусор отбросить."""
        if not isinstance(v, (list, tuple)):
            return []
        return [c for c in v if isinstance(c, str) and c in _ALLOWED_CARD_TYPES]

    @model_validator(mode="after")
    def _normalize(self) -> "NegotiationSignal":
        if not self.should_prompt:
            self.novelty_key = "none"
        elif not self.novelty_key or not self.novelty_key.strip():
            self.novelty_key = self.situation_type
        if self.intent and len(self.intent) > _MAX_TEXT_LEN:
            self.intent = self.intent[:_MAX_TEXT_LEN]
        if self.reasoning_summary and len(self.reasoning_summary) > _MAX_TEXT_LEN:
            self.reasoning_summary = self.reasoning_summary[:_MAX_TEXT_LEN]
        return self


class SignalEngineResult(BaseModel):
    signal: NegotiationSignal
    raw_response: Optional[str] = None
    error: Optional[str] = None
    # Тип ошибки для policy: технические (llm_unavailable/timeout/exception) допускают
    # legacy fallback; качество ответа (invalid_json/validation_error) — нет (молчим).
    error_kind: Literal[
        "none",
        "llm_unavailable",
        "timeout",
        "exception",
        "invalid_json",
        "validation_error",
    ] = "none"
    used_fallback: bool = False


def _extract_json_object(text: str) -> Optional[dict]:
    """Безопасно извлечь первый JSON-объект из текста модели.

    Модель может вернуть markdown-обёртку, лишний текст до/после JSON или
    невалидный JSON. Пытаемся: (1) прямой json.loads; (2) снять ```json```/```
    обёртку; (3) найти сбалансированный {...}-объект. При неудаче — None.
    Никакого keyword-fallback: лучше молчание, чем триггерные слова.
    """
    if not text or not text.strip():
        return None

    candidate = text.strip()

    # (1) прямой парс
    obj = _try_load_dict(candidate)
    if obj is not None:
        return obj

    # (2) снять markdown-ограждение ```json ... ``` или ``` ... ```
    fence = re.search(r"```(?:json)?\s*(.+?)```", candidate, re.DOTALL | re.IGNORECASE)
    if fence:
        obj = _try_load_dict(fence.group(1).strip())
        if obj is not None:
            return obj

    # (3) сбалансированный первый {...}-объект
    snippet = _first_balanced_object(candidate)
    if snippet is not None:
        obj = _try_load_dict(snippet)
        if obj is not None:
            return obj

    return None


def _try_load_dict(text: str) -> Optional[dict]:
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _first_balanced_object(text: str) -> Optional[str]:
    """Вернуть подстроку первого сбалансированного {...} (учёт строк/escape)."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def passes_thresholds(
    signal: NegotiationSignal,
    *,
    min_confidence: float,
    min_actionability: float,
    min_urgency: float,
) -> bool:
    """True, если сигнал проходит все три порога. Используется в SessionManager и тестах."""
    return (
        signal.confidence >= min_confidence
        and signal.actionability >= min_actionability
        and signal.urgency >= min_urgency
    )


_SCHEMA_HINT = """Верни ТОЛЬКО JSON-объект ровно этой схемы (без markdown, без пояснений):
{
  "should_prompt": true|false,
  "situation_type": "price_pressure|deadline_pressure|liability_shift|scope_change|verbal_agreement_risk|concession_requested|contradiction|stalling|missing_evidence|opportunity_to_fix_terms|none",
  "phase": "opening|clarifying|bargaining|risk_fixing|closing|unknown",
  "speaker_side": "our_side|counterparty|third_party|unknown",
  "intent": "что сейчас пытается сделать говорящий (кратко)",
  "risk_level": "low|medium|high",
  "urgency": 0.0,
  "confidence": 0.0,
  "actionability": 0.0,
  "novelty_key": "стабильный короткий ключ, напр. price_pressure:counterparty:discount_without_exchange",
  "recommended_card_types": ["say_now|ask|counter|risk|fixation|trade_concession|pause|clarify|summarize"],
  "reasoning_summary": "1-2 предложения: почему это (не) момент для подсказки"
}"""


class SignalEngine:
    """LLM-классификатор переговорной ситуации. Не делает keyword-matching."""

    def _build_prompt(
        self,
        *,
        role_name: str,
        recent_dialog: str,
        current_text: str,
        document_context: str,
        knowledge_context: str,
        previous_meetings_context: str,
        letters_context: str,
        speaker_context: str,
    ) -> str:
        parts = [
            f"Ты — аналитик переговоров на стороне роли «{role_name}».",
            "Ты НЕ ищешь ключевые слова. Ты оцениваешь СМЫСЛ переговорной ситуации.",
            "",
            "ПРИНЦИПЫ:",
            "- Подсказка нужна ТОЛЬКО если есть конкретное действие, усиливающее НАШУ позицию прямо сейчас.",
            "- Не предлагай карточку ради активности. Сомневаешься — should_prompt=false.",
            "- Не предлагай одностороннюю уступку. Если оппонент просит уступку — это concession_requested,",
            "  и уместен обмен (trade_concession), а не дарение.",
            "- Если звучит устная договорённость или размытая ответственность — это риск:",
            "  situation_type verbal_agreement_risk/liability_shift, карточки fixation/risk.",
            "- Если данных недостаточно для опоры — clarify/ask, либо should_prompt=false.",
            "- novelty_key — стабильный короткий ключ ситуации (для дедупликации). При should_prompt=false → \"none\".",
            "- urgency/confidence/actionability — числа 0..1.",
            "",
            "СТОРОНЫ ГОВОРЯЩИХ (важно):",
            "- Используй блок «Роли и стороны участников» как ГЛАВНЫЙ источник сторон, если он есть.",
            "- НЕ угадывай сторону по имени/метке спикера («Speaker 1» — это не оппонент по умолчанию).",
            "- НЕ путай технический источник (device_role: desktop/phone/secondary/observer) с переговорной стороной.",
            "- Если роли неизвестны или из диалога сторона неясна — speaker_side=\"unknown\".",
            "- Если текст противоречит указанным сторонам — снизь confidence и кратко поясни это в reasoning_summary.",
        ]
        # Блок ролей включаем всегда (даже пустой) — чтобы модель явно знала про неизвестность.
        parts += ["", "Роли и стороны участников:",
                  speaker_context or "Роли участников неизвестны. Не делай жёстких предположений о стороне говорящего."]
        if document_context:
            parts += ["", "ДОКУМЕНТЫ ВСТРЕЧИ:", document_context]
        if knowledge_context:
            parts += ["", "УТВЕРЖДЁННАЯ БАЗА ЗНАНИЙ:", knowledge_context]
        if previous_meetings_context:
            parts += ["", "ПРЕДЫДУЩИЕ ВСТРЕЧИ:", previous_meetings_context]
        if letters_context:
            parts += ["", "ПЕРЕПИСКА (ПИСЬМА):", letters_context]
        parts += [
            "",
            "ПОСЛЕДНИЕ РЕПЛИКИ (с таймкодами):",
            recent_dialog or "(нет)",
            "",
            "НОВЫЕ РЕПЛИКИ (оцени именно их в контексте выше):",
            current_text or "(нет)",
            "",
            _SCHEMA_HINT,
        ]
        return "\n".join(parts)

    async def classify(
        self,
        *,
        llm_client=None,
        role_name: str,
        recent_dialog: str,
        current_text: str,
        document_context: str = "",
        knowledge_context: str = "",
        previous_meetings_context: str = "",
        letters_context: str = "",
        speaker_context: str = "",
        timeout_seconds: Optional[float] = None,
    ) -> SignalEngineResult:
        """Классифицировать ситуацию. Без llm_client/при невалидном ответе → молчание.

        timeout_seconds: если задан (>0), LLM-вызов оборачивается в asyncio.wait_for.
        """
        if llm_client is None:
            return SignalEngineResult(
                signal=NegotiationSignal(), used_fallback=True,
                error="no_llm_client", error_kind="llm_unavailable",
            )

        prompt = self._build_prompt(
            role_name=role_name,
            recent_dialog=recent_dialog,
            current_text=current_text,
            document_context=document_context,
            knowledge_context=knowledge_context,
            previous_meetings_context=previous_meetings_context,
            letters_context=letters_context,
            speaker_context=speaker_context,
        )

        try:
            call = llm_client.get_suggestion_async(prompt, max_tokens=600)
            if timeout_seconds is not None and timeout_seconds > 0:
                raw = await asyncio.wait_for(call, timeout=timeout_seconds)
            else:
                raw = await call
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("[SignalEngine] timeout after %ss", timeout_seconds)
            return SignalEngineResult(
                signal=NegotiationSignal(), used_fallback=True,
                error="timeout", error_kind="timeout",
            )
        except Exception as e:  # noqa: BLE001 — техническое исключение при вызове LLM
            logger.warning("[SignalEngine] LLM error: %s", e)
            return SignalEngineResult(
                signal=NegotiationSignal(), used_fallback=True,
                error="llm_error", error_kind="exception",
            )

        if not raw or not raw.strip():
            # LLM-вызов вернулся БЕЗ исключения, но пустой → это проблема качества ответа
            # модели (нельзя извлечь JSON), а НЕ технический сбой. invalid_json → без legacy.
            return SignalEngineResult(
                signal=NegotiationSignal(), used_fallback=True,
                error="empty_llm_response", error_kind="invalid_json", raw_response=raw,
            )

        data = _extract_json_object(raw)
        if data is None:
            return SignalEngineResult(
                signal=NegotiationSignal(), used_fallback=True,
                error="invalid_json", error_kind="invalid_json", raw_response=raw,
            )

        try:
            signal = NegotiationSignal(**data)
        except ValidationError as e:
            logger.warning("[SignalEngine] validation error: %s", e)
            return SignalEngineResult(
                signal=NegotiationSignal(), used_fallback=True,
                error="validation_error", error_kind="validation_error", raw_response=raw,
            )

        return SignalEngineResult(signal=signal, raw_response=raw)
