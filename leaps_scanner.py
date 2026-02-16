"""
=============================================================================
  WEEKLY RSI LEAPS SCANNER
  Based on @JasonL_Capital's setup
=============================================================================

  WHAT IT DOES:
  - Checks weekly RSI(14) on your watchlist of stocks
  - When weekly RSI drops below 30, sends you an email alert
  - The email includes: current price, RSI value, suggested 10% OTM strike,
    target expiration (360+ DTE), and a direct link to the options chain

  SETUP (5 minutes):
  1. Install dependencies:    pip install yfinance pandas
  2. Fill in your email settings in the CONFIG section below
  3. Customize your WATCHLIST
  4. Run it:                  python leaps_scanner.py
  5. Schedule it to run daily (see instructions at bottom of file)

=============================================================================
"""

import yfinance as yf
import pandas as pd
import smtplib
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pathlib import Path

# =============================================================================
# CONFIG — FILL THESE IN
# =============================================================================

# Your email settings (Gmail example — see notes below for other providers)
EMAIL_CONFIG = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "YOUR_EMAIL@gmail.com",
    "sender_password": "YOUR_APP_PASSWORD",  # Use Gmail App Password, NOT your real password
    "recipient_email": "YOUR_EMAIL@gmail.com",  # Where to receive alerts (can be same)
}

# RSI threshold — the setup triggers below this
RSI_THRESHOLD = 30

# Minimum days to expiration for LEAPs
MIN_DTE = 360

# OTM percentage for strike selection
OTM_PERCENT = 10

# File to track already-alerted stocks (prevents duplicate emails)
ALERT_HISTORY_FILE = "leaps_alert_history.json"

# =============================================================================
# WATCHLIST — Customize this with stocks you'd buy LEAPs on
# =============================================================================
# Focus on quality names with liquid options chains.
# The setup works best on growth stocks that have been beaten down.

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
    "PYPL", "SQ", "HOOD", "COIN", "V", "MA", "AFRM", "SOFI",

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
    """
    Download weekly price data and calculate RSI(14) on the weekly timeframe.
    Returns dict with ticker info or None if data unavailable.
    """
    try:
        stock = yf.Ticker(ticker)
        # Get 1 year of weekly data (enough for RSI calculation)
        df = stock.history(period="1y", interval="1wk")

        if df.empty or len(df) < period + 1:
            print(f"  ⚠ {ticker}: Insufficient data")
            return None

        # Calculate RSI on weekly closes
        close = df["Close"]
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        # Wilder's smoothing (exponential moving average)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        current_rsi = round(rsi.iloc[-1], 2)
        prev_rsi = round(rsi.iloc[-2], 2) if len(rsi) > 1 else None
        current_price = round(close.iloc[-1], 2)

        # Get some additional context
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
    """
    Calculate the suggested LEAPS trade based on the strategy rules.
    """
    otm_strike = round(current_price * (1 + OTM_PERCENT / 100))
    # Round to nearest $5 for cleaner strikes
    if otm_strike > 50:
        otm_strike = round(otm_strike / 5) * 5
    elif otm_strike > 10:
        otm_strike = round(otm_strike / 2.5) * 2.5

    target_expiry = datetime.now() + timedelta(days=MIN_DTE)
    # LEAPs typically expire in January or June
    if target_expiry.month <= 6:
        expiry_str = f"January {target_expiry.year + 1}"
    else:
        expiry_str = f"January {target_expiry.year + 1}"

    half_exit_target = round(current_price * (1 + OTM_PERCENT / 100) * 0.5, 2)

    return {
        "strike": otm_strike,
        "min_expiry": target_expiry.strftime("%Y-%m-%d"),
        "expiry_suggestion": expiry_str,
        "exit_half_at": "100% gain (2x entry price)",
        "exit_rest_at": "60 DTE remaining",
        "options_chain_url": f"https://finance.yahoo.com/quote/{ticker}/options/",
    }


def load_alert_history() -> dict:
    """Load previously alerted stocks to avoid duplicate notifications."""
    if os.path.exists(ALERT_HISTORY_FILE):
        with open(ALERT_HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}


