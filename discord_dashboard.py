import requests
from flask import Flask, render_template, jsonify
import threading
import time
from datetime import datetime, timedelta
import pytz
from collections import deque
from dateutil.parser import parse as dateutil_parse
import socket
import os
HEADERS = os.getenv("HEADERS")

# Flask app setup
app = Flask(__name__)
MAX_MESSAGES = 1000  # Increased for better capacity
messages = deque(maxlen=MAX_MESSAGES)
messages_lock = threading.Lock()
sent_to_telegram = set()  # Track messages sent to Telegram
initial_fetch_complete = False  # Flag to track initial fetch completion
initial_message_ids = set()  # Track IDs from initial fetch

# Discord API configuration for the new server
CHANNELS = [
    {"id": "1301557760109842463", "name": "swing-trades"},
    {"id": "1266047163297828904", "name": "all-trades"}
]
CHANNEL_URL_TEMPLATE = "https://discord.com/api/v9/channels/{channel_id}/messages?limit=50"

# Telegram configuration with new bot and channel
TELEGRAM_BOT_TOKEN = "7673376661:AAHs54ap5sz8-oupzbPdeQlHnBOpIrLrLSE"
TELEGRAM_CHANNEL_ID = "-1002386976913"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
TELEGRAM_ENABLED = 1  # 0 to disable, 1 to enable Telegram functionality

# Allowed users for the new server
ALLOWED_USERS = [".HERE-BOT GG#0217",
                 "stocksareeazy", "yashnogja", "gg_caesar"]

# Fetch channel name from Discord API


def get_channel_name(channel_id):
    try:
        url = f"https://discord.com/api/v9/channels/{channel_id}"
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json().get('name', f"Channel {channel_id}")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching channel name for ID {channel_id}: {e}")
        return f"Channel {channel_id}"


# Initialize channel names
for channel in CHANNELS:
    channel["name"] = get_channel_name(channel["id"])
print("Initialized Channels:", {ch["id"]: ch["name"] for ch in CHANNELS})

# Parse timestamp with timezone awareness


def parse_timestamp(timestamp_str):
    """Parse ISO 8601 timestamp string into an offset-aware datetime object."""
    dt = dateutil_parse(timestamp_str)
    if dt.tzinfo is None:
        # If no timezone, assume UTC (common for Discord)
        dt = dt.replace(tzinfo=pytz.UTC)
    return dt

# Clean bot message content


def clean_bot_message(content):
    """Remove the :golf: **username**: prefix and | @ (HH:MM:SS) suffix from HERE-BOT GG messages."""
    if content.startswith(":golf: **"):
        # Remove prefix
        prefix_end = content.find("**: ") + 4
        cleaned = content[prefix_end:]
        # Remove suffix
        suffix_start = cleaned.rfind(" | @ (")
        if suffix_start != -1:
            cleaned = cleaned[:suffix_start].strip()
        return cleaned
    return content

# Send message to Telegram with rate limit handling and toggle


def send_to_telegram(message):
    if TELEGRAM_ENABLED == 0:
        print("Telegram functionality is disabled.")
        return
    local_tz = datetime.now().astimezone().tzinfo
    utc_time = parse_timestamp(message['timestamp'])
    local_time = utc_time.astimezone(local_tz)
    formatted_timestamp = local_time.strftime('%Y-%m-%d %H:%M:%S')
    telegram_message = (
        f"{message['username']} ({message['display_name']}) [{message['channel']}] {formatted_timestamp}\n"
        f"{message['content']}"
    )
    try:
        response = requests.post(
            TELEGRAM_API_URL,
            json={"chat_id": TELEGRAM_CHANNEL_ID, "text": telegram_message},
            timeout=10
        )
        response.raise_for_status()
        print(f"Sent to Telegram: {telegram_message[:50]}...")
    except requests.exceptions.RequestException as e:
        if response and response.status_code == 429:
            retry_after = response.json().get('parameters', {}).get('retry_after', 5)
            print(
                f"Telegram rate limited. Retrying after {retry_after} seconds...")
            time.sleep(retry_after)
            send_to_telegram(message)  # Retry once
        else:
            print(f"Error sending to Telegram: {e}")
    time.sleep(1)  # Slow sending to 1 message per second

# Fetch messages from all channels in a single thread with 24-hour filter


