"""Протокол ElevenLabs Scribe v3 Live (прямой WebSocket): опции, URL, диаризация, тайминги.

Вынесено из streaming_service.py, чтобы сервис держал только цикл подключения и обмена.
Имена query-параметров и сообщений — по доке /v1/speech-to-text/realtime.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Optional
from urllib.parse import urlencode

logger = logging.getLogger("meridian.elevenlabs")

WS_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"

# Типы сообщений-ошибок: тип лежит в message_type, текст — в error.
FATAL_ERRORS = {"auth_error", "invalid_api_key", "quota_exceeded", "unaccepted_terms"}
# Не фатальные: показываем пользователю и переподключаемся.
RECONNECT_ERRORS = {"commit_throttled", "queue_overflow", "rate_limited", "session_time_limit_exceeded"}
# Ошибки параметров запроса: лечим отказом от «новых» опций.
DEGRADE_ERRORS = {"invalid_request", "input_error"}
# Прочие ошибки сервера: показываем, сессию не рвём (если сервер закроет сокет — реконнект)
OTHER_ERRORS = {"error", "transcriber_error", "chunk_size_exceeded", "insufficient_audio_activity",
                "resource_exhausted"}
ALL_ERRORS = FATAL_ERRORS | RECONNECT_ERRORS | DEGRADE_ERRORS | OTHER_ERRORS

# Лимиты keyterms (query) и keyterm_library (первый чанк)
KEYTERMS_MAX = 50
KEYTERMS_MAX_CHARS = 20
LIBRARY_MAX_TERMS = 10000
LIBRARY_MAX_CHARS = 50
LIBRARY_MAX_BYTES = 2 * 1024 * 1024

PREVIOUS_TEXT_MAX = 50
# Сколько сегментов держим для сопоставления с diarized_transcript
TRACKER_LIMIT = 500


@dataclass(frozen=True)
class LiveOptions:
    """Опции сессии. level: 0 — все; 1 — без «новых» опций; 2 — ещё и без keyterms."""
    language: str = "ru"
    secondary_languages: tuple[str, ...] = ()
    multilang: bool = True
    diarize: bool = True
    commit_strategy: str = "turn_prediction"
    keyterm_library: bool = True
    keepalive_secs: int = 5

    @classmethod
    def from_settings(cls, settings) -> "LiveOptions":
        secondary = tuple(
            c for c in (x.strip() for x in (settings.elevenlabs_live_secondary_languages or "").split(",")) if c
        )
        strategy = (settings.elevenlabs_live_commit_strategy or "").strip().lower()
        return cls(
            language=(settings.elevenlabs_live_language or "").strip(),
            secondary_languages=secondary,
            multilang=bool(settings.elevenlabs_live_multilang),
            diarize=bool(settings.elevenlabs_live_diarize),
            commit_strategy=strategy if strategy in ("vad", "turn_prediction") else "vad",
            keyterm_library=bool(settings.elevenlabs_live_keyterm_library),
            keepalive_secs=max(1, int(settings.elevenlabs_live_keepalive_secs)),
        )

    def degraded(self) -> "LiveOptions":
        """Уровень 1: без multilang, diarize, turn_prediction, keyterm_library, secondary_languages."""
        return replace(
            self, secondary_languages=(), multilang=False, diarize=False,
            commit_strategy="vad", keyterm_library=False,
        )


def _flag(value: bool) -> str:
    return "true" if value else "false"


def build_ws_url(
    base_url: str, *, model: str, sample_rate: int, options: LiveOptions,
    language_code: Optional[str], keyterms: list[str], send_keepalive: bool,
) -> str:
    """URL сессии. Повторяющиеся параметры (secondary_languages, keyterms) — через doseq."""
    params: list[tuple[str, object]] = [
        ("model_id", model),
        ("audio_format", f"pcm_{sample_rate}"),
        ("include_timestamps", _flag(True)),
        ("include_language_detection", _flag(True)),
        ("commit_strategy", options.commit_strategy),
        # Production VAD: тишина 1.0 с до коммита, порог 0.5 (меньше шума), речь ≥250 мс, пауза ≥300 мс.
        # ElevenLabs: частые коммиты ухудшают качество.
        ("vad_silence_threshold_secs", 1.0),
        ("vad_threshold", 0.5),
        ("min_speech_duration_ms", 250),
        ("min_silence_duration_ms", 300),
    ]
    if language_code:
        params.append(("language_code", language_code))
    params += [("secondary_languages", c) for c in options.secondary_languages]
    params += [("keyterms", t) for t in keyterms]
    if options.multilang:
        params.append(("multilang_mode", _flag(True)))
    if options.diarize:
        params.append(("diarize", _flag(True)))
    if send_keepalive:
        params.append(("keepalive_interval_ms", min(10000, max(500, options.keepalive_secs * 1000))))
    return f"{base_url}?{urlencode(params, doseq=True)}"


def trim_previous_text(text: str, limit: int = PREVIOUS_TEXT_MAX) -> str:
    """Последние ≤limit символов текста, начало — по границе слова."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    tail = text[-limit:]
    if not text[-limit - 1].isspace():
        _head, sep, rest = tail.partition(" ")
        tail = rest if sep else ""
    return tail.strip()