def save_alert_history(history: dict):
    """Save alert history."""
    with open(ALERT_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def should_alert(ticker: str, history: dict) -> bool:
    """
    Only alert once per oversold episode.
    Reset when RSI goes back above 40 (out of oversold territory).
    """
    if ticker not in history:
        return True

    last_alert = history[ticker]
    last_alert_date = datetime.fromisoformat(last_alert["date"])

    # Don't re-alert within 7 days
    if (datetime.now() - last_alert_date).days < 7:
        return False

    return True


def send_email_alert(alerts: list[dict]):
    """Send a formatted email with all triggered LEAPS setups."""
    if not alerts:
        return

    # Build email body
    subject = f"🚨 LEAPS Scanner: {len(alerts)} Stock(s) Triggered Weekly RSI <{RSI_THRESHOLD}"

    html = f"""
    <html>
    <body style="font-family: 'Courier New', monospace; background: #0a0a0f; color: #e0e0e0; padding: 20px;">
        <div style="max-width: 700px; margin: 0 auto;">
            <h1 style="color: #00ff88; font-size: 22px; border-bottom: 1px solid #1a2332; padding-bottom: 12px;">
                Weekly RSI LEAPS Scanner Alert
            </h1>
            <p style="color: #5a6a7a; font-size: 14px;">
                {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}
            </p>
            <p style="color: #ffaa00; font-size: 14px; background: #1a1a0f; padding: 12px; border-radius: 6px;">
                ⚠️ The following stock(s) have Weekly RSI below {RSI_THRESHOLD} — potential LEAPS entry candidates.
            </p>
    """

    for alert in alerts:
        stock = alert["stock"]
        options = alert["options"]
        crossed_badge = "🔥 JUST CROSSED BELOW" if stock["just_crossed"] else "📉 STILL OVERSOLD"

        html += f"""
            <div style="background: #111118; border: 1px solid #1a2332; border-radius: 8px; padding: 18px; margin: 16px 0;">
                <h2 style="color: #ffffff; margin: 0 0 4px;">
                    {stock['ticker']}
                    <span style="color: #00ff88; font-size: 14px; margin-left: 8px;">{crossed_badge}</span>
                </h2>

                <table style="width: 100%; font-size: 14px; margin-top: 12px; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 6px 0; color: #5a6a7a;">Current Price</td>
                        <td style="padding: 6px 0; color: #ffffff; font-weight: bold;">${stock['price']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #5a6a7a;">Weekly RSI</td>
                        <td style="padding: 6px 0; color: #ff4444; font-weight: bold;">{stock['weekly_rsi']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #5a6a7a;">Previous Week RSI</td>
                        <td style="padding: 6px 0; color: #aabbcc;">{stock['prev_weekly_rsi']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #5a6a7a;">52-Week High</td>
                        <td style="padding: 6px 0; color: #aabbcc;">${stock['high_52w']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; color: #5a6a7a;">Drawdown from High</td>
                        <td style="padding: 6px 0; color: #ff8800;">-{stock['drawdown_pct']}%</td>
                    </tr>
                </table>

                <div style="background: #0d1a0d; border: 1px solid #1a3d1a; border-radius: 6px; padding: 14px; margin-top: 14px;">
                    <h3 style="color: #00ff88; font-size: 14px; margin: 0 0 10px;">Suggested LEAPS Trade</h3>
                    <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 4px 0; color: #5a6a7a;">Strike (10% OTM)</td>
                            <td style="padding: 4px 0; color: #00ccff; font-weight: bold;">${options['strike']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px 0; color: #5a6a7a;">Expiration</td>
                            <td style="padding: 4px 0; color: #00ccff; font-weight: bold;">{options['expiry_suggestion']} or later</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px 0; color: #5a6a7a;">Exit Half At</td>
                            <td style="padding: 4px 0; color: #ffaa00;">{options['exit_half_at']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px 0; color: #5a6a7a;">Exit Rest At</td>
                            <td style="padding: 4px 0; color: #ffaa00;">{options['exit_rest_at']}</td>
                        </tr>
                    </table>
                    <p style="margin: 12px 0 0;">
                        <a href="{options['options_chain_url']}" style="color: #00ff88;">
                            View Options Chain →
                        </a>
                    </p>
                </div>
            </div>
        """

    html += """
            <div style="color: #3a4a5a; font-size: 11px; margin-top: 24px; padding-top: 12px; border-top: 1px solid #1a2332;">
                This is not financial advice. Options involve significant risk of loss.
                Based on a publicly shared strategy. Always do your own due diligence.
            </div>
        </div>
    </body>
    </html>
    """

    # Send email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_CONFIG["sender_email"]
    msg["To"] = EMAIL_CONFIG["recipient_email"]
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
            server.sendmail(
                EMAIL_CONFIG["sender_email"],
                EMAIL_CONFIG["recipient_email"],
                msg.as_string()
            )
        print(f"\n✅ Alert email sent to {EMAIL_CONFIG['recipient_email']}")
    except Exception as e:
        print(f"\n❌ Failed to send email: {e}")
        print("   Check your EMAIL_CONFIG settings. See setup instructions below.")


# =============================================================================
# MAIN SCANNER
# =============================================================================

def run_scanner():
    print("=" * 60)
    print("  WEEKLY RSI LEAPS SCANNER")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}")
    print(f"  Scanning {len(WATCHLIST)} stocks for Weekly RSI < {RSI_THRESHOLD}")
    print("=" * 60)

    alert_history = load_alert_history()
    results = []
    alerts_to_send = []

    for i, ticker in enumerate(WATCHLIST):
        print(f"  [{i+1}/{len(WATCHLIST)}] Scanning {ticker}...", end="")
        data = calculate_weekly_rsi(ticker)

        if data is None:
            print(" skipped")
            continue

        results.append(data)

        if data["weekly_rsi"] < RSI_THRESHOLD:
            print(f" 🔴 RSI = {data['weekly_rsi']} — OVERSOLD!")

            if should_alert(ticker, alert_history):
                options = get_options_suggestion(ticker, data["price"])
                alerts_to_send.append({"stock": data, "options": options})

                # Update history
                alert_history[ticker] = {
                    "date": datetime.now().isoformat(),
                    "rsi": data["weekly_rsi"],
                    "price": data["price"],
                }
        elif data["weekly_rsi"] < 35:
            print(f" 🟡 RSI = {data['weekly_rsi']} — approaching oversold")
        else:
            print(f" ✅ RSI = {data['weekly_rsi']}")

        # Reset alert history if RSI recovered above 40
        if data["weekly_rsi"] > 40 and ticker in alert_history:
            del alert_history[ticker]

    # Save updated history
    save_alert_history(alert_history)

    # Summary
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

    # Send email alerts
    if alerts_to_send:
        print(f"\n📧 Sending alerts for {len(alerts_to_send)} new signal(s)...")
        send_email_alert(alerts_to_send)
    else:
        print("\n📧 No new alerts to send (either no signals or already alerted).")

    print("\n" + "=" * 60)
    print("  Scan complete. Run again tomorrow or set up a cron job.")
    print("=" * 60)


