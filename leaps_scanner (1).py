"""
=============================================================================
  WEEKLY RSI LEAPS SCANNER — Telegram Alerts w/ Conviction Tiers
  Based on @JasonL_Capital's setup
=============================================================================
"""

import yfinance as yf
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta

# =============================================================================
# CONFIG
# =============================================================================

RSI_THRESHOLD = 30
MIN_DTE = 360
OTM_PERCENT = 10

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# =============================================================================
# WATCHLIST WITH CONVICTION TIERS
# =============================================================================
# Tier 1 (🟢 A+) = Blue chip / market leaders. High conviction LEAPS plays.
#                   These companies aren't going anywhere. When they're oversold,
#                   it's almost always a gift.
#
# Tier 2 (🟡 B+) = Strong companies but more volatile. Good LEAPS candidates
#                   but size smaller than Tier 1.
#
# Tier 3 (🟠 C+) = Speculative / high-risk. Could 10x or go to zero.
#                   Only play these if you have a strong thesis. Small size only.
# =============================================================================

TIER_1 = {
    # Mega cap tech — not going bankrupt, ever
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO",
    # Dominant franchises
    "V", "MA", "COST", "WMT", "UNH",
    # Enterprise software leaders
    "CRM", "ADBE", "NOW", "ORCL",
}

TIER_2 = {
    # Strong but more cyclical / volatile
    "TSLA", "AMD", "QCOM", "MRVL", "AMAT", "LRCX", "KLAC", "MU",
    "NFLX", "BKNG", "UBER", "ABNB",
    "CRWD", "PANW", "ZS", "DDOG", "NET", "SNOW", "MDB", "SHOP",
    "PYPL", "ISRG", "TMO", "DHR", "ABBV",
    "IBM", "ACN", "AXP", "INTC",
    "PLTR", "SPOT", "DASH",
}

TIER_3 = {
    # Speculative — high reward but real risk of permanent loss
    "HOOD", "COIN", "AFRM", "SOFI",
    "RBLX", "PINS", "ROKU", "TTD",
    "IREN", "AI", "PATH", "S", "SMCI",
    "ON", "AMKR", "ENPH", "SEDG",
    "RIVN", "LCID", "DXCM",
}

WATCHLIST = list(TIER_1 | TIER_2 | TIER_3)


def get_tier(ticker):
    if ticker in TIER_1:
        return 1, "🟢 A+", "HIGH CONVICTION — size up"
    elif ticker in TIER_2:
        return 2, "🟡 B+", "SOLID — normal size"
    else:
        return 3, "🟠 C+", "SPECULATIVE — small size only"


# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def calculate_weekly_rsi(ticker, period=14):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y", interval="1wk")

        if df.empty or len(df) < period + 1:
            print(f"  ⚠ {ticker}: Insufficient data")
            return None

        close = df["Close"]
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        current_rsi = round(rsi.iloc[-1], 2)
        prev_rsi = round(rsi.iloc[-2], 2) if len(rsi) > 1 else None
        current_price = round(close.iloc[-1], 2)
        high_52w = round(df["High"].max(), 2)
        drawdown = round((1 - current_price / high_52w) * 100, 1)

        return {
            "ticker": ticker,
            "price": current_price,
            "weekly_rsi": current_rsi,
            "prev_weekly_rsi": prev_rsi,
            "high_52w": high_52w,
            "drawdown_pct": drawdown,
            "just_crossed": prev_rsi is not None and prev_rsi >= RSI_THRESHOLD and current_rsi < RSI_THRESHOLD,
        }
    except Exception as e:
        print(f"  ⚠ {ticker}: Error — {e}")
        return None


def get_options_suggestion(ticker, current_price):
    otm_strike = round(current_price * (1 + OTM_PERCENT / 100))
    if otm_strike > 50:
        otm_strike = round(otm_strike / 5) * 5
    elif otm_strike > 10:
        otm_strike = round(otm_strike / 2.5) * 2.5

    target_expiry = datetime.now() + timedelta(days=MIN_DTE)
    expiry_str = f"Jan {target_expiry.year + 1}"

    return {
        "strike": otm_strike,
        "expiry": expiry_str,
        "chain_url": f"https://finance.yahoo.com/quote/{ticker}/options/",
    }


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  ❌ Telegram credentials not set")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as response:
            print("  ✅ Telegram message sent!")
    except Exception as e:
        print(f"  ❌ Telegram error: {e}")


# =============================================================================
# MAIN
# =============================================================================

