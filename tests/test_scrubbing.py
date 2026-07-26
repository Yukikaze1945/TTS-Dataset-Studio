from tts_dataset_studio.domain.models import MediaAsset, Project
from tts_dataset_studio.ui.main_window import MainWindow


def test_scrubbing_ignores_stale_player_positions(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    asset = MediaAsset("audio.wav", "audio.wav", duration_ms=5000)
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    window.timeline.set_asset(asset)
    scrubbed: list[int] = []
    finished: list[int] = []
    monkeypatch.setattr(window.player_widget, "scrub", scrubbed.append)
    monkeypatch.setattr(window.player_widget, "finish_scrub", finished.append)

    window._scrub(2000)
    window._on_position_changed(400)

    assert window.timeline.playhead_ms == 2000
    assert scrubbed == [2000]

    window._finish_scrub(2300)
    window._on_position_changed(800)

    assert window.timeline.playhead_ms == 2300
    assert finished == [2300]

    window._on_position_changed(2290)

    assert window.timeline.playhead_ms == 2290
    assert window._awaiting_scrub_ms is None
    window.dirty = False
