"""Снимки сегментов для channel-aware reconciliation (Этап 9.7) — read-only.

Primary: committed-сегменты активной сессии (stable segment_key + server timestamps).
Channel: final-сегменты live multi-channel session (зафиксированный channel mapping).
Ничего не пишет в БД, не меняет roles/corrections/MeetingMemory, raw text не трогает.
"""

from .multi_channel_reconciliation import (
    ChannelTranscriptSegmentView,
    PrimaryTranscriptSegmentView,
)
from .speaker_roles import to_public_side


def build_primary_segments_for_reconciliation(*, session, limit: int) -> list:
    """Committed-сегменты активной сессии → views (последние `limit`, свежие предпочтительнее).

    segment_key = CommittedSegment.segment_id; timestamps из server_ts_ms (Этап 9.1).
    Эффективная сторона/спикер — через существующий resolver сессии (Этап 8).
    """
    segments = list(getattr(session, "committed_segments", []) or [])
    if limit > 0 and len(segments) > limit:
        segments = segments[-limit:]
    corrections = getattr(session, "speaker_segment_corrections", {}) or {}
    out = []
    for seg in segments:
        seg_key = getattr(seg, "segment_id", None)
        if not seg_key:
            continue
        try:
            start_ms = int(seg.server_ts_ms)
        except Exception:
            continue
        dur_ms = max(0, int(round((seg.end_time - seg.start_time) * 1000)))
        end_ms = start_ms + dur_ms
        original = getattr(seg, "speaker_label", None) or getattr(seg, "speaker_id", None)
        try:
            effective, side = session._resolve_segment(seg)
        except Exception:
            effective, side = original, None
        corr = corrections.get(seg_key) or {}
        out.append(PrimaryTranscriptSegmentView(
            segment_key=seg_key, text=seg.text or "",
            start_server_ms=start_ms, end_server_ms=end_ms,
            original_speaker_label=original, effective_speaker_label=effective,
            current_side=to_public_side(side),
            has_segment_correction=bool(corr.get("side") or corr.get("corrected_speaker_label")),
            correction_side=to_public_side(corr.get("side")),
            corrected_speaker_label=corr.get("corrected_speaker_label"),
        ))
    return out


def build_channel_segments_for_reconciliation(*, live_session, limit: int) -> list:
    """Final-сегменты live multi-channel session → views (interim НЕ включаются)."""
    if live_session is None:
        return []
    state = getattr(live_session, "state", None)
    if state is None:
        return []
    channel_by_index = getattr(live_session, "_channel_by_index", {}) or {}
    finals = list(state.final_segments or [])
    if limit > 0 and len(finals) > limit:
        finals = finals[-limit:]
    out = []
    for s in finals:
        ch = channel_by_index.get(s.channel_index)
        conf = s.confidence
        if conf is not None:
            conf = max(0.0, min(1.0, conf))
        out.append(ChannelTranscriptSegmentView(
            segment_id=s.segment_id, session_id=s.session_id,
            channel_index=s.channel_index, channels_count=s.channels_count,
            track_id=s.track_id,
            source_connection_id=(ch.connection_id if ch else s.track_id),
            source_kind=(ch.source_kind if ch else ""),
            generation=(ch.generation if ch else 0),
            channel_label=s.channel_label, channel_side=to_public_side(s.side),
            text=s.transcript or "",
            start_server_ms=int(s.start_server_ms), end_server_ms=int(s.end_server_ms),
            provider_confidence=conf, speech_final=bool(s.speech_final),
        ))
    return out
