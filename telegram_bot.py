import os
import logging
import requests

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_startup_message():
    """Send a simple HTTP POST to Telegram to confirm the bot is online."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Cannot send startup message.")
        return
    
    text = "🤖 *OpenClaw Daemon Online*\n\nThe job scouting and application pipeline has started successfully. You will receive alerts here when high-match jobs are found."
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("[TELEGRAM] ✅ Startup message sent. Bot is online.")
        else:
            print(f"[TELEGRAM] ❌ Failed to send startup message: {response.text}")
    except Exception as e:
        print(f"[TELEGRAM] ❌ Exception sending startup message: {e}")