def run_scanner():
    print("=" * 60)
    print("  WEEKLY RSI LEAPS SCANNER")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}")
    print(f"  Scanning {len(WATCHLIST)} stocks for Weekly RSI < {RSI_THRESHOLD}")
    print("=" * 60)

    results = []

    for i, ticker in enumerate(WATCHLIST):
        print(f"  [{i+1}/{len(WATCHLIST)}] Scanning {ticker}...", end="")
        data = calculate_weekly_rsi(ticker)

        if data is None:
            print(" skipped")
            continue

        results.append(data)

        if data["weekly_rsi"] < RSI_THRESHOLD:
            crossed = " ← JUST CROSSED" if data["just_crossed"] else ""
            print(f" 🔴 RSI = {data['weekly_rsi']} — OVERSOLD!{crossed}")
        elif data["weekly_rsi"] < 35:
            print(f" 🟡 RSI = {data['weekly_rsi']} — approaching oversold")
        else:
            print(f" ✅ RSI = {data['weekly_rsi']}")

    # Separate results
    oversold = sorted([r for r in results if r["weekly_rsi"] < RSI_THRESHOLD], key=lambda x: x["weekly_rsi"])
    approaching = sorted([r for r in results if RSI_THRESHOLD <= r["weekly_rsi"] < 35], key=lambda x: x["weekly_rsi"])

    # Print summary
    print("\n" + "=" * 60)
    if oversold:
        print(f"\n🔴 OVERSOLD (Weekly RSI < {RSI_THRESHOLD}):")
        for s in oversold:
            tier_num, tier_label, _ = get_tier(s["ticker"])
            crossed = " ← JUST CROSSED" if s["just_crossed"] else ""
            print(f"   [{tier_label}] {s['ticker']:6s}  RSI: {s['weekly_rsi']:5.1f}  Price: ${s['price']:>10.2f}  "
                  f"Drawdown: -{s['drawdown_pct']}%{crossed}")
    else:
        print("\n✅ No stocks with Weekly RSI below 30.")

    if approaching:
        print(f"\n🟡 APPROACHING (Weekly RSI 30-35):")
        for s in approaching:
            print(f"   {s['ticker']:6s}  RSI: {s['weekly_rsi']:5.1f}  Price: ${s['price']:>10.2f}  "
                  f"Drawdown: -{s['drawdown_pct']}%")

    # === SEND TELEGRAM ALERTS ===
    if oversold:
        # Group by tier
        tier1_alerts = [s for s in oversold if s["ticker"] in TIER_1]
        tier2_alerts = [s for s in oversold if s["ticker"] in TIER_2]
        tier3_alerts = [s for s in oversold if s["ticker"] in TIER_3]

        msg = "🚨 <b>LEAPS SCANNER ALERT</b>\n"
        msg += f"📅 {datetime.now().strftime('%A, %b %d %Y')}\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━━\n\n"

        # TIER 1
        if tier1_alerts:
            msg += "🟢 <b>TIER 1 — HIGH CONVICTION</b>\n"
            msg += "<i>Blue chips. Size up. These are the plays.</i>\n\n"
            for s in tier1_alerts:
                opts = get_options_suggestion(s["ticker"], s["price"])
                crossed = " 🔥 JUST CROSSED" if s["just_crossed"] else ""
                msg += f"<b>${s['ticker']}</b>{crossed}\n"
                msg += f"  ${s['price']}  |  RSI: {s['weekly_rsi']}  |  -{s['drawdown_pct']}%\n"
                msg += f"  ➡️ <b>Buy ${opts['strike']}C exp {opts['expiry']}+</b>\n"
                msg += f"  📊 <a href=\"{opts['chain_url']}\">Options Chain</a>\n\n"

        # TIER 2
        if tier2_alerts:
            msg += "🟡 <b>TIER 2 — SOLID PLAYS</b>\n"
            msg += "<i>Strong companies. Normal size.</i>\n\n"
            for s in tier2_alerts:
                opts = get_options_suggestion(s["ticker"], s["price"])
                crossed = " 🔥 JUST CROSSED" if s["just_crossed"] else ""
                msg += f"<b>${s['ticker']}</b>{crossed}\n"
                msg += f"  ${s['price']}  |  RSI: {s['weekly_rsi']}  |  -{s['drawdown_pct']}%\n"
                msg += f"  ➡️ Buy ${opts['strike']}C exp {opts['expiry']}+\n"
                msg += f"  📊 <a href=\"{opts['chain_url']}\">Options Chain</a>\n\n"

        # TIER 3
        if tier3_alerts:
            msg += "🟠 <b>TIER 3 — SPECULATIVE</b>\n"
            msg += "<i>High risk. Small size only. Could go either way.</i>\n\n"
            for s in tier3_alerts:
                opts = get_options_suggestion(s["ticker"], s["price"])
                crossed = " 🔥 JUST CROSSED" if s["just_crossed"] else ""
                msg += f"<b>${s['ticker']}</b>{crossed}\n"
                msg += f"  ${s['price']}  |  RSI: {s['weekly_rsi']}  |  -{s['drawdown_pct']}%\n"
                msg += f"  ➡️ Buy ${opts['strike']}C exp {opts['expiry']}+\n"
                msg += f"  📊 <a href=\"{opts['chain_url']}\">Options Chain</a>\n\n"

        msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"<b>STRATEGY RULES:</b>\n"
        msg += f"• Buy 360+ DTE calls, 10% OTM\n"
        msg += f"• Sell HALF at 100% gain\n"
        msg += f"• Hold rest until 60 DTE\n"
        msg += f"• Tier 1 = size up, Tier 3 = small bets\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━━\n\n"

        if approaching:
            msg += f"👀 <b>WATCH LIST (RSI 30-35):</b>\n"
            for s in approaching:
                _, tier_label, _ = get_tier(s["ticker"])
                msg += f"  {tier_label} ${s['ticker']} — RSI: {s['weekly_rsi']} — ${s['price']}\n"

        msg += f"\n<i>⚠️ Not financial advice. Do your own DD.</i>"

        print(f"\n📱 Sending Telegram alert...")
        send_telegram(msg)
    else:
        msg = f"✅ <b>LEAPS Scanner</b> — {datetime.now().strftime('%b %d')}\n"
        msg += f"No stocks below RSI 30. Be patient.\n"
        if approaching:
            msg += f"\n👀 <b>Approaching:</b>\n"
            for s in approaching:
                _, tier_label, _ = get_tier(s["ticker"])
                msg += f"  {tier_label} ${s['ticker']} — RSI: {s['weekly_rsi']} — ${s['price']}\n"
        print(f"\n📱 Sending Telegram status...")
        send_telegram(msg)

    print("\n" + "=" * 60)
    print("  Scan complete.")
    print("=" * 60)


if __name__ == "__main__":
    run_scanner()
