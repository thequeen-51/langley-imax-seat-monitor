# Langley IMAX Seat Monitor — Starter

This starter repository only verifies that GitHub Actions can send a Telegram message.

## Required GitHub repository secrets

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Test

1. Open the repository's **Actions** tab.
2. Select **Test Telegram Alert**.
3. Click **Run workflow**.
4. Wait for the run to finish.
5. Check Telegram for the test message.

The actual Cineplex seat-checking code should only be added after the current
Cineplex showtime/seat request format has been validated.
