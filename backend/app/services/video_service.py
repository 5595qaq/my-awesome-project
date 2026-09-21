import subprocess


def convert_fps(input_path: str, output_path: str, fps: int) -> None:
    """Normalize an uploaded video to H.265 at the requested frame rate."""
    command = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter:v", f"fps={fps}",
        "-c:v", "libx265",
        "-crf", "28",
        output_path,
    ]
    subprocess.run(command, check=True)

def convert_to_5fps(input_path: str, output_path: str) -> None:
    convert_fps(input_path, output_path, 5)
