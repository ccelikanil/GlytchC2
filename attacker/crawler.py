#!/usr/bin/env python3
import subprocess
import sys
import argparse

def get_stream_url(channel_url, quality):
    """
    Uses streamlink to extract the m3u8 URL for a given Twitch channel.
    """
    try:
        # Run the streamlink command and capture its stdout.
        result = subprocess.run(
            ["streamlink", "--stream-url", channel_url, quality],
            capture_output=True,
            text=True,
            check=True
        )
        stream_url = result.stdout.strip()
        if not stream_url:
            raise ValueError("No stream URL found")
        return stream_url
    except subprocess.CalledProcessError as e:
        print("Error running streamlink command:", e, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(1)

def record_stream(stream_url, output_file):
    """
    Uses ffmpeg to capture frames from the provided stream URL and save them as images.
    """
    try:
        # Capture one frame per second and save as images using the given filename pattern.
        ffmpeg_command = ["ffmpeg", "-i", stream_url, "-vf", "fps=1", output_file]
        print("Running ffmpeg command:", " ".join(ffmpeg_command))
        subprocess.run(ffmpeg_command, check=True)
    except subprocess.CalledProcessError as e:
        print("Error running ffmpeg command:", e, file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Extract Twitch stream URL using streamlink and capture frames using ffmpeg."
    )
    parser.add_argument(
        "--channel",
        default="https://twitch.tv/bilocan1337",
        help="Twitch channel URL (default: https://twitch.tv/bilocan1337)"
    )
    parser.add_argument(
        "--quality",
        default="best",
        help="Stream quality to extract (default: best)"
    )
    parser.add_argument(
        "--output",
        default="frame-%04d.png",
        help="Output filename pattern for ffmpeg recording (default: frame-%04d.png)"
    )
    args = parser.parse_args()

    print("Extracting stream URL for channel:", args.channel)
    stream_url = get_stream_url(args.channel, args.quality)
    print("Retrieved stream URL:", stream_url)

    print("Capturing frames to files with pattern:", args.output)
    record_stream(stream_url, args.output)

if __name__ == "__main__":
    main()
