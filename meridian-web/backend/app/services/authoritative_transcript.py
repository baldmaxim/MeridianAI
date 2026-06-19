"""Авторитетный транскрипт встречи поверх эпох (Этап 9.8) — чистый, тестируемый.

Собирает единый транскрипт из набора эпох + сегментов двух источников:
- single   → committed STT сегменты (по speech-time),
- multi_channel → сохранённые normalized multi-channel сегменты.

Для каждой эпохи берутся сегменты ЕЁ источника, попадающие в [start, end). На стыке
источников выполняется boundary-dedupe (одна и та же реплика могла попасть в оба источника
у границы). Без эпох — поведение single-only (как до cutover). Никакого I/O/времени-now."""

from dataclasses import dataclass

from .multi_channel_reconciliation import (
    normalize_reconciliation_text,
    text_similarity_score,
)

SOURCE_SINGLE = "single"
SOURCE_MULTI = "multi_channel"

_SIDE_LABELS = {"self": "МЫ", "opponent": "НЕ МЫ"}


@dataclass(frozen=True)
class EpochView:
    epoch_index: int
    source: str
    start_server_ms: int
    end_server_ms: int | None  # None = открытая (текущая) эпоха


@dataclass(frozen=True)
class SingleSegmentView:
    segment_key: str
    text: str
    speech_start_ms: int
    speech_end_ms: int
    side: str | None = None
    speaker: str | None = None


@dataclass(frozen=True)
class MultiSegmentView:
    segment_key: str
    text: str
    start_server_ms: int
    end_server_ms: int
    side: str | None = None
    channel_label: str | None = None


@dataclass(frozen=True)
class AuthoritativeSegment:
    segment_key: str
    source: str
    side: str | None
    speaker: str | None
    text: str
    start_ms: int
    end_ms: int

    def to_dict(self) -> dict:
        return {
            "segment_key": self.segment_key, "source": self.source, "side": self.side,
            "speaker": self.speaker, "text": self.text,
            "start_ms": self.start_ms, "end_ms": self.end_ms,
        }


def _in_range(ts: int, start: int, end: int | None) -> bool:
    if ts < start:
        return False
    return end is None or ts < end


def _format_tc(ms: int, origin_ms: int) -> str:
    sec = max(0, (ms - origin_ms) // 1000)
    return f"{sec // 60:02d}:{sec % 60:02d}"


@dataclass
class AuthoritativeTranscript:
    segments: list
    epochs_count: int
    sources_used: tuple

    def _label(self, seg: AuthoritativeSegment) -> str:
        if seg.side and seg.side in _SIDE_LABELS:
            return _SIDE_LABELS[seg.side]
        return seg.speaker or "—"

    def _render(self, segs: list, max_chars: int | None) -> str:
        if not segs:
            return ""
        origin = min(s.start_ms for s in segs)
        lines = []
        for s in segs:
            tc = _format_tc(s.start_ms, origin)
            lines.append(f"[{tc}] {self._label(s)}: {s.text}")
        text = "\n".join(lines)
        if max_chars is not None and len(text) > max_chars:
            # сохраняем хвост (свежие реплики важнее в подсказках), но по границе строки —
            # иначе первая строка обрезается посреди «[mm:ss] СТОРОНА: …» и теряет префикс.
            text = text[-max_chars:]
            nl = text.find("\n")
            if nl != -1:
                text = text[nl + 1:]
        return text

    def recent_text(self, *, now_ms: int, minutes: int, max_chars: int | None = None) -> str:
        cutoff = now_ms - minutes * 60_000
        segs = [s for s in self.segments if s.end_ms >= cutoff]
        return self._render(segs, max_chars)

    def full_text(self, *, max_chars: int | None = None) -> str:
        return self._render(list(self.segments), max_chars)

    def to_dict(self, *, max_segments: int = 2000) -> dict:
        segs = self.segments[-max_segments:]
        return {
            "epochs_count": self.epochs_count,
            "sources_used": list(self.sources_used),
            "segment_count": len(self.segments),
            "segments": [s.to_dict() for s in segs],
            "truncated": len(self.segments) > len(segs),
        }


def _single_to_auth(s: SingleSegmentView) -> AuthoritativeSegment:
    return AuthoritativeSegment(
        segment_key=s.segment_key, source=SOURCE_SINGLE, side=s.side, speaker=s.speaker,
        text=s.text, start_ms=s.speech_start_ms, end_ms=s.speech_end_ms,
    )


def _multi_to_auth(s: MultiSegmentView) -> AuthoritativeSegment:
    return AuthoritativeSegment(
        segment_key=s.segment_key, source=SOURCE_MULTI, side=s.side,
        speaker=s.channel_label, text=s.text,
        start_ms=s.start_server_ms, end_ms=s.end_server_ms,
    )


def _boundary_dedupe(segs: list, dedupe_ms: int, similarity: float) -> list:
    """Убрать дубль одной реплики на стыке источников.

    Идём по упорядоченному списку: если соседние сегменты из РАЗНЫХ источников, близки по
    времени (в пределах dedupe_ms) и похожи по тексту (>= similarity) — оставляем более
    ранний (он принадлежит эпохе, владеющей этим временем), поздний дубль выкидываем.
    """
    if dedupe_ms <= 0 or len(segs) < 2:
        return segs
    out: list = []
    for seg in segs:
        if out:
            prev = out[-1]
            if prev.source != seg.source:
                gap = seg.start_ms - prev.end_ms
                if gap <= dedupe_ms:
                    sim = text_similarity_score(
                        normalize_reconciliation_text(prev.text),
                        normalize_reconciliation_text(seg.text),
                    )
                    if sim >= similarity:
                        continue  # дубль — не добавляем поздний
        out.append(seg)
    return out


def build_authoritative_transcript(
    *,
    epochs: list,
    single_segments: list,
    multi_segments: list,
    boundary_dedupe_ms: int = 1500,
    boundary_dedupe_similarity: float = 0.6,
) -> AuthoritativeTranscript:
    """Собрать авторитетный транскрипт. Без эпох — все single сегменты (как до cutover)."""
    sources_used: list[str] = []

    if not epochs:
        segs = sorted(
            (_single_to_auth(s) for s in single_segments),
            key=lambda x: (x.start_ms, x.segment_key),
        )
        if segs:
            sources_used = [SOURCE_SINGLE]
        return AuthoritativeTranscript(segments=segs, epochs_count=0,
                                       sources_used=tuple(sources_used))

    ordered_epochs = sorted(epochs, key=lambda e: e.epoch_index)
    result: list[AuthoritativeSegment] = []
    for ep in ordered_epochs:
        if ep.source == SOURCE_MULTI:
            picked = [
                _multi_to_auth(s) for s in multi_segments
                if _in_range(s.start_server_ms, ep.start_server_ms, ep.end_server_ms)
            ]
        else:
            picked = [
                _single_to_auth(s) for s in single_segments
                if _in_range(s.speech_start_ms, ep.start_server_ms, ep.end_server_ms)
            ]
        if not picked:
            continue
        picked.sort(key=lambda x: (x.start_ms, x.segment_key))
        if ep.source not in sources_used:
            sources_used.append(ep.source)
        result.extend(picked)

    result = _boundary_dedupe(result, boundary_dedupe_ms, boundary_dedupe_similarity)
    return AuthoritativeTranscript(
        segments=result, epochs_count=len(ordered_epochs), sources_used=tuple(sources_used),
    )
