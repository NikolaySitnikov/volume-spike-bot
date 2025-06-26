import requests
from flask import Flask, render_template, jsonify
import threading
import time
from datetime import datetime
from collections import deque
from dateutil.parser import parse  # To parse ISO 8601 timestamps
import os
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Define channel IDs and URLs
CHANNEL_1_ID = "689840724094484552"  # Original channel
CHANNEL_2_ID = "689840762786939112"  # New channel
CHANNEL_URL_TEMPLATE = "https://discord.com/api/v9/channels/{channel_id}/messages?limit=50"

# Headers for API requests
HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9,ru;q=0.8,es;q=0.7",
    "authorization": DISCORD_TOKEN,
    "cookie": "__dcfduid=619d2160f0b111ef9b3d21e74ef23cff; __sdcfduid=619d2161f0b111ef9b3d21e74ef23cffe215c4cc65d66e0dcb7f02ec0c8001b93bd72c8d9229d1d35c7d6a89d948b97f; locale=en-US; _gcl_au=1.1.32599864.1740183013; _ga=GA1.1.1715759669.1740183013; __cfruid=8e49c5a45f7ded256f70625e273815f045f355aa-1740361346; _cfuvid=qqwUqY6K5bGaO0A5LAQ7mPEg.UMeojUrEK6HW2EEYlk-1740361346273-0.0.1.1-604800000; OptanonConsent=isIABGlobal=false&datestamp=Sun+Feb+23+2025+20%3A42%3A38+GMT-0500+(Eastern+Standard+Time)&version=6.33.0&hosts=&landingPath=https%3A%2F%2Fdiscord.com%2F&groups=C0001%3A1%2CC0002%3A1%2CC0003%3A1; _ga_Q149DFWHT7=GS1.1.1740361358.2.0.1740361362.0.0.0; cf_clearance=9R3SD4I4Bv9pMF2QfTKPgGzqL1AMWgeLW_1LVQQiK7I-1740511321-1.2.1.1-s0NJqteKPEr_wPT03Q7.6oEipwz.vUag9cksfQvhuctAl.6lwpLX9lI5Adr62Kdj_45mwbIJjARNoh_12qdiQGxP2fge_yYhQ6qkMRne2WX2KPLwtWjEZwYXp4.qUP8Q0kfRuWhQibnJ0C4yLfdyr0_Gb7VAExQTk3qZEFMsivqHxrW1IFkvPZR3C9UfAS39TlwXBhZ6qzAm9wXgh.EfBcfXx68Y5NEx5kVfPAOCJJT823VKk6tjrp.ByTKzvMQ.uMxp4qD1y7RVvoOSatEpPf7DADPI5nL4tgm59hF2CgQ",
    "priority": "u=1, i",
    "referer": "https://discord.com/channels/689839056598990895/689840762786939112",
    "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "x-debug-options": "bugReporterEnabled",
    "x-discord-locale": "en-US",
    "x-discord-timezone": "America/Cancun",
    "x-super-properties": "eyJvcyI6Ik1hYyBPUyBYIiwiYnJvd3NlciI6IkNocm9tZSIsImRldmljZSI6IiIsInN5c3RlbV9sb2NhbGUiOiJlbi1VUyIsImJyb3dzZXJfdXNlcl9hZ2VudCI6Ik1vemlsbGEvNS4wIChNYWNpbnRvc2g7IEludGVsIE1hYyBPUyBYIDEwXzE1XzcpIEFwcGxlV2ViS2l0LzUzNy4zNiAoS0hUTUwsIGxpa2UgR2Vja28pIENocm9tZS8xMzMuMC4wLjAgU2FmYXJpLzUzNy4zNiIsImJyb3dzZXJfdmVyc2lvbiI6IjEzMy4wLjAuMCIsIm9zX3ZlcnNpb24iOiIxMC4xNS43IiwicmVmZXJyZXIiOiJodHRwczovL2Rpc2NvcmQuY29tL2NoYW5uZWxzL0BtZS84NjM0NzU3NzI2MDEyNzAyOTIiLCJyZWZlcnJpbmdfZG9tYWluIjoiZGlzY29yZC5jb20iLCJyZWZlcnJlcl9jdXJyZW50IjoiIiwicmVmZXJyaW5nX2RvbWFpbl9jdXJyZW50IjoiIiwicmVsZWFzZV9jaGFubmVsIjoic3RhYmxlIiwiY2xpZW50X2J1aWxkX251bWJlciI6MzcxNzA2LCJjbGllbnRfZXZlbnRfc291cmNlIjpudWxsLCJoYXNfY2xpZW50X21vZHMiOmZhbHNlfQ=="
}

