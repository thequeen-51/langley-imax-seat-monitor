import os
import sys
import requests

def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token:
        raise RuntimeError("Missing GitHub secret: TELEGRAM_BOT_TOKEN")
    if not chat_id:
        raise RuntimeError("Missing GitHub secret: TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": (
            "✅ Langley IMAX Seat Monitor test successful!\n"
            "Your GitHub Actions workflow can send Telegram alerts."
        ),
        "disable_web_page_preview": True,
    }

    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")

    print("Telegram test message sent successfully.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
