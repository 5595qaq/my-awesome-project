import subprocess


def convert_to_1fps(input_path: str, output_path: str) -> None:
    """Downsamples a video to 1fps (H.265), matching the convention already
    used for the existing videos in the bucket (`*_1fps.mp4`). Videos are
    always converted before upload so Vertex AI receives the same lightweight
    format regardless of what a tester's raw source video looks like.
    """
    command = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter:v", "fps=1",
        "-c:v", "libx265",
        "-crf", "28",
        output_path,
    ]
    subprocess.run(command, check=True)
