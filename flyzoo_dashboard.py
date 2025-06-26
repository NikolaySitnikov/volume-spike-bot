import requests
from flask import Flask, render_template, jsonify
import threading
import time
from datetime import datetime, timedelta
import pytz
from collections import deque
from dateutil.parser import parse as dateutil_parse
import socket

# Flask app setup
app = Flask(__name__)
MAX_MESSAGES = 1000  # Increased for better capacity
messages = deque(maxlen=MAX_MESSAGES)
messages_lock = threading.Lock()
sent_to_telegram = set()  # Track messages sent to Telegram
initial_fetch_complete = False  # Flag to track initial fetch completion
initial_message_ids = set()  # Track IDs from initial fetch

# Flyzoo API configuration
CHATROOM_ID = "5c0b1ec74fb4d50db40b12f8"
WEBSITE_ID = "5c0b1ec44fb4d50db40b12f3"
API_URL = f"https://widget-b.flyzoo.co/chatrooms/getchatroomhistory?id={CHATROOM_ID}&start=&q=25&wid={WEBSITE_ID}"
HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-CA,en;q=0.6",
    "Connection": "keep-alive",
    "Referer": "https://widget-b.flyzoo.co/chatrooms/chatroom?xto=https%3A%2F%2Fsmartertrading411.com%2Fchat%2F&url=https%3A%2F%2Fsmartertrading411.com%2Fchat%2F&idWebsite=5c0b1ec44fb4d50db40b12f3&mode=embed&id=5c0b1ec74fb4d50db40b12f8&mobile=false&rt=false&gcn=null&fzla=en&rnd=178877",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Storage-Access": "none",
    "Sec-GPC": "1",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": '"Not(A:Brand";v="99", "Brave";v="133", "Chromium";v="133"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"'
}

# Telegram configuration with new bot and channel
TELEGRAM_BOT_TOKEN = "7673376661:AAHs54ap5sz8-oupzbPdeQlHnBOpIrLrLSE"
TELEGRAM_CHANNEL_ID = "-1002386976913"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
TELEGRAM_ENABLED = 1  # 0 to disable, 1 to enable Telegram functionality

# Allowed users for Flyzoo
ALLOWED_USERS = {
    "smartertrader": {"id": "5c0b1e88bb547e30b83d8554", "requires_flag": True},  # Requires 🚩 emoji
    "GeoTrader": {"id": "5c0fd49abb547e3368afa5d4", "requires_flag": False}  # All messages
}

# Parse timestamp with timezone awareness
def parse_timestamp(timestamp_str):
    """Parse ISO 8601 timestamp string into an offset-aware datetime object."""
    dt = dateutil_parse(timestamp_str)
    if dt.tzinfo is None:
        # If no timezone, assume UTC (common for Flyzoo)
        dt = dt.replace(tzinfo=pytz.UTC)
    return dt

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
            print(f"Telegram rate limited. Retrying after {retry_after} seconds...")
            time.sleep(retry_after)
            send_to_telegram(message)  # Retry once
        else:
            print(f"Error sending to Telegram: {e}")
    time.sleep(1)  # Slow sending to 1 message per second

