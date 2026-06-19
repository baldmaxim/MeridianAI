"""Контроллер авторитетного источника транскрипта (Этап 9.8).

Per-room runtime: РУЧНОЙ promote single→multi, manual/auto fallback, recovery после
рестарта, состояние/качество для WS/REST, сохранение multi-finals и in-memory провайдер
авторитетного текста. Авто-promote ОТСУТСТВУЕТ. Авто-fallback — только при ЖЁСТКОМ сбое
live. По умолчанию выключено (rollout 0% + allowlist). Single STT всегда работает как hot
standby и не затрагивается.
"""

import asyncio
import logging
import time
from typing import Optional

from ..config import get_settings
from ..database import async_session
from .audit import audit
from .authoritative_transcript import (
    SOURCE_SINGLE, SOURCE_MULTI, SingleSegmentView, MultiSegmentView,
    build_authoritative_transcript,
)
from .multi_channel_cutover_quality import evaluate_cutover_quality, CutoverQualityReport
from .multi_channel_cutover_rollout import evaluate_cutover_rollout, RolloutDecision
from . import transcription_epochs as epochs_svc
from . import persisted_multi_channel_transcript as mc_store

logger = logging.getLogger("meridian.cutover")


def _now_ms() -> int:
    return int(time.time() * 1000)


