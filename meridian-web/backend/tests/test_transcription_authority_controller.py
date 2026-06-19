"""Контроллер cutover: promote/fallback/recovery/quality-gate (Этап 9.8).

DB-переключение (_do_switch) подменяется фейком — проверяем оркестрацию/гейтинг без БД."""

from app.config import get_settings
from app.services.transcription_authority_controller import TranscriptionAuthorityController
from app.services.authoritative_transcript import SOURCE_SINGLE, SOURCE_MULTI, EpochView


class FakeChannel:
    def __init__(self, idx, kind):
        self.channel_index = idx
        self.source_kind = kind
        self.connection_id = f"c{idx}"


class FakeState:
    def __init__(self, status="streaming", n_finals=10, ratios=None, finals=None):
        self.status = status
        self.final_segments = finals if finals is not None else list(range(n_finals))
        self.channels = (FakeChannel(0, "primary"), FakeChannel(1, "secondary"))
        self.silence_ratio_by_channel = ratios if ratios is not None else [0.0, 0.0]


class FakeLive:
    def __init__(self, status="streaming", n_finals=10, finals=None):
        self.session_id = "sess123"
        self.state = FakeState(status=status, n_finals=n_finals, finals=finals)


def enable_cutover(monkeypatch, pct=100, **over):
    s = get_settings()
    monkeypatch.setattr(s, "multi_channel_cutover_enabled", True)
    monkeypatch.setattr(s, "multi_channel_cutover_rollout_percent", pct)
    for k, v in over.items():
        monkeypatch.setattr(s, k, v)


def make_ctrl(monkeypatch, *, live=None, recon=(8, 10), clock=None, session=None):
    events = []

    async def broadcast(ev):
        events.append(ev)

    ctrl = TranscriptionAuthorityController(
        meeting_id=1, owner_user_id=10,
        get_session=lambda: session, get_live=lambda: live,
        get_reconciliation_summary=lambda: recon,
        get_channel_clock_quality=lambda: (clock if clock is not None else {0: "good", 1: "good"}),
        broadcast=broadcast, now_ms_fn=lambda: 1_000_000)

    switches = []

    async def fake_switch(*, to_source, reason, by_user_id, automatic,
                          live_session_id=None, audit_event=None):
        switches.append({"to": to_source, "reason": reason, "automatic": automatic})
        ctrl.current_source = to_source
        ctrl.revision += 1
        ctrl.open_multi_epoch_id = 1 if to_source == SOURCE_MULTI else None
        ctrl.last_switch = {"to_source": to_source, "reason": reason, "automatic": automatic}
        return True

    monkeypatch.setattr(ctrl, "_do_switch", fake_switch)
    return ctrl, events, switches


async def test_promote_denied_when_disabled(monkeypatch):
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive())
    r = await ctrl.promote(by_user_id=10)
    assert r["ok"] is False and r["code"] == "FEATURE_DISABLED" and switches == []


async def test_promote_denied_when_live_inactive(monkeypatch):
    enable_cutover(monkeypatch)
    ctrl, events, switches = make_ctrl(monkeypatch, live=None)
    r = await ctrl.promote(by_user_id=10)
    assert r["ok"] is False and r["code"] == "LIVE_NOT_ACTIVE" and switches == []


async def test_promote_quality_gate_blocks_then_force(monkeypatch):
    enable_cutover(monkeypatch)
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive(n_finals=1))
    r = await ctrl.promote(by_user_id=10)
    assert r["ok"] is False and r["code"] == "QUALITY_GATE_FAILED" and "quality" in r
    assert switches == []
    r2 = await ctrl.promote(by_user_id=10, force=True)
    assert r2["ok"] is True and ctrl.current_source == SOURCE_MULTI
    assert switches[-1]["to"] == SOURCE_MULTI and switches[-1]["reason"].endswith("_forced")


async def test_promote_force_respects_allow_force_off(monkeypatch):
    enable_cutover(monkeypatch, multi_channel_cutover_allow_force=False)
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive(n_finals=1))
    r = await ctrl.promote(by_user_id=10, force=True)
    assert r["ok"] is False and r["code"] == "QUALITY_GATE_FAILED"


async def test_promote_success_healthy_broadcasts(monkeypatch):
    enable_cutover(monkeypatch)
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive(n_finals=10))
    r = await ctrl.promote(by_user_id=10)
    assert r["ok"] is True and ctrl.current_source == SOURCE_MULTI
    assert any(e.get("type") == "transcription_authority_state" for e in events)


