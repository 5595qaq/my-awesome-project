import subprocess


def convert_fps(input_path: str, output_path: str, fps: int) -> None:
    """Downsamples a video to 1fps (H.265), matching the convention already
    used for the existing videos in the bucket (`*_1fps.mp4`). Videos are
    always converted before upload so Vertex AI receives the same lightweight
    format regardless of what a tester's raw source video looks like.
    """
    command = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter:v", f"fps={fps}",
        "-c:v", "libx265",
        "-crf", "28",
        output_path,
    ]
    subprocess.run(command, check=True)


def convert_to_1fps(input_path: str, output_path: str) -> None:
    convert_fps(input_path, output_path, 1)


def convert_to_5fps(input_path: str, output_path: str) -> None:
    convert_fps(input_path, output_path, 5)
