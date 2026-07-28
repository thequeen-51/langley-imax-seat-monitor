# Langley IMAX 70mm Seat Monitor

Monitors Cineplex Cinemas Langley (`theatreId=1405`) for future **The Odyssey — IMAX 70mm** showtimes and sends Telegram alerts.

## Seat rule

Two adjacent seats, in this order:

1. H10–H15
2. I10–I15
3. G10–G15

The monitor also alerts when Cineplex adds a new matching showtime.

## Installation in GitHub

1. Open your repository `thequeen-51/langley-imax-seat-monitor`.
2. Upload all files from this package, preserving the `.github/workflows/` folder.
3. Keep the existing repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Open **Actions → Langley IMAX Seat Monitor → Run workflow**.
5. Open the run log.

## Important validation step

Cineplex's seat-map interface is undocumented and can change. This monitor:

- uses Cineplex's current public showtimes API to discover future showtimes;
- opens each matching ticket page in Chromium;
- watches JSON network responses;
- detects seat objects flexibly instead of relying on one guessed endpoint;
- uploads a `cineplex-debug` artifact containing screenshots and HTML.

A run is fully validated only when the log shows candidate seat responses or `state.json` contains:

```json
"seat_payload_detected": true
```

If it remains `false`, download the `cineplex-debug` artifact from the workflow run. The screenshots/HTML will show which control needs one additional selector. Do not assume seat alerts are active until this validation passes.

## Notes

- GitHub scheduled workflows may start later than the nominal five-minute interval.
- The script never buys or reserves tickets. It only reads availability and sends a purchase link.
- `state.json` prevents repeated alerts while the same pair remains available.