class TranscriptionAuthorityController:
    def __init__(self, *, meeting_id: int, owner_user_id: int | None,
                 get_session, get_live, get_reconciliation_summary,
                 get_channel_clock_quality, broadcast, now_ms_fn=None):
        self.meeting_id = meeting_id
        self.owner_user_id = owner_user_id
        self._get_session = get_session                  # () -> SessionManager
        self._get_live = get_live                        # () -> MultiChannelLiveSession | None
        self._get_recon = get_reconciliation_summary     # () -> (matched, total) | None
        self._get_clock = get_channel_clock_quality      # () -> dict[int, str|None]
        self._broadcast = broadcast                      # async def(event)
        self._now_ms = now_ms_fn or _now_ms

        self.current_source = SOURCE_SINGLE
        self.epochs_count = 0
        self.revision = 0
        self.fallback_used = False
        self.open_multi_epoch_id: Optional[int] = None
        self.last_switch: Optional[dict] = None
        self.last_quality: Optional[CutoverQualityReport] = None
        self._epoch_views: list = []
        # сериализует read-modify-write эпох (promote/fallback/recover/finalize), чтобы
        # параллельные переключения не коллизировали по uq_transcription_epoch_meeting_index.
        self._switch_lock = asyncio.Lock()
        # кэш числа сохранённых multi-сегментов (cap-guard без COUNT(*) на каждый final)
        self._persisted_multi_count: Optional[int] = None

    # ---------------- load / recover ----------------

    async def load(self) -> None:
        try:
            async with async_session() as db:
                epochs = await epochs_svc.load_epochs(db, self.meeting_id)
            self._apply_epochs(epochs)
        except Exception:
            logger.exception("[cutover %s] load failed", self.meeting_id)

    def _apply_epochs(self, epochs) -> None:
        self._epoch_views = epochs_svc.epoch_records_to_views(epochs)
        self.epochs_count = len(epochs)
        self.current_source = epochs_svc.current_source_from_epochs(epochs)
        open_ep = epochs_svc.open_epoch(epochs)
        self.open_multi_epoch_id = open_ep.id if (open_ep and open_ep.source == SOURCE_MULTI) else None

    async def recover(self) -> None:
        """После рестарта live не активна. Открытая multi-эпоха → авто-fallback на single."""
        if self.current_source != SOURCE_MULTI:
            return
        async with self._switch_lock:
            if self.current_source != SOURCE_MULTI:    # перепроверка под локом
                return
            ok = await self._do_switch(to_source=SOURCE_SINGLE, reason="recovery_fallback",
                                       by_user_id=None, automatic=True,
                                       audit_event="transcription_cutover_recovery")
            if ok:
                self.fallback_used = True
        await self.broadcast_state()

    # ---------------- rollout / quality ----------------

    def rollout_decision(self) -> RolloutDecision:
        s = get_settings()
        return evaluate_cutover_rollout(
            meeting_id=self.meeting_id, owner_user_id=self.owner_user_id,
            enabled=s.multi_channel_cutover_enabled,
            rollout_percent=s.multi_channel_cutover_rollout_percent,
            allowlist_user_ids=s.multi_channel_cutover_allowlist_user_ids_set,
            allowlist_meeting_ids=s.multi_channel_cutover_allowlist_meeting_ids_set,
        )

    def evaluate_quality(self) -> CutoverQualityReport:
        s = get_settings()
        live = self._get_live()
        status = live.state.status if live else "idle"
        channel_count = len(live.state.channels) if live else 0
        finals = len(live.state.final_segments) if live else 0
        sec_sil: list[float] = []
        if live:
            ratios = list(getattr(live.state, "silence_ratio_by_channel", []) or [])
            for c in live.state.channels:
                if getattr(c, "source_kind", None) == "secondary" and c.channel_index < len(ratios):
                    sec_sil.append(ratios[c.channel_index])
        clock = self._get_clock() or {}
        recon = self._get_recon()
        matched, total = recon if recon else (0, 0)
        report = evaluate_cutover_quality(
            live_status=status, channel_count=channel_count,
            min_channels=s.multi_channel_live_min_channels,
            final_segment_count=finals, min_final_segments=s.multi_channel_cutover_min_final_segments,
            secondary_silence_ratios=sec_sil,
            max_secondary_silence_ratio=s.multi_channel_cutover_max_secondary_silence_ratio,
            channel_clock_quality=clock,
            reconciliation_matched=matched, reconciliation_total=total,
            min_match_ratio=s.multi_channel_cutover_min_match_ratio,
        )
        self.last_quality = report
        return report

    @staticmethod
    def _live_active(live) -> bool:
        return live is not None and live.state.status in ("streaming", "degraded")

    # ---------------- promote / fallback ----------------

    async def promote(self, *, by_user_id: int | None, reason: str = "manual_promote",
                      force: bool = False) -> dict:
        s = get_settings()
        async with self._switch_lock:
            rollout = self.rollout_decision()
            if not rollout.allowed:
                code = "FEATURE_DISABLED" if rollout.reason == "feature_disabled" else "NOT_IN_ROLLOUT"
                return self._err(code, "Cutover недоступен для этой встречи")
            if self.current_source == SOURCE_MULTI:
                return self._err("ALREADY_MULTI", "Транскрипт уже multi-channel")
            live = self._get_live()
            if not self._live_active(live):
                return self._err("LIVE_NOT_ACTIVE", "Live multi-channel сессия не активна")
            quality = self.evaluate_quality()
            use_force = bool(force) and s.multi_channel_cutover_allow_force
            if s.multi_channel_cutover_require_quality_gate and not quality.ok and not use_force:
                return self._err("QUALITY_GATE_FAILED", "Качество недостаточно для продвижения",
                                 quality=quality)
            ok = await self._do_switch(
                to_source=SOURCE_MULTI,
                reason=f"{reason}_forced" if use_force else reason,
                by_user_id=by_user_id, automatic=False,
                live_session_id=live.session_id, audit_event="transcription_promote")
            if not ok:
                return self._err("SWITCH_FAILED", "Не удалось переключить источник транскрипта")
        await self.broadcast_state()
        return {"ok": True, "state": self.state_dict()}

    async def fallback(self, *, by_user_id: int | None = None, reason: str = "manual_fallback",
                       automatic: bool = False) -> dict:
        async with self._switch_lock:
            if self.current_source != SOURCE_MULTI:
                return self._err("ALREADY_SINGLE", "Транскрипт уже single")
            ok = await self._do_switch(
                to_source=SOURCE_SINGLE, reason=reason, by_user_id=by_user_id, automatic=automatic,
                audit_event="transcription_auto_fallback" if automatic else "transcription_fallback")
            if not ok:
                return self._err("SWITCH_FAILED", "Не удалось переключить источник транскрипта")
            if automatic:
                self.fallback_used = True
        await self.broadcast_state()
        return {"ok": True, "state": self.state_dict()}

    async def close_open_epoch_on_finalize(self) -> None:
        """Закрыть открытую эпоху на границе финализации (детерминированный end_server_ms)."""
        if self.epochs_count == 0:
            return  # cutover не применялся — строк нет, ничего закрывать
        at = self._now_ms()
        async with self._switch_lock:
            try:
                async with async_session() as db:
                    await epochs_svc.close_open_epoch(db, self.meeting_id, at)
                    await db.commit()
                    epochs = await epochs_svc.load_epochs(db, self.meeting_id)
                self._apply_epochs(epochs)
            except Exception:
                logger.debug("[cutover %s] close_open_epoch failed", self.meeting_id)

    async def on_live_failure(self) -> None:
        """Live упала/остановилась пока promoted → авто-fallback (если включено)."""
        s = get_settings()
        if self.current_source == SOURCE_MULTI and s.multi_channel_cutover_auto_fallback_on_failure:
            await self.fallback(reason="auto_fallback_failure", automatic=True)

    async def _do_switch(self, *, to_source: str, reason: str, by_user_id: int | None,
                         automatic: bool, live_session_id: str | None = None,
                         audit_event: str | None = None) -> bool:
        """Применить переключение источника. Вызывать ПОД self._switch_lock. True если применено."""
        at = self._now_ms()
        try:
            async with async_session() as db:
                await epochs_svc.switch_to(
                    db, self.meeting_id, to_source=to_source, at_server_ms=at, reason=reason,
                    by_user_id=by_user_id, live_session_id=live_session_id, automatic=automatic)
                await db.commit()
                epochs = await epochs_svc.load_epochs(db, self.meeting_id)
            self._apply_epochs(epochs)
            self._persisted_multi_count = None    # пере-сидируется при следующем persist
        except Exception:
            logger.exception("[cutover %s] switch_to failed", self.meeting_id)
            return False
        self.revision += 1
        self.last_switch = {"to_source": to_source, "reason": reason, "automatic": automatic,
                            "at_server_ms": at, "by_user_id": by_user_id}
        if audit_event:
            try:
                await audit(audit_event, actor_user_id=by_user_id, meeting_id=self.meeting_id,
                            to_source=to_source, reason=reason, automatic=automatic)
            except Exception:
                pass
        logger.info("[cutover %s] switch -> %s (%s, auto=%s)",
                    self.meeting_id, to_source, reason, automatic)
        return True

    def _err(self, code: str, message: str, quality: CutoverQualityReport | None = None) -> dict:
        d = {"ok": False, "code": code, "message": message, "state": self.state_dict()}
        if quality is not None:
            d["quality"] = quality.to_dict()
        return d

    # ---------------- persistence of multi finals ----------------

    async def persist_live_final(self, seg) -> None:
        if self.current_source != SOURCE_MULTI:
            return
        s = get_settings()
        cap = s.multi_channel_cutover_max_persisted_segments
        try:
            async with async_session() as db:
                if self._persisted_multi_count is None:
                    # ленивое сидирование один раз на эпоху — без COUNT(*) на каждый final
                    self._persisted_multi_count = await mc_store.count_segments(db, self.meeting_id)
                if self._persisted_multi_count >= cap:
                    return
                inserted = await mc_store.persist_segment(
                    db, meeting_id=self.meeting_id, epoch_id=self.open_multi_epoch_id,
                    live_session_id=getattr(seg, "session_id", "") or "", seg=seg,
                    provider=s.multi_channel_live_provider)
                if inserted:
                    await db.commit()
                    self._persisted_multi_count += 1
        except Exception:
            logger.debug("[cutover %s] persist live final failed", self.meeting_id)

    # ---------------- in-memory authoritative provider (sync) ----------------

    def live_authoritative_text(self, recent: bool):
        """fn(recent) для PromptContextBuilder. None → single (поведение без изменений)."""
        if self.current_source != SOURCE_MULTI:
            return None
        live = self._get_live()
        session = self._get_session()
        if not self._live_active(live) or session is None:
            return None
        s = get_settings()
        single_views: list[SingleSegmentView] = []
        for seg in list(session.committed_segments):
            try:
                speaker, side = session._resolve_segment(seg)
            except Exception:
                speaker, side = None, None
            single_views.append(SingleSegmentView(
                segment_key=getattr(seg, "segment_id", "") or "", text=seg.text or "",
                speech_start_ms=seg.effective_speech_start_ms,
                speech_end_ms=seg.effective_speech_end_ms, side=side, speaker=speaker))
        multi_views = [
            MultiSegmentView(segment_key=m.segment_id, text=m.transcript, side=m.side,
                             channel_label=m.channel_label, start_server_ms=m.start_server_ms,
                             end_server_ms=m.end_server_ms)
            for m in list(live.state.final_segments)
        ]
        transcript = build_authoritative_transcript(
            epochs=self._epoch_views, single_segments=single_views, multi_segments=multi_views,
            boundary_dedupe_ms=s.multi_channel_cutover_boundary_dedupe_ms,
            boundary_dedupe_similarity=s.multi_channel_cutover_boundary_dedupe_similarity)
        if recent:
            return transcript.recent_text(
                now_ms=self._now_ms(), minutes=s.multi_channel_cutover_recent_minutes,
                max_chars=s.context_pack_recent_dialog_max_chars)
        return transcript.full_text(max_chars=s.multi_channel_cutover_max_transcript_chars)

    # ---------------- state ----------------

    def state_dict(self) -> dict:
        rollout = self.rollout_decision()
        return {
            "meeting_id": self.meeting_id,
            "current_source": self.current_source,
            "revision": self.revision,
            "fallback_used": self.fallback_used,
            "epochs_count": self.epochs_count,
            "can_promote": rollout.allowed and self.current_source == SOURCE_SINGLE,
            "rollout": {"allowed": rollout.allowed, "reason": rollout.reason, "bucket": rollout.bucket},
            "quality": self.last_quality.to_dict() if self.last_quality else None,
            "last_switch": self.last_switch,
        }

    async def broadcast_state(self) -> None:
        try:
            await self._broadcast({"type": "transcription_authority_state", **self.state_dict()})
        except Exception:
            pass


