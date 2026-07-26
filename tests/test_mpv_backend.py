import json

import pytest

from tts_dataset_studio.ui.mpv_backend import encode_command, gain_db_to_percent


def test_encode_command_uses_json_line_protocol() -> None:
    payload = encode_command(["loadfile", "C:/媒体/episode.wav", "replace"], request_id=7)

    assert payload.endswith(b"\n")
    assert json.loads(payload) == {
        "command": ["loadfile", "C:/媒体/episode.wav", "replace"],
        "request_id": 7,
    }


def test_gain_db_is_converted_to_mpv_volume_percent() -> None:
    assert gain_db_to_percent(6.0) == pytest.approx(199.526, rel=0.001)
    assert gain_db_to_percent(-60.0) == pytest.approx(0.1)
    assert gain_db_to_percent(12.0, bypassed=True) == 100.0
