"""Общая подготовка многоканального аудио (Этап 9.4/9.5).

Единый internal helper, которым пользуются И WAV-export API, И batch multi-channel STT,
чтобы track order / window / offsets / validation / channel mapping были идентичны.
Backend НЕ дёргает собственный HTTP WAV endpoint — всё через эти функции.

prepare_multi_channel_audio синхронна (без await) → snapshot атомарен к ingest.
build_prepared_wav выносит тяжёлую сборку PCM в threadpool.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime

from .multi_source_ingest import MultiSourceWindowSnapshot
from .multi_channel_wav import (
    MultiChannelExportError,
    MultiChannelExportPlan,
    build_export_plan,
    build_multi_channel_wav,
    default_channel_order,
    export_plan_to_manifest,
    resolve_export_window,
)


@dataclass(frozen=True)
class PreparedMultiChannelAudio:
    snapshot: MultiSourceWindowSnapshot
    plan: MultiChannelExportPlan
    manifest: dict
    channel_mapping: tuple  # tuple[dict, ...] — channel_index→track/label/side/source_kind


def prepare_multi_channel_audio(*, room, request, settings, meeting_id: int,
                                created_at: datetime) -> PreparedMultiChannelAudio:
    """Подготовить snapshot+plan+manifest+channel_mapping из live ingest-окна.

    Чистая логика поверх ingest; HTTP-уровень не трогает. Бросает MultiChannelExportError
    (коды как в multi_channel_wav). Вызывать синхронно (без await вокруг) — атомарно к ingest.
    """
    ingest = room.ingest
    now_ms = int(time.time() * 1000)
    clock_quality = {
        cid: (conn.clock.quality if getattr(conn, "clock", None) else None)
        for cid, conn in room.connections.items()
    }
    active_source = room.active_audio_source
    exportable = ingest.list_exportable_tracks(
        include_stopped=request.include_stopped, now_ms=now_ms,
        clock_quality_by_track=clock_quality,
    )
    for t in exportable:
        t["is_active"] = (t["track_id"] == active_source)
    by_id = {t["track_id"]: t for t in exportable}
    if not exportable:
        raise MultiChannelExportError("NO_AUDIO_DATA", "Нет аудиоданных в ingest")

    if request.track_ids:
        missing = [tid for tid in request.track_ids if tid not in by_id]
        if missing:
            raise MultiChannelExportError("TRACK_NOT_FOUND", f"Треки не найдены: {missing}")
        ordered = list(request.track_ids)
    else:
        ordered = default_channel_order(exportable)[:settings.multi_channel_export_max_channels]

    selected_dicts = [by_id[tid] for tid in ordered]

    try:
        start_index, end_index = resolve_export_window(
            tracks=selected_dicts, mode=request.window_mode, frame_ms=ingest.frame_ms,
            default_seconds=settings.multi_channel_export_default_seconds,
            max_seconds=settings.multi_channel_export_max_seconds,
            duration_seconds=request.duration_seconds,
            start_server_ms=request.start_server_ms, end_server_ms=request.end_server_ms,
        )
        snapshot = ingest.snapshot_window(
            track_ids=ordered, start_index=start_index, end_index=end_index,
            now_ms=now_ms, clock_quality_by_track=clock_quality,
        )
        plan = build_export_plan(
            snapshot=snapshot, ordered_track_ids=ordered,
            offsets_ms=request.channel_offsets_ms,
            max_channels=settings.multi_channel_export_max_channels,
            max_seconds=settings.multi_channel_export_max_seconds,
            max_bytes=settings.multi_channel_export_max_bytes,
            max_offset_ms=settings.multi_channel_export_max_offset_ms,
        )
    except KeyError as e:
        raise MultiChannelExportError("TRACK_NOT_FOUND", f"Трек не найден: {e}")
    except ValueError as e:
        raise MultiChannelExportError("INVALID_WINDOW", str(e))

    manifest = export_plan_to_manifest(plan, meeting_id=meeting_id, created_at=created_at)
    channel_mapping = tuple({
        "channel_index": c.channel_index,
        "track_id": c.track_id,
        "channel_label": c.label,
        "side_hint": c.side_hint,
        "source_kind": c.source_kind,
        "generation": c.generation,
        "offset_ms": c.offset_ms,
    } for c in plan.channels)

    return PreparedMultiChannelAudio(
        snapshot=snapshot, plan=plan, manifest=manifest, channel_mapping=channel_mapping,
    )


async def build_prepared_wav(prepared: PreparedMultiChannelAudio) -> bytes:
    """Собрать WAV (тяжёлый PCM) вне event loop. Файлы на диск не пишутся."""
    return await asyncio.to_thread(
        build_multi_channel_wav, snapshot=prepared.snapshot, plan=prepared.plan,
    )
