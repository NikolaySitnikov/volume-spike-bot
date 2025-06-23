"""
Binance USDT-Perpetual Pairs Dashboard
──────────────────────────────────────
• Shows 24 h volume, funding, and price
• Auto-refreshes every 5 minutes
• Generates a TradingView watchlist (.txt) on every hard browser reload
• Ignores delisted / inactive contracts using /exchangeInfo status
• NEW: watchlist lines now end with USDT.P (TradingView futures notation)
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────
import requests
import pandas as pd
import streamlit as st
# pip install streamlit-autorefresh
from streamlit_autorefresh import st_autorefresh
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ──────────────────────────────────────────────────────────────
# Constants & settings
# ──────────────────────────────────────────────────────────────
VOLUME_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

REFRESH_MS = 5 * 60 * 1000      # 5 min
WATCHLIST_FILE = "tradingview_watchlist.txt"
CACHE_MINUTES = 60                 # refresh active-symbol cache once per hour

# ──────────────────────────────────────────────────────────────
# Utility helpers
# ──────────────────────────────────────────────────────────────


def format_volume(volume: float) -> str:
    volume = round(volume, -4)
    return f"${volume / 1_000_000_000:.2f}B" if volume >= 1_000_000_000 else f"${volume / 1_000_000:.2f}M"


def format_price(price: float | str) -> str:
    p = float(price)
    s = f"{p:.4f}" if p < 5 else f"{p:.2f}"
    return f"${s.rstrip('0').rstrip('.')}"


def get_color(rate: float) -> str:
    if rate > 0.03:
        return "background-color: #90EE90"   # light green
    if rate < -0.03:
        return "background-color: #FFCCCC"   # light red
    return ""


# resilient requests session
session = requests.Session()
session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=3, backoff_factor=1,
            status_forcelist=[429, 451, 500, 502, 503, 504]
        )
    )
)

# ──────────────────────────────────────────────────────────────
# Active-symbol cache (no zombie contracts)
# ──────────────────────────────────────────────────────────────


def fetch_active_perp_syms() -> set[str]:
    """Return USDT-quoted PERPETUAL symbols whose status is TRADING."""
    data = session.get(EXCHANGE_INFO_URL, timeout=10).json()
    return {
        s["symbol"] for s in data["symbols"]
        if s.get("contractType") == "PERPETUAL"
        and s.get("quoteAsset") == "USDT"
        and s.get("status") == "TRADING"
    }


def ensure_active_syms_cache():
    """Populate / refresh the cached active symbol set."""
    if "active_syms" not in st.session_state:
        st.session_state.active_syms = fetch_active_perp_syms()
        st.session_state.active_syms_time = pd.Timestamp.utcnow()
    else:
        age = (pd.Timestamp.utcnow() -
               st.session_state.active_syms_time).total_seconds() / 60
        if age > CACHE_MINUTES:
            st.session_state.active_syms = fetch_active_perp_syms()
            st.session_state.active_syms_time = pd.Timestamp.utcnow()

# ──────────────────────────────────────────────────────────────
# Data fetchers
# ──────────────────────────────────────────────────────────────


def fetch_volume_data() -> pd.DataFrame:
    try:
        data = session.get(VOLUME_URL, timeout=10).json()
        rows = [
            {
                "Asset": item["symbol"].replace("USDT", ""),
                "Volume (24h, $)": float(item["quoteVolume"]),
                "Price (USDT)": float(item["lastPrice"]),
            }
            for item in data
            if (
                item.get("symbol", "").endswith("USDT")
                and item["symbol"] in st.session_state.active_syms
                and float(item.get("quoteVolume", 0)) > 100_000_000
            )
        ]
        df = pd.DataFrame(rows).sort_values("Volume (24h, $)", ascending=False)
        df["Volume (24h, $)"] = df["Volume (24h, $)"].apply(format_volume)
        df["Price (USDT)"] = df["Price (USDT)"].apply(format_price)
        df.index = range(1, len(df) + 1)
        return df
    except Exception as e:
        st.error(f"Failed to fetch volume data: {e}")
        return pd.DataFrame(columns=["Asset", "Volume (24h, $)", "Price (USDT)"])


def fetch_funding_rates() -> dict[str, float]:
    try:
        data = session.get(FUNDING_URL, timeout=10).json()
        return {
            item["symbol"].replace("USDT", ""): float(item["lastFundingRate"]) * 100
            for item in data
            if item.get("symbol", "").endswith("USDT")
        }
    except Exception as e:
        st.error(f"Failed to fetch funding: {e}")
        return {}

# ──────────────────────────────────────────────────────────────
# Watchlist export  (UPDATED)
# ──────────────────────────────────────────────────────────────


def export_watchlist(df: pd.DataFrame) -> str:
    """
    TradingView wants Binance perpetual futures as BINANCE:<base>USDT.P
    (e.g. BINANCE:BTCUSDT.P).  This generates one symbol per line.
    """
    symbols = [f"BINANCE:{row.Asset}USDT.P" for _, row in df.iterrows()]
    txt = "\n".join(symbols)
    with open(WATCHLIST_FILE, "w") as f:
        f.write(txt)
    return txt

# ──────────────────────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────────────────────


def create_dashboard():
    st_autorefresh(interval=REFRESH_MS, key="auto_refresh")
    ensure_active_syms_cache()

    vol_df = fetch_volume_data()
    funding_dict = fetch_funding_rates()
    vol_df["Funding Rate (%)"] = vol_df["Asset"].map(funding_dict)
    vol_df = vol_df[[
        "Asset", "Volume (24h, $)", "Funding Rate (%)", "Price (USDT)"]]

    # style table
    def highlight(row):
        rate = row["Funding Rate (%)"]
        return [get_color(rate) if pd.notna(rate) else "" for _ in row]

    styled = (
        vol_df.style
        .apply(highlight, axis=1)
        .set_properties(**{"text-align": "center", "border": "1px solid black", "padding": "8px"})
        .set_table_styles([{"selector": "th", "props": [("background-color", "#f0f0f0"),
                                                        ("border",
                                                         "1px solid black"),
                                                        ("padding", "8px")]}])
        .format({"Funding Rate (%)": lambda x: f"{x:.3f}" if pd.notna(x) else ""})
    )

    st.title("Binance USDT-Perpetual Pairs Dashboard")
    st.write(
        f"Data as of: {pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    st.table(styled)

    # watchlist file (one-time per hard reload)
    if "watchlist_txt" not in st.session_state:
        st.session_state.watchlist_txt = export_watchlist(vol_df)

    st.download_button(
        "Download TradingView Watchlist (.txt)",
        data=st.session_state.watchlist_txt,
        file_name=WATCHLIST_FILE,
        mime="text/plain",
    )


# ──────────────────────────────────────────────────────────────
# Run app
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    create_dashboard()