def clip_keyterm_library(terms: list[str]) -> list[str]:
    """Библиотека в лимитах API: ≤10 000 терминов, ≤50 символов, ≤2 МБ (UTF-8), без пустых."""
    out: list[str] = []
    total = 0
    for raw in terms:
        term = (raw or "").strip()
        if not term or len(term) > LIBRARY_MAX_CHARS:
            continue
        size = len(term.encode("utf-8"))
        if len(out) >= LIBRARY_MAX_TERMS or total + size > LIBRARY_MAX_BYTES:
            break
        out.append(term)
        total += size
    return out


def silence_pcm(sample_rate: int, ms: int = 100) -> bytes:
    """Тишина PCM16 mono."""
    return bytes(2 * sample_rate * ms // 1000)


class SessionTimeline:
    """Время внутри сессии ElevenLabs → позиция в записи встречи (секунды реального звука).

    Таймстемпы слов в каждой новой сессии идут с нуля; в сессию к тому же попадает служебная
    тишина-keepalive и не попадают выброшенные устаревшие чанки. audio_recorder пишет только
    реальный звук подряд, поэтому start/end реплик (плеер, нарезка) считаем по нему. Для первой
    сессии без пауз сдвиг нулевой — как до перехода на прямой WebSocket.
    Опорные точки: (время сессии, позиция в записи) на каждом разрыве.
    """

    GAP_EPS = 0.02

    def __init__(self) -> None:
        self._recorded = 0.0  # секунд реального звука из очереди (отправленного и выброшенного)
        self._sent = 0.0      # секунд, отправленных в текущую сессию (звук + тишина)
        self._points: list[tuple[float, float]] = []

    def start_session(self) -> None:
        self._sent = 0.0
        self._points = []

    def on_silence_sent(self, seconds: float) -> None:
        self._sent += seconds

    def on_real_sent(self, seconds: float) -> None:
        """Реальный чанк отправлен (вызывать до advance_recorded)."""
        if not self._points:
            self._points.append((self._sent, self._recorded))
        else:
            last_session, last_recorded = self._points[-1]
            if abs(self._recorded - (last_recorded + self._sent - last_session)) > self.GAP_EPS:
                self._points.append((self._sent, self._recorded))
        self._sent += seconds

    def advance_recorded(self, seconds: float) -> None:
        """Чанк из очереди обработан (отправлен, выброшен или потерян при ошибке) — он в записи."""
        self._recorded += seconds

    def to_meeting(self, session_s: float) -> float:
        offset = 0.0
        for point_session, point_recorded in self._points:
            if point_session > session_s:
                break
            offset = point_recorded - point_session
        return session_s + offset


@dataclass
class _TrackedSegment:
    segment: Any
    text: str
    speakers: Counter = field(default_factory=Counter)  # сырые speaker_id → число слов
    label: Optional[str] = None
    diarized: bool = False


def _norm(text: str) -> str:
    return " ".join((text or "").split())


class DiarizationTracker:
    """diarized_transcript / speakers_merged → метка говорящего у committed-сегмента.

    segment_index приходит в committed_transcript (не в …_with_timestamps), поэтому берём его из
    сообщения, а если нет — считаем сами по порядку коммитов сессии. Совпадение всегда сверяем
    по тексту: при расхождении счёта ищем сегмент с тем же текстом. Метки с номером сессии
    («s1_speaker_0») — стабильны между реконнектами: speaker_id в новой сессии начинаются заново.
    """

    def __init__(self, session_no: int) -> None:
        self.session_no = session_no
        self._by_index: dict[int, _TrackedSegment] = {}
        self._merged: dict[str, str] = {}
        self._pending: dict[int, dict] = {}
        self._plain_index: dict[str, list[int]] = {}
        self._counter = 0

    def note_plain_commit(self, index: Optional[int], text: str) -> None:
        """committed_transcript (без таймстемпов) принёс segment_index — запоминаем по тексту."""
        if isinstance(index, int):
            if len(self._plain_index) > 200:
                self._plain_index.clear()
            self._plain_index.setdefault(_norm(text), []).append(index)

    def next_index(self, explicit: Optional[int], text: str) -> int:
        """Индекс очередного committed_with_timestamps (счётчик растёт и на пустых коммитах)."""
        counted = self._counter
        self._counter += 1
        if isinstance(explicit, int):
            return explicit
        queue = self._plain_index.get(_norm(text))
        if queue:
            return queue.pop(0)
        return counted

    def register(self, index: int, segment: Any, text: str) -> Optional[tuple[Any, str]]:
        self._by_index[index] = _TrackedSegment(segment=segment, text=_norm(text))
        while len(self._by_index) > TRACKER_LIMIT:
            self._by_index.pop(next(iter(self._by_index)))
        pending = self._pending.pop(index, None)
        return self.on_diarized(pending) if pending else None

    def _resolve(self, speaker: str) -> str:
        seen = {speaker}
        while speaker in self._merged:
            speaker = self._merged[speaker]
            if speaker in seen:
                break
            seen.add(speaker)
        return speaker

    def _label(self, item: _TrackedSegment) -> Optional[str]:
        resolved: Counter = Counter()
        for raw, count in item.speakers.items():
            resolved[self._resolve(raw)] += count
        if not resolved:
            return None
        return f"s{self.session_no}_{resolved.most_common(1)[0][0]}"

    def _find(self, index: object, text: str) -> Optional[_TrackedSegment]:
        # Дока: сопоставлять по segment_index, а не по тексту — текст лишь запасной путь
        item = self._by_index.get(index) if isinstance(index, int) else None
        if item is not None:
            return item
        for candidate in reversed(self._by_index.values()):
            if candidate.text == text and not candidate.diarized:
                return candidate
        return None

    def on_diarized(self, data: dict) -> Optional[tuple[Any, str]]:
        """Вернуть (сегмент, метка), если метка определена и изменилась."""
        text = _norm(data.get("text", ""))
        index = data.get("segment_index")
        item = self._find(index, text)
        if item is None:
            if isinstance(index, int) and index not in self._by_index and len(self._pending) < 50:
                self._pending[index] = data  # diarized пришёл раньше своего committed
            return None
        words = data.get("words") or []
        counts = Counter(
            w["speaker_id"] for w in words
            if isinstance(w, dict) and w.get("speaker_id") and w.get("type", "word") == "word"
        )
        if not counts:
            counts = Counter(w["speaker_id"] for w in words if isinstance(w, dict) and w.get("speaker_id"))
        item.speakers = counts
        item.diarized = True
        label = self._label(item)
        if label is None or label == item.label:
            return None
        item.label = label
        return item.segment, label

    def on_merged(self, from_id: Optional[str], to_id: Optional[str]) -> list[tuple[Any, str]]:
        """speakers_merged: пересчитать метки сегментов, у которых она изменилась."""
        if not from_id or not to_id or from_id == to_id:
            return []
        self._merged[from_id] = to_id
        changed: list[tuple[Any, str]] = []
        for item in self._by_index.values():
            if not item.diarized:
                continue
            label = self._label(item)
            if label is not None and label != item.label:
                item.label = label
                changed.append((item.segment, label))
        return changed
