from PySide6.QtWidgets import QWidget

from tts_dataset_studio.ui.player import PlayerWidget


def test_video_asset_can_switch_between_video_and_waveform_preview(qtbot) -> None:
    waveform = QWidget()
    player = PlayerWidget(waveform)
    qtbot.addWidget(player)
    player._has_video = True

    player.set_preview_mode("video")
    assert player.currentWidget() is player.qt_video

    player.set_preview_mode("waveform")
    assert player.currentWidget() is waveform


def test_audio_asset_cannot_switch_away_from_waveform_preview(qtbot) -> None:
    waveform = QWidget()
    player = PlayerWidget(waveform)
    qtbot.addWidget(player)
    player._has_video = False

    player.set_preview_mode("video")

    assert player.currentWidget() is waveform


def test_track_monitor_controls_source_and_ai_outputs(qtbot) -> None:
    player = PlayerWidget(QWidget())
    qtbot.addWidget(player)

    player.set_track_monitor(False, True)

    assert player.audio_output.isMuted()
    assert not player.ai_audio_output.isMuted()
