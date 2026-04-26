import argparse
import random
import shutil
import subprocess
import tempfile
from pathlib import Path


FONT = "C\\:/Users/Joka/AppData/Local/Microsoft/Windows/Fonts/8bitOperatorPlus8-Bold.ttf"

CROP = {
    "width": 768,
    "height": 432,
    "x": 425,
    "y": 160,
}

OUTPUT_SIZE = (1280, 720)


def run(cmd):
    subprocess.run(cmd, check=True)


def get_video_duration(video_path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return float(result.stdout.strip())


def escape_drawtext_text(text):
    return (
        text
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
    )


def drawtext(
    text,
    x,
    y,
    fontsize,
    fontcolor="white",
    borderw=4,
    bordercolor="black",
    shadowcolor="black",
    shadowx=3,
    shadowy=3,
    fontfile=FONT,
):
    text = escape_drawtext_text(text)

    return (
        "drawtext="
        f"fontfile='{fontfile}':"
        f"text='{text}':"
        f"x={x}:"
        f"y={y}:"
        f"fontsize={fontsize}:"
        f"fontcolor={fontcolor}:"
        f"borderw={borderw}:"
        f"bordercolor={bordercolor}:"
        f"shadowcolor={shadowcolor}:"
        f"shadowx={shadowx}:"
        f"shadowy={shadowy}"
    )


def wrap_words(text, max_chars=16):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        next_line = f"{current} {word}".strip()

        if len(next_line) <= max_chars:
            current = next_line
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def pop_text(text, x, y, fontsize, main_color="white", accent_color="yellow"):
    """
    Layered text:
    - fuzzy shadow
    - colored accent outline
    - black stroke
    - main text
    """
    return [
        drawtext(
            text,
            x=x,
            y=y,
            fontsize=fontsize,
            fontcolor="black@0.25",
            borderw=0,
            shadowx=12,
            shadowy=12,
        ),
        drawtext(
            text,
            x=x,
            y=y,
            fontsize=fontsize,
            fontcolor=accent_color,
            borderw=8,
            bordercolor=accent_color,
            shadowx=0,
            shadowy=0,
        ),
        drawtext(
            text,
            x=x,
            y=y,
            fontsize=fontsize,
            fontcolor=main_color,
            borderw=5,
            bordercolor="black",
            shadowx=3,
            shadowy=3,
        ),
    ]


def fancy_text(text, x, y, fontsize, main_color="white"):
    return [
        drawtext(text, x, y, fontsize, fontcolor="black@0.2", borderw=0, shadowx=10, shadowy=10),
        drawtext(text, x, y, fontsize, fontcolor="black@0.4", borderw=0, shadowx=5, shadowy=5),
        drawtext(text, x, y, fontsize, fontcolor="black@0.7", borderw=0, shadowx=2, shadowy=2),
        drawtext(text, x, y, fontsize, fontcolor=main_color, borderw=5, bordercolor="black"),
    ]


def build_vf(game_name, run_time, accent_color):
    output_w, output_h = OUTPUT_SIZE
    text_filters = []

    title_lines = wrap_words(game_name, max_chars=16)

    title_y = 70
    title_fontsize = 100
    title_line_spacing = 95

    for i, line in enumerate(title_lines):
        text_filters += pop_text(
            line,
            x="70",
            y=str(title_y + i * title_line_spacing),
            fontsize=title_fontsize,
            main_color="white",
            accent_color=accent_color,
        )

    subtitle_y = title_y + len(title_lines) * title_line_spacing + 5

    text_filters += fancy_text(
        "Speedrun",
        x="80",
        y=str(subtitle_y),
        fontsize=70,
        main_color="white",
    )
    text_filters += fancy_text(
        run_time,
        x="w-text_w-70",
        y="h-text_h-70",
        fontsize=200,
        main_color="lightgreen",
    )

    filters = [
        f"crop={CROP['width']}:{CROP['height']}:{CROP['x']}:{CROP['y']}",
        f"scale={output_w}:{output_h}",
        "gblur=sigma=2",
        "eq=gamma=0.6:contrast=0.9",
        *text_filters,
    ]

    return ",".join(filters)


def extract_random_frames(video_path, temp_dir, count):
    duration = get_video_duration(video_path)
    frame_paths = []

    for i in range(count):
        timestamp = random.uniform(0, duration)
        output_path = temp_dir / f"frame_{i}.png"

        run([
            "ffmpeg",
            "-y",
            "-ss", str(timestamp),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_path),
        ])

        frame_paths.append(output_path)

    return frame_paths


def make_thumbnails(video_path, game_name, run_time, output_dir, count, accent_color):
    output_dir.mkdir(parents=True, exist_ok=True)
    vf = build_vf(game_name, run_time, accent_color)

    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)

        frames = extract_random_frames(video_path, temp_dir, count)

        for index, frame_path in enumerate(frames, start=1):
            safe_game = game_name.lower().replace(" ", "_")
            safe_time = run_time.replace(":", "_")
            output_path = output_dir / f"{safe_game}_{safe_time}_{index}.png"

            run([
                "ffmpeg",
                "-y",
                "-i", str(frame_path),
                "-vf", vf,
                str(output_path),
            ])

            print(f"Saved {output_path}")

    # tempfile automatically deletes the temporary frame images here


def parse_args():
    parser = argparse.ArgumentParser(description="Generate speedrun thumbnails from an MKV video.")

    parser.add_argument("video", help="Path to the input .mkv video")
    parser.add_argument("game", help="Game name, e.g. Contra")
    parser.add_argument("time", help="Run time, e.g. 10:28")
    parser.add_argument("accent", nargs="?", default="yellow", help="Accent color (default: yellow)")

    parser.add_argument("-n", "--count", type=int, default=5, help="Number of thumbnails to generate")
    parser.add_argument("-o", "--output-dir", default="thumbnails", help="Output directory")

    return parser.parse_args()


def main():
    args = parse_args()
    full_path = args.video if ":/" in args.video else f"C:/Users/Joka/Documents/{args.video}"

    make_thumbnails(
        video_path=Path(full_path),
        game_name=args.game,
        run_time=args.time,
        output_dir=Path(args.output_dir),
        count=args.count,
        accent_color=args.accent,
    )


if __name__ == "__main__":
    main()