ALLOWED_USERS = [
    "lsdinmycoffee",
    "pierre_crypt0",
    "coldbloodedshiller",
    "cryptoub",
    "loma"  # Added from second channel response
]

app = Flask(__name__)
MAX_MESSAGES = 100
messages = deque(maxlen=MAX_MESSAGES)
messages_lock = threading.Lock()  # Thread-safe access to messages

# Fetch channel names using Discord API


def get_channel_name(channel_id):
    try:
        url = f"https://discord.com/api/v9/channels/{channel_id}"
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        channel_data = response.json()
        return channel_data.get('name', f"Channel {channel_id}")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching channel name for ID {channel_id}: {e}")
        return f"Channel {channel_id}"


# Get channel names at startup
CHANNEL_1_NAME = get_channel_name(CHANNEL_1_ID)
CHANNEL_2_NAME = get_channel_name(CHANNEL_2_ID)
print(f"Channel 1 Name: {CHANNEL_1_NAME}")
print(f"Channel 2 Name: {CHANNEL_2_NAME}")


def parse_timestamp(timestamp_str):
    """Parse ISO 8601 timestamp string into a datetime object."""
    return parse(timestamp_str)


def fetch_messages(channel_id, channel_name):
    channel_url = CHANNEL_URL_TEMPLATE.format(channel_id=channel_id)
    last_message_id = None
    while True:
        try:
            url = channel_url if not last_message_id else f"{channel_url}&after={last_message_id}"
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            new_messages = response.json()
            if new_messages:
                # Collect all new messages and sort by timestamp
                valid_messages = []
                for msg in reversed(new_messages):
                    username = msg.get('author', {}).get('username', 'Unknown')
                    if username in ALLOWED_USERS:
                        attachments = [
                            {"url": att.get("url", ""), "filename": att.get(
                                "filename", ""), "content_type": att.get("content_type", "")}
                            for att in msg.get("attachments", [])
                        ]
                        message_data = {
                            "id": msg.get('id'),
                            "username": username,
                            "display_name": msg.get('author', {}).get('global_name', 'Unknown'),
                            "content": msg.get('content', ''),
                            "timestamp": msg.get('timestamp', ''),
                            "attachments": attachments,
                            "channel": channel_name
                        }
                        valid_messages.append(message_data)

                # Sort messages by timestamp (oldest to newest)
                valid_messages.sort(
                    key=lambda x: parse_timestamp(x['timestamp']))

                with messages_lock:  # Ensure thread-safe updates
                    for msg in valid_messages:
                        if not any(m['id'] == msg['id'] for m in messages):
                            messages.append(msg)

                last_message_id = new_messages[0]['id']
        except requests.exceptions.RequestException as e:
            print(
                f"Error fetching messages from {channel_name} at {datetime.now()}: {e}")
        time.sleep(5)


# Start threads for both channels
thread1 = threading.Thread(target=fetch_messages, args=(
    CHANNEL_1_ID, CHANNEL_1_NAME), daemon=True)
thread2 = threading.Thread(target=fetch_messages, args=(
    CHANNEL_2_ID, CHANNEL_2_NAME), daemon=True)
thread1.start()
thread2.start()


@app.route('/')
def index():
    print("Serving index.html")
    return render_template('index.html')


@app.route('/messages')
def get_messages():
    with messages_lock:  # Ensure thread-safe read
        return jsonify(list(messages))


if __name__ == "__main__":
    print("Starting Discord message dashboard...")
    print("Open http://127.0.0.1:5001 in your browser")
    app.run(debug=True, use_reloader=False, port=5001)

    # app.run(debug=True, use_reloader=False)