if __name__ == "__main__":
    run_scanner()


# =============================================================================
# SETUP INSTRUCTIONS
# =============================================================================
"""
QUICK START:
============

1. INSTALL DEPENDENCIES:
   pip install yfinance pandas

2. SET UP GMAIL APP PASSWORD (recommended):
   - Go to https://myaccount.google.com/apppasswords
   - You need 2-Factor Authentication enabled first
   - Generate an "App Password" for "Mail"
   - Paste it into EMAIL_CONFIG["sender_password"] above
   - This is NOT your Gmail login password

   For other email providers:
   - Outlook: smtp_server="smtp.office365.com", smtp_port=587
   - Yahoo:   smtp_server="smtp.mail.yahoo.com", smtp_port=587

3. TEST IT:
   python leaps_scanner.py

4. SCHEDULE IT TO RUN DAILY:

   === macOS / Linux (cron) ===
   Run: crontab -e
   Add this line (runs at 5pm ET every weekday):
   0 17 * * 1-5 cd /path/to/script && /usr/bin/python3 leaps_scanner.py >> scanner.log 2>&1

   === Windows (Task Scheduler) ===
   - Open Task Scheduler
   - Create Basic Task → "LEAPS Scanner"
   - Trigger: Daily at 5:00 PM
   - Action: Start a Program
     Program: python
     Arguments: C:\\path\\to\\leaps_scanner.py

   === PythonAnywhere (free, runs in cloud) ===
   - Sign up at pythonanywhere.com (free tier)
   - Upload this script
   - Go to Tasks → add a scheduled task
   - Set it to run daily at 21:00 UTC (5pm ET)
   - Command: python3 /home/yourusername/leaps_scanner.py

5. CUSTOMIZE YOUR WATCHLIST:
   Edit the WATCHLIST variable above. Focus on:
   - Stocks with liquid options (high open interest)
   - Companies you fundamentally believe in
   - Growth stocks that could bounce hard from oversold
   - Avoid: penny stocks, low-volume names, companies in real trouble
"""