# ---------------- module-level: post-hoc authoritative from DB ----------------

async def build_authoritative_from_db(db, meeting_id: int):
    """Авторитетный транскрипт из БД (эпохи + single + multi). None если эпох нет."""
    from ..models.meeting import TranscriptSegmentRecord
    from sqlalchemy import select

    epochs = await epochs_svc.load_epochs(db, meeting_id)
    if not epochs:
        return None

    from .speaker_corrections import list_segment_corrections, resolve_speaker_for_segment
    from .speaker_roles import get_roles_map
    corrections = await list_segment_corrections(db, meeting_id)
    roles = await get_roles_map(db, meeting_id)

    seg_rows = (await db.execute(
        select(TranscriptSegmentRecord)
        .where(TranscriptSegmentRecord.session_id == meeting_id)
    )).scalars().all()
    single_views: list[SingleSegmentView] = []
    for s in seg_rows:
        original = s.speaker_label or s.speaker_id
        resolved = resolve_speaker_for_segment(s.segment_id, original, corrections, roles)
        sstart = s.speech_start_ms if s.speech_start_ms is not None else int(s.wall_clock.timestamp() * 1000)
        send = s.speech_end_ms if s.speech_end_ms is not None else sstart
        single_views.append(SingleSegmentView(
            segment_key=s.segment_id, text=s.text or "", speech_start_ms=sstart,
            speech_end_ms=send, side=resolved.side,
            speaker=resolved.effective_speaker_label or original))

    multi_rows = await mc_store.load_segments(db, meeting_id)
    multi_views = [mc_store.record_to_view(m) for m in multi_rows]

    settings = get_settings()
    return build_authoritative_transcript(
        epochs=epochs_svc.epoch_records_to_views(epochs),
        single_segments=single_views, multi_segments=multi_views,
        boundary_dedupe_ms=settings.multi_channel_cutover_boundary_dedupe_ms,
        boundary_dedupe_similarity=settings.multi_channel_cutover_boundary_dedupe_similarity)
