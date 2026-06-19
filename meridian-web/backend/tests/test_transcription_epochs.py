"""Pure-помощники эпох транскрипции (Этап 9.8)."""

from types import SimpleNamespace

from app.services.transcription_epochs import (
    current_source_from_epochs, open_epoch, epoch_records_to_views,
)


def E(i, source, start, end, id_=None):
    return SimpleNamespace(epoch_index=i, source=source, start_server_ms=start,
                           end_server_ms=end, id=id_ if id_ is not None else i)


def test_current_source_empty_is_single():
    assert current_source_from_epochs([]) == "single"


def test_current_source_is_last_by_index():
    eps = [E(1, "multi_channel", 100, None), E(0, "single", 0, 100)]
    assert current_source_from_epochs(eps) == "multi_channel"


def test_current_source_single_after_fallback():
    eps = [E(0, "single", 0, 100), E(1, "multi_channel", 100, 200), E(2, "single", 200, None)]
    assert current_source_from_epochs(eps) == "single"


def test_open_epoch_picks_highest_index_open():
    eps = [E(0, "single", 0, 100), E(1, "multi_channel", 100, None)]
    assert open_epoch(eps).epoch_index == 1


def test_open_epoch_none_when_all_closed():
    assert open_epoch([E(0, "single", 0, 100)]) is None


def test_epoch_records_to_views():
    vs = epoch_records_to_views([E(0, "single", 0, 100), E(1, "multi_channel", 100, None)])
    assert vs[0].source == "single" and vs[0].end_server_ms == 100
    assert vs[1].source == "multi_channel" and vs[1].end_server_ms is None