async def test_promote_idempotent_when_already_multi(monkeypatch):
    enable_cutover(monkeypatch)
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive(n_finals=10))
    await ctrl.promote(by_user_id=10)
    r = await ctrl.promote(by_user_id=10)
    assert r["ok"] is False and r["code"] == "ALREADY_MULTI"


async def test_fallback_requires_multi(monkeypatch):
    enable_cutover(monkeypatch)
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive())
    r = await ctrl.fallback()
    assert r["ok"] is False and r["code"] == "ALREADY_SINGLE"


async def test_fallback_after_promote(monkeypatch):
    enable_cutover(monkeypatch)
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive(n_finals=10))
    await ctrl.promote(by_user_id=10)
    r = await ctrl.fallback(by_user_id=10)
    assert r["ok"] is True and ctrl.current_source == SOURCE_SINGLE


async def test_on_live_failure_auto_fallback(monkeypatch):
    enable_cutover(monkeypatch, multi_channel_cutover_auto_fallback_on_failure=True)
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive(n_finals=10))
    await ctrl.promote(by_user_id=10)
    await ctrl.on_live_failure()
    assert ctrl.current_source == SOURCE_SINGLE and ctrl.fallback_used is True
    assert switches[-1]["automatic"] is True and switches[-1]["reason"] == "auto_fallback_failure"


async def test_on_live_failure_noop_when_disabled(monkeypatch):
    enable_cutover(monkeypatch, multi_channel_cutover_auto_fallback_on_failure=False)
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive(n_finals=10))
    await ctrl.promote(by_user_id=10)
    before = len(switches)
    await ctrl.on_live_failure()
    assert len(switches) == before and ctrl.current_source == SOURCE_MULTI


async def test_recover_stale_multi_falls_back(monkeypatch):
    enable_cutover(monkeypatch)
    ctrl, events, switches = make_ctrl(monkeypatch, live=None)
    ctrl.current_source = SOURCE_MULTI            # имитация открытой multi-эпохи после рестарта
    await ctrl.recover()
    assert ctrl.current_source == SOURCE_SINGLE and ctrl.fallback_used is True
    assert switches[-1]["reason"] == "recovery_fallback"


async def test_recover_noop_when_single(monkeypatch):
    enable_cutover(monkeypatch)
    ctrl, events, switches = make_ctrl(monkeypatch, live=None)
    await ctrl.recover()
    assert switches == []


async def test_promote_switch_failure_returns_error(monkeypatch):
    enable_cutover(monkeypatch)
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive(n_finals=10))

    async def failing_switch(**kw):
        return False

    monkeypatch.setattr(ctrl, "_do_switch", failing_switch)
    r = await ctrl.promote(by_user_id=10)
    assert r["ok"] is False and r["code"] == "SWITCH_FAILED"
    assert ctrl.current_source == SOURCE_SINGLE


async def test_close_open_epoch_noop_without_epochs(monkeypatch):
    ctrl, events, switches = make_ctrl(monkeypatch, live=None)
    assert ctrl.epochs_count == 0
    # без эпох — никаких обращений к БД, тихий no-op
    await ctrl.close_open_epoch_on_finalize()
    assert ctrl.current_source == SOURCE_SINGLE


async def test_live_authoritative_text_none_when_single(monkeypatch):
    ctrl, events, switches = make_ctrl(monkeypatch, live=FakeLive())
    assert ctrl.live_authoritative_text(recent=True) is None


async def test_live_authoritative_text_multi(monkeypatch):
    enable_cutover(monkeypatch)

    class FakeFinal:
        def __init__(self, sid, text, side, start, end):
            self.segment_id = sid
            self.transcript = text
            self.side = side
            self.channel_label = "Канал"
            self.start_server_ms = start
            self.end_server_ms = end

    class FakeSession:
        committed_segments = []

        def _resolve_segment(self, seg):
            return ("X", "self")

    finals = [FakeFinal("m1", "привет канал", "opponent", 999000, 1_000_000)]
    live = FakeLive(n_finals=0, finals=finals)
    ctrl, events, switches = make_ctrl(monkeypatch, live=live, session=FakeSession())
    ctrl.current_source = SOURCE_MULTI
    ctrl._epoch_views = [EpochView(0, "single", 0, 500000),
                         EpochView(1, "multi_channel", 500000, None)]
    text = ctrl.live_authoritative_text(recent=True)
    assert text is not None and "привет канал" in text