def fetch_all_channels():
    global initial_fetch_complete, initial_message_ids
    # Track last message ID per channel
    last_message_ids = {channel["id"]: None for channel in CHANNELS}
    local_tz = datetime.now(pytz.utc).astimezone().tzinfo  # Get local timezone
    twenty_four_hours_ago = datetime.now(
        local_tz) - timedelta(hours=24)  # 24 hours ago in local time
    initial_channels_processed = 0  # Counter for initial fetch completion

    while True:
        for channel in CHANNELS:
            channel_id = channel["id"]
            channel_name = channel["name"]
            try:
                url = CHANNEL_URL_TEMPLATE.format(channel_id=channel_id) if last_message_ids[channel_id] is None else \
                    f"{CHANNEL_URL_TEMPLATE.format(channel_id=channel_id)}&after={last_message_ids[channel_id]}"
                print(f"Fetching messages from {channel_name} with URL: {url}")
                response = requests.get(url, headers=HEADERS)
                response.raise_for_status()
                new_messages = response.json()
                print(
                    f"Fetched {len(new_messages)} messages from {channel_name}")

                if new_messages:
                    valid_messages = []
                    for msg in reversed(new_messages):
                        username = msg.get('author', {}).get(
                            'username', 'Unknown')
                        msg_timestamp = parse_timestamp(
                            msg.get('timestamp', ''))
                        local_msg_time = msg_timestamp.astimezone(local_tz)
                        print(
                            f"Processing message from {channel_name} by {username} at {local_msg_time}")

                        # Handle HERE-BOT GG messages
                        if username == "HERE-BOT GG" and msg.get('content', '').startswith(":golf: **"):
                            username_start = msg['content'].find("**") + 2
                            username_end = msg['content'].find(
                                "**", username_start)
                            username = msg['content'][username_start:username_end]
                            content = clean_bot_message(msg['content'])
                        else:
                            content = msg.get('content', '')

                        # Filter: Only include messages from ALLOWED_USERS within the last 24 hours
                        if username in ALLOWED_USERS and local_msg_time >= twenty_four_hours_ago:
                            attachments = [
                                {"url": att.get("url", ""), "filename": att.get(
                                    "filename", ""), "content_type": att.get("content_type", "")}
                                for att in msg.get("attachments", [])
                            ]
                            message_data = {
                                "id": msg.get('id'),
                                "username": username,
                                "display_name": msg.get('author', {}).get('global_name', 'Unknown' if username != "HERE-BOT GG" else 'Bot'),
                                "content": content,
                                "timestamp": msg.get('timestamp', ''),
                                "attachments": attachments,
                                "channel": channel_name
                            }
                            valid_messages.append(message_data)
                            print(
                                f"Valid message from {channel_name}: {username} - {message_data['content'][:20]}... at {local_msg_time}")
                        else:
                            print(
                                f"Discarded message from {channel_name} by {username}: Outside 24h or not allowed")

                    with messages_lock:
                        for msg in valid_messages:
                            if not any(m['id'] == msg['id'] for m in messages):
                                messages.append(msg)
                                if last_message_ids[channel_id] is None:  # Initial fetch
                                    initial_message_ids.add(msg['id'])
                                print(
                                    f"Added to deque from {channel_name}: {msg['username']} - {msg['content'][:20]}... at {msg['timestamp']}")

                    last_message_ids[channel_id] = new_messages[0]['id']
                    # Track initial fetch completion
                    if last_message_ids[channel_id] is not None:
                        initial_channels_processed += 1
                        if initial_channels_processed >= len(CHANNELS) and not initial_fetch_complete:
                            initial_fetch_complete = True
                            print(
                                "Initial fetch complete across all channels; Telegram sending enabled for new messages.")
                else:
                    print(f"No new messages from {channel_name}")
                    # Handle case where a channel has no messages initially
                    if last_message_ids[channel_id] is None:
                        initial_channels_processed += 1
                        if initial_channels_processed >= len(CHANNELS) and not initial_fetch_complete:
                            initial_fetch_complete = True
                            print(
                                "Initial fetch complete (no messages in some channels); Telegram sending enabled for new messages.")
            except requests.exceptions.RequestException as e:
                print(f"Error fetching messages from {channel_name}: {e}")
        time.sleep(5)  # Poll every 5 seconds for all channels

# Centralized Telegram sender with 24-hour filter and initial skip


def telegram_sender():
    if TELEGRAM_ENABLED == 0:
        print("Telegram sender thread disabled.")
        while True:
            # Sleep for an hour if disabled to reduce resource usage
            time.sleep(3600)
        return
    while True:
        with messages_lock:
            local_tz = datetime.now(pytz.utc).astimezone().tzinfo
            twenty_four_hours_ago = datetime.now(
                local_tz) - timedelta(hours=24)
            sorted_messages = sorted(
                list(messages), key=lambda x: parse_timestamp(x['timestamp']))
            new_messages = []
            for msg in sorted_messages:
                msg_timestamp = parse_timestamp(msg['timestamp'])
                local_msg_time = msg_timestamp.astimezone(local_tz)
                # Only send new messages after initial fetch, within 24 hours, and not from initial batch
                if msg['id'] not in sent_to_telegram and initial_fetch_complete and local_msg_time >= twenty_four_hours_ago and msg['id'] not in initial_message_ids:
                    new_messages.append(msg)
            for msg in new_messages:
                send_to_telegram(msg)
                sent_to_telegram.add(msg['id'])
        time.sleep(5)  # Check and send every 5 seconds

# Flask routes


@app.route('/')
def index():
    print("Serving index.html")
    return render_template('index.html')


@app.route('/messages')
def get_messages():
    with messages_lock:
        # Create a copy of the messages list to avoid modifying the original deque
        messages_copy = [msg.copy() for msg in messages]
        # Sort the copied messages by timestamp
        sorted_messages = sorted(
            messages_copy, key=lambda x: parse_timestamp(x['timestamp']))
        local_tz = datetime.now().astimezone().tzinfo
        for msg in sorted_messages:
            utc_time = parse_timestamp(msg['timestamp'])
            msg['timestamp'] = utc_time.astimezone(
                local_tz).strftime('%Y-%m-%d %H:%M:%S')
        print(f"Serving {len(sorted_messages)} messages to dashboard")
        return jsonify(sorted_messages)


# Start message fetching and Telegram sender threads
fetch_thread = threading.Thread(target=fetch_all_channels, daemon=True)
telegram_thread = threading.Thread(target=telegram_sender, daemon=True)

fetch_thread.start()
telegram_thread.start()

if __name__ == "__main__":
    port = 5002
    print(f"Starting Flask server on http://127.0.0.1:{port}")
    # Check if port is available
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(('127.0.0.1', port)) == 0:
            print(
                f"Port {port} is already in use. Please free it or use a different port.")
            exit(1)
    app.run(debug=True, use_reloader=False, port=5002)