# Fetch messages from Flyzoo API with 24-hour and user-specific flag filter
def fetch_messages():
    global initial_fetch_complete, initial_message_ids
    last_timestamp = None  # Track the oldest timestamp to paginate
    local_tz = datetime.now(pytz.utc).astimezone().tzinfo  # Get local timezone
    twenty_four_hours_ago = datetime.now(local_tz) - timedelta(hours=24)  # 24 hours ago in local time
    initial_fetch_done = False  # Track initial fetch completion

    while True:
        try:
            params = {
                "id": CHATROOM_ID,
                "start": last_timestamp.strftime('%Y-%m-%dT%H:%M:%S.000Z') if last_timestamp else "",
                "q": 25,
                "wid": WEBSITE_ID
            }
            print(f"Fetching messages from Flyzoo with URL: {API_URL} and params: {params}")
            response = requests.get(API_URL, headers=HEADERS, params=params)
            response.raise_for_status()
            data = response.json()
            messages_data = data.get("StartMessages", [])
            if not isinstance(messages_data, list):
                # Handle stringified JSON if needed
                messages_data = eval(messages_data)
            print(f"Fetched {len(messages_data)} messages from Flyzoo")

            if messages_data:
                valid_messages = []
                for msg in reversed(messages_data):
                    username = msg.get('UserName', 'Unknown')
                    msg_timestamp = parse_timestamp(msg.get('Date', ''))
                    local_msg_time = msg_timestamp.astimezone(local_tz)
                    print(f"Processing message from Flyzoo by {username} at {local_msg_time}")

                    # Filter: Include messages from allowed users within the last 24 hours
                    content = msg.get('Text', '')
                    if username in ALLOWED_USERS and local_msg_time >= twenty_four_hours_ago:
                        user_config = ALLOWED_USERS[username]
                        # Apply flag filter for smartertrader, but not for GeoTrader
                        if user_config["requires_flag"] and "🚩" not in content:
                            print(f"Discarded message from Flyzoo by {username}: No 🚩 emoji")
                            continue
                        message_data = {
                            "id": msg.get('Id'),
                            "username": username,
                            # Use UserName as display_name
                            "display_name": msg.get('UserName', 'Unknown'),
                            "content": content,
                            "timestamp": msg.get('Date', ''),
                            "attachments": [],  # No attachments in response, but we’ll handle links
                            "channel": "flyzoo-chat"  # Single "channel" name for consistency
                        }
                        valid_messages.append(message_data)
                        print(f"Valid message from Flyzoo: {username} - {message_data['content'][:20]}... at {local_msg_time}")
                    else:
                        print(f"Discarded message from Flyzoo by {username}: Not an allowed user or outside 24h")

                with messages_lock:
                    for msg in valid_messages:
                        if not any(m['id'] == msg['id'] for m in messages):
                            messages.append(msg)
                            if not initial_fetch_done:  # Initial fetch
                                initial_message_ids.add(msg['id'])
                            print(f"Added to deque from Flyzoo: {msg['username']} - {msg['content'][:20]}... at {msg['timestamp']}")

                # Update last_timestamp for pagination (use the oldest message’s timestamp)
                last_timestamp = parse_timestamp(messages_data[-1]['Date']) if messages_data else None
                # Set initial fetch complete after first successful fetch
                if not initial_fetch_done and messages_data:
                    initial_fetch_done = True
                    if not initial_fetch_complete:
                        initial_fetch_complete = True
                        print("Initial fetch complete from Flyzoo; Telegram sending enabled for new messages.")
            else:
                print(f"No new messages from Flyzoo")
                # Set initial fetch complete if no messages are fetched initially
                if not initial_fetch_done and not initial_fetch_complete:
                    initial_fetch_complete = True
                    print("Initial fetch complete (no messages from Flyzoo); Telegram sending enabled for new messages.")
        except requests.exceptions.RequestException as e:
            print(f"Error fetching messages from Flyzoo: {e}")
        except (ValueError, SyntaxError) as e:
            print(f"Error parsing Flyzoo response: {e}")
        time.sleep(5)  # Poll every 5 seconds

# Centralized Telegram sender with 24-hour and user-specific flag filter
def telegram_sender():
    if TELEGRAM_ENABLED == 0:
        print("Telegram sender thread disabled.")
        while True:
            time.sleep(3600)  # Sleep for an hour if disabled to reduce resource usage
        return
    while True:
        with messages_lock:
            local_tz = datetime.now(pytz.utc).astimezone().tzinfo
            twenty_four_hours_ago = datetime.now(local_tz) - timedelta(hours=24)
            sorted_messages = sorted(list(messages), key=lambda x: parse_timestamp(x['timestamp']))
            new_messages = []
            for msg in sorted_messages:
                msg_timestamp = parse_timestamp(msg['timestamp'])
                local_msg_time = msg_timestamp.astimezone(local_tz)
                user_config = ALLOWED_USERS.get(msg['username'], {})
                # Only send new messages after initial fetch, within 24 hours, not from initial batch, and apply flag filter for smartertrader
                if (msg['id'] not in sent_to_telegram and
                    initial_fetch_complete and
                    local_msg_time >= twenty_four_hours_ago and
                    msg['id'] not in initial_message_ids and
                    (not user_config.get("requires_flag", False) or "🚩" in msg['content'])):
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
        sorted_messages = sorted(messages_copy, key=lambda x: parse_timestamp(x['timestamp']))
        local_tz = datetime.now().astimezone().tzinfo
        for msg in sorted_messages:
            utc_time = parse_timestamp(msg['timestamp'])
            msg['timestamp'] = utc_time.astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')
        print(f"Serving {len(sorted_messages)} messages to dashboard")
        return jsonify(sorted_messages)

# Start message fetching and Telegram sender threads
fetch_thread = threading.Thread(target=fetch_messages, daemon=True)
telegram_thread = threading.Thread(target=telegram_sender, daemon=True)

fetch_thread.start()
telegram_thread.start()

if __name__ == "__main__":
    port = 5003
    print(f"Starting Flask server on http://127.0.0.1:{port}")
    # Check if port is available
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(('127.0.0.1', port)) == 0:
            print(f"Port {port} is already in use. Please free it or use a different port.")
            exit(1)
    app.run(debug=True, use_reloader=False, port=5003)