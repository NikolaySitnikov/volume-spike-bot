"""
Hourly Volume Spike Alert – Binance USDT-Perpetuals
────────────────────────────────────────────────────
• Scans every 5 min on the clock (…:00, :05, :10, …)
• At hh:00 → uses last two *closed* hourly candles
  All other times → compares current open candle vs. previous closed
• Fires when curr ≥ 3× prev and ≥ $3 M notional
• Prints one line per symbol, magenta highlight on spikes
• Sends spikes to Telegram
"""

import time
import datetime
import requests
import sys
import warnings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

warnings.filterwarnings("ignore", category=DeprecationWarning)

API = "https://fapi.binance.com"
INTERVAL = "1h"
VOLUME_MULTIPLE = 3
MIN_QUOTE_VOL = 3_000_000      # ~$3 M

# Telegram
import os
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
CHAT_ID         = os.getenv("CHAT_ID")

# Track last-alerted hour per symbol
last_alert: dict[str, datetime.datetime] = {}

# ─────────────────────── requests session ───────────────────────
session = requests.Session()
session.mount(
    "https://",
    HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1,
                                  status_forcelist=[429, 500, 502, 503, 504]))
)

# ────────────────────────── helpers ────────────────────────────


def fmt(vol: float) -> str:
    if vol >= 1e9:
        return f"{vol/1e9:,.2f}B"
    if vol >= 1e6:
        return f"{vol/1e6:,.2f}M"
    if vol >= 1e3:
        return f"{vol/1e3:,.2f}K"
    return f"{vol:,.0f}"


def tg_send(text: str):
    try:
        r = session.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": text},
            timeout=5,
        )
        if r.status_code != 200:
            print(f"Telegram error {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print("Telegram send exception:", e)


def active_perps() -> list[str]:
    info = session.get(f"{API}/fapi/v1/exchangeInfo", timeout=10).json()
    return [
        s["symbol"] for s in info["symbols"]
        if s["contractType"] == "PERPETUAL"
        and s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
    ]


def last_two_closed_klines(sym: str):
    kl = session.get(f"{API}/fapi/v1/klines",
                     params={"symbol": sym, "interval": INTERVAL, "limit": 3},
                     timeout=10).json()
    now_ms = int(time.time() * 1000)
    closed = [k for k in kl if k[6] < now_ms]
    return closed[-2:] if len(closed) >= 2 else []

# ─────────────────────── core scan function ─────────────────────


def scan(top_of_hour: bool) -> None:
    for sym in active_perps():
        try:
            if top_of_hour:
                prev, curr = last_two_closed_klines(sym)
            else:
                kl = session.get(f"{API}/fapi/v1/klines",
                                 params={"symbol": sym,
                                         "interval": INTERVAL, "limit": 2},
                                 timeout=10).json()
                prev, curr = kl[-2], kl[-1]
        except Exception:
            continue

        prev_vol = float(prev[7])
        curr_vol = float(curr[7])
        ratio = curr_vol / prev_vol if prev_vol else 0

        curr_hour = datetime.datetime.fromtimestamp(
            curr[0] / 1000, datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)

        already = last_alert.get(sym) == curr_hour
        spike = (ratio >= VOLUME_MULTIPLE) and (
            curr_vol >= MIN_QUOTE_VOL) and not already

        if spike:
            last_alert[sym] = curr_hour

        line = (f"{sym:<12}  prev: {fmt(prev_vol):>9}  "
                f"curr: {fmt(curr_vol):>9}  "
                f"({ratio:5.2f}×)")
        if spike:
            print(f"\033[95;1m{line}  ← VOLUME SPIKE!\033[0m")
            tg_send(f"{sym} hourly volume {fmt(curr_vol)} "
                    f"({ratio:.2f}× prev) — VOLUME SPIKE!")
        else:
            note = " (ratio hit, volume < min)" if ratio >= VOLUME_MULTIPLE and curr_vol < MIN_QUOTE_VOL else ""
            print(f"{line}{note}")


# ───────────────────────── main loop ────────────────────────────
print("Hourly-volume alert running…  (Ctrl-C to stop)")
while True:
    utc_now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    top_of_hour = (utc_now.minute == 0)

    print("Starting volume scan…", flush=True)
    try:
        scan(top_of_hour)
    except Exception as e:
        print("⚠️  Error:", e)

    # Sleep until next 5-minute boundary
    utc_now = datetime.datetime.utcnow()
    seconds = utc_now.minute * 60 + utc_now.second
    wait_sec = (300 - (seconds % 300)) or 300
    for r in range(wait_sec, 0, -1):
        sys.stdout.write(f"\r… next check in {r:3d}s ")
        sys.stdout.flush()
        time.sleep(1)
    print()
