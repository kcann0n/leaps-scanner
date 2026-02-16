"""
=============================================================================
  WEEKLY RSI LEAPS SCANNER
  Based on @JasonL_Capital's setup
=============================================================================

  WHAT IT DOES:
  - Checks weekly RSI(14) on your watchlist of stocks
  - When weekly RSI drops below 30, creates a GitHub Issue as an alert
  - The alert includes: current price, RSI value, suggested 10% OTM strike,
    target expiration (360+ DTE), and a direct link to the options chain
  - GitHub sends you an email notification automatically for new Issues

  SETUP:
  - No email config needed — GitHub handles notifications
  - Just make sure you have "Watch" enabled on your repo (default)

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

# =============================================================================
# WATCHLIST — Customize this with stocks you'd buy LEAPs on
# =============================================================================

WATCHLIST = [
    # === Mega Cap Tech ===
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO",

    # === Software / Cloud ===
    "CRM", "ADBE", "NOW", "SNOW", "PLTR", "DDOG", "NET", "CRWD",
    "PANW", "ZS", "MDB", "SHOP",

    # === Semiconductors ===
    "AMD", "QCOM", "MRVL", "AMAT", "LRCX", "KLAC", "AMKR", "ON",
    "MU", "INTC",

    # === Fintech / Payments ===
    "PYPL", "HOOD", "COIN", "V", "MA", "AFRM", "SOFI",

    # === Internet / Consumer ===
    "NFLX", "BKNG", "UBER", "ABNB", "DASH", "SPOT", "RBLX", "PINS",

    # === AI / Data / Infrastructure ===
    "IREN", "AI", "PATH", "S", "SMCI",

    # === Healthcare / Biotech ===
    "UNH", "ISRG", "DXCM", "TMO", "DHR", "ABBV",

    # === High-Growth / Speculative ===
    "ROKU", "TTD", "ENPH", "SEDG", "RIVN", "LCID",

    # === Other Quality ===
    "ACN", "AXP", "ORCL", "IBM", "COST", "WMT",
]


# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def calculate_weekly_rsi(ticker: str, period: int = 14) -> dict | None:
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
        low_52w = round(df["Low"].min(), 2)
        drawdown_from_high = round((1 - current_price / high_52w) * 100, 1)

        return {
            "ticker": ticker,
            "price": current_price,
            "weekly_rsi": current_rsi,
            "prev_weekly_rsi": prev_rsi,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "drawdown_pct": drawdown_from_high,
            "just_crossed": prev_rsi is not None and prev_rsi >= RSI_THRESHOLD and current_rsi < RSI_THRESHOLD,
        }

    except Exception as e:
        print(f"  ⚠ {ticker}: Error — {e}")
        return None


def get_options_suggestion(ticker: str, current_price: float) -> dict:
    otm_strike = round(current_price * (1 + OTM_PERCENT / 100))
    if otm_strike > 50:
        otm_strike = round(otm_strike / 5) * 5
    elif otm_strike > 10:
        otm_strike = round(otm_strike / 2.5) * 2.5

    target_expiry = datetime.now() + timedelta(days=MIN_DTE)
    expiry_str = f"January {target_expiry.year + 1}"

    return {
        "strike": otm_strike,
        "min_expiry": target_expiry.strftime("%Y-%m-%d"),
        "expiry_suggestion": expiry_str,
        "exit_half_at": "100% gain (2x entry price)",
        "exit_rest_at": "60 DTE remaining",
        "options_chain_url": f"https://finance.yahoo.com/quote/{ticker}/options/",
    }


def create_github_issue(alerts: list[dict], approaching: list[dict]):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        print("  ❌ GITHUB_TOKEN or GITHUB_REPOSITORY not found.")
        return

    date_str = datetime.now().strftime("%b %d, %Y")
    tickers = ", ".join([a["stock"]["ticker"] for a in alerts])
    title = f"🚨 LEAPS Alert — {len(alerts)} stock(s) oversold: {tickers} [{date_str}]"

    body = f"# Weekly RSI LEAPS Scanner Alert\n"
    body += f"**{datetime.now().strftime('%A, %B %d, %Y')}**\n\n---\n\n"
    body += f"## 🔴 OVERSOLD — Weekly RSI Below {RSI_THRESHOLD}\n\n"

    for alert in alerts:
        stock = alert["stock"]
        options = alert["options"]
        crossed = " 🔥 **JUST CROSSED BELOW 30**" if stock["just_crossed"] else ""

        body += f"### {stock['ticker']} — ${stock['price']} (RSI: {stock['weekly_rsi']}){crossed}\n\n"
        body += f"| Metric | Value |\n|---|---|\n"
        body += f"| Current Price | **${stock['price']}** |\n"
        body += f"| Weekly RSI | **{stock['weekly_rsi']}** |\n"
        body += f"| Previous Week RSI | {stock['prev_weekly_rsi']} |\n"
        body += f"| 52-Week High | ${stock['high_52w']} |\n"
        body += f"| Drawdown from High | **-{stock['drawdown_pct']}%** |\n\n"

        body += f"**Suggested LEAPS Trade:**\n\n"
        body += f"| | |\n|---|---|\n"
        body += f"| Strike (10% OTM) | **${options['strike']}** |\n"
        body += f"| Expiration | **{options['expiry_suggestion']}** or later (360+ DTE) |\n"
        body += f"| Exit Half At | {options['exit_half_at']} |\n"
        body += f"| Exit Rest At | {options['exit_rest_at']} |\n"
        body += f"| Options Chain | [View on Yahoo Finance]({options['options_chain_url']}) |\n\n"
        body += f"---\n\n"

    if approaching:
        body += f"## 🟡 APPROACHING — Weekly RSI 30-35 (Watch List)\n\n"
        body += f"| Ticker | RSI | Price | Drawdown |\n|---|---|---|---|\n"
        for s in approaching:
            body += f"| **{s['ticker']}** | {s['weekly_rsi']} | ${s['price']} | -{s['drawdown_pct']}% |\n"
        body += f"\n---\n\n"

    body += f"*⚠️ Not financial advice. Options involve significant risk. Do your own DD.*\n"

    url = f"https://api.github.com/repos/{repo}/issues"
    data = json.dumps({
        "title": title,
        "body": body,
        "labels": ["leaps-alert"],
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read())
            print(f"\n✅ GitHub Issue created: {result['html_url']}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"\n❌ Failed to create GitHub Issue: {e.code} {error_body}")
    except Exception as e:
        print(f"\n❌ Failed to create GitHub Issue: {e}")


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

    print("\n" + "=" * 60)
    oversold = [r for r in results if r["weekly_rsi"] < RSI_THRESHOLD]
    approaching = [r for r in results if RSI_THRESHOLD <= r["weekly_rsi"] < 35]

    if oversold:
        print(f"\n🔴 OVERSOLD (Weekly RSI < {RSI_THRESHOLD}):")
        for s in sorted(oversold, key=lambda x: x["weekly_rsi"]):
            crossed = " ← JUST CROSSED" if s["just_crossed"] else ""
            print(f"   {s['ticker']:6s}  RSI: {s['weekly_rsi']:5.1f}  Price: ${s['price']:>10.2f}  "
                  f"Drawdown: -{s['drawdown_pct']}%{crossed}")
    else:
        print("\n✅ No stocks with Weekly RSI below 30. Setup not active — be patient.")

    if approaching:
        print(f"\n🟡 APPROACHING (Weekly RSI 30-35) — Watch these:")
        for s in sorted(approaching, key=lambda x: x["weekly_rsi"]):
            print(f"   {s['ticker']:6s}  RSI: {s['weekly_rsi']:5.1f}  Price: ${s['price']:>10.2f}  "
                  f"Drawdown: -{s['drawdown_pct']}%")

    if oversold:
        alerts = []
        for stock in sorted(oversold, key=lambda x: x["weekly_rsi"]):
            options = get_options_suggestion(stock["ticker"], stock["price"])
            alerts.append({"stock": stock, "options": options})

        print(f"\n📝 Creating GitHub Issue for {len(alerts)} signal(s)...")
        create_github_issue(alerts, approaching)
    else:
        print("\n📝 No alerts — no GitHub Issue created.")

    print("\n" + "=" * 60)
    print("  Scan complete.")
    print("=" * 60)


if __name__ == "__main__":
    run_scanner()
