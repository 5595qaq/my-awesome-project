from unittest.mock import patch

from app.services import video_service


def test_convert_to_1fps_invokes_ffmpeg_with_expected_args():
    with patch("app.services.video_service.subprocess.run") as mock_run:
        video_service.convert_to_1fps("in.mp4", "out.mp4")

    mock_run.assert_called_once()
    command = mock_run.call_args[0][0]
    assert command[0] == "ffmpeg"
    assert "in.mp4" in command
    assert "out.mp4" in command
    assert "fps=1" in command
    assert "libx265" in command
