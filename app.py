import streamlit as st
import pandas as pd
from binance.client import Client
from ta.momentum import RSIIndicator
from ta.trend import MACD

# ─── Sidebar ──────────────────────────────────────────────────────────────
st.sidebar.header("Settings")
interval           = st.sidebar.selectbox("Interval", ["1d", "4h", "1h", "15m", "1w"])
buy_rsi_daily      = st.sidebar.slider("Daily RSI Buy Threshold",   20, 60, 50)
sell_rsi_daily     = st.sidebar.slider("Daily RSI Sell Threshold",  50, 90, 65)
buy_rsi_weekly     = st.sidebar.slider("Weekly RSI Buy Threshold",  20, 60, 50)
sell_rsi_weekly    = st.sidebar.slider("Weekly RSI Sell Threshold", 50, 90, 55)
limit              = st.sidebar.number_input("History Limit (candles)", 500, 5000, 2000)

# ─── Cached Resources ───────────────────────────────────────────────────────
@st.cache_resource
def get_client():
    return Client()

@st.cache_data(show_spinner=False)
def load_data(interval: str, limit: int) -> pd.DataFrame:
    client = get_client()
    klines = client.get_klines(symbol="BTCUSDT", interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        "timestamp","open","high","low","close","volume",
        "close_time","quote_asset_volume","num_trades",
        "taker_buy_base_vol","taker_buy_quote_vol","ignore"
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df[["open","high","low","close","volume"]].astype(float)

# ─── Load & Compute ──────────────────────────────────────────────────────────
df = load_data(interval, limit)

# Daily indicators
df["rsi"]         = RSIIndicator(df["close"], window=14).rsi()
macd             = MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
df["macd"]       = macd.macd()
df["macd_signal"]= macd.macd_signal()

# ─── Compute raw daily signals ───────────────────────────────────────────────
df["daily_sig"] = ""
df.loc[
    (df["rsi"] < buy_rsi_daily) & (df["macd"] > df["macd_signal"]),
    "daily_sig"
] = "BUY"
df.loc[
    (df["rsi"] > sell_rsi_daily) & (df["macd"] < df["macd_signal"]),
    "daily_sig"
] = "SELL"

# ─── Weekly Signals ────────────────────────────────────────────────────────
weekly = df.resample("W").agg({
    "open":"first","high":"max","low":"min","close":"last","volume":"sum"
})
weekly["rsi"]         = RSIIndicator(weekly["close"], window=14).rsi()
macd_w               = MACD(weekly["close"], window_slow=26, window_fast=12, window_sign=9)
weekly["macd"]       = macd_w.macd()
weekly["macd_signal"]= macd_w.macd_signal()
weekly["signal"]     = ""
weekly.loc[
    (weekly["rsi"] < buy_rsi_weekly) & (weekly["macd"] > weekly["macd_signal"]),
    "signal"
] = "BUY"
weekly.loc[
    (weekly["rsi"] > sell_rsi_weekly) & (weekly["macd"] < weekly["macd_signal"]),
    "signal"
] = "SELL"

# Forward‑fill weekly into df
weekly_sig = weekly["signal"].reindex(df.index, method="ffill").fillna("")
df["weekly_sig"] = weekly_sig

# ─── Hybrid Trade Signal ───────────────────────────────────────────────────
trade_signal = []
for ts, row in df.iterrows():
    if (
        row["daily_sig"] == "BUY"
        and row["weekly_sig"] != "SELL"
    ):
        trade_signal.append("BUY")
    elif row["weekly_sig"] == "SELL":
        trade_signal.append("SELL")
    else:
        trade_signal.append("")
df["trade_signal"] = trade_signal

# ─── Display ────────────────────────────────────────────────────────────────
st.title("🔹 Bitcoin Hybrid Strategy Dashboard")

# 1) Daily Overview selector
st.subheader("🗓️ Daily Overview")
selected_date = st.date_input(
    "Pick a date", 
    value=df.index[-1].date(),
    min_value=df.index.min().date(),
    max_value=df.index[-1].date()
)
daily_row = df.loc[str(selected_date), [
    "open","high","low","close","volume",
    "rsi","macd","macd_signal",
    "daily_sig","weekly_sig","trade_signal"
]]
if isinstance(daily_row, pd.Series):
    daily_row = daily_row.to_frame().T
st.table(daily_row)

# 2) Price Chart with numeric markers
st.subheader("📈 Price Chart with Signals")
chart_df = pd.DataFrame({
    "Close": df["close"],
    "Buy"  : df["close"].where(df["trade_signal"]=="BUY"),
    "Sell" : df["close"].where(df["trade_signal"]=="SELL"),
})
st.line_chart(chart_df, y=["Close","Buy","Sell"], use_container_width=True)

# 3) Latest Signals
st.subheader("📰 Latest Signals")
st.dataframe(df[[
    "close","rsi","macd","macd_signal",
    "daily_sig","weekly_sig","trade_signal"
]].tail(20), use_container_width=True)

# 4) Full Daily Data Table
st.subheader("📊 Daily Data Table")
st.dataframe(df[[
    "open","high","low","close","volume",
    "rsi","macd","macd_signal",
    "daily_sig","weekly_sig","trade_signal"
]], use_container_width=True)

# 5) Download
csv = df.to_csv().encode()
st.download_button("💾 Download CSV", data=csv, file_name=f"btc_signals_{interval}.csv")
