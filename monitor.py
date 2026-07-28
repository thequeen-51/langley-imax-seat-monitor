import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import APIRequestContext, sync_playwright


MOVIE_URL = (
    "https://www.cineplex.com/movie/"
    "imax70-the-odyssey-the-imax-experience-in-7"
)

API_BASE = "https://apis.cineplex.com/prod"

THEATRE_ID = 1405
FILM_ID = 37617
THEATRE_NAME = "Cineplex Cinemas Langley"

# 依照你的优先顺序检查。
SEAT_RULES = [
    ("H", 10, 15),
    ("I", 10, 15),
    ("G", 10, 15),
]

STATE_FILE = Path("state.json")


def api_get_json(
    api: APIRequestContext,
    url: str,
) -> Any:
    """Request JSON through the browser session."""

    print(f"GET {url}")

    response = api.get(
        url,
        timeout=60_000,
        headers={
            "Accept": "application/json",
            "Referer": MOVIE_URL,
            "Origin": "https://www.cineplex.com",
        },
    )

    print(f"HTTP {response.status}")

    if not response.ok:
        body = response.text()
        raise RuntimeError(
            f"Request failed with HTTP {response.status}: "
            f"{body[:500]}"
        )

    return response.json()


def get_bookable_dates(
    api: APIRequestContext,
) -> list[datetime]:
    url = (
        f"{API_BASE}/cpx/theatrical/api/v1/dates/bookable"
        f"?locationId={THEATRE_ID}"
        f"&experiences=imax-70mm"
    )

    raw_dates = api_get_json(api, url)

    dates: list[datetime] = []

    for value in raw_dates:
        try:
            dates.append(
                datetime.fromisoformat(value)
            )
        except (TypeError, ValueError):
            print(f"Skipping invalid date: {value!r}")

    dates.sort()
    return dates


def get_sessions_for_date(
    api: APIRequestContext,
    show_date: datetime,
) -> list[dict[str, Any]]:
    date_parameter = (
        f"{show_date.month}/"
        f"{show_date.day}/"
        f"{show_date.year}"
    )

    url = (
        f"{API_BASE}/cpx/theatrical/api/v1/showtimes"
        f"?language=en"
        f"&locationId={THEATRE_ID}"
        f"&date={date_parameter}"
        f"&filmId={FILM_ID}"
        f"&experiences=imax-70mm"
    )

    payload = api_get_json(api, url)
    sessions: list[dict[str, Any]] = []

    for theatre in payload:
        if int(theatre.get("theatreId", 0)) != THEATRE_ID:
            continue

        for date_group in theatre.get("dates", []):
            for movie in date_group.get("movies", []):
                if int(movie.get("id", 0)) != FILM_ID:
                    continue

                for experience in movie.get("experiences", []):
                    experience_types = {
                        str(value).lower()
                        for value in experience.get(
                            "experienceTypes",
                            [],
                        )
                    }

                    if not (
                        "imax" in experience_types
                        and "70mm" in experience_types
                    ):
                        continue

                    for session in experience.get(
                        "sessions",
                        [],
                    ):
                        if session.get("isInThePast"):
                            continue

                        if not session.get(
                            "isShowtimeEnabledOnline",
                            True,
                        ):
                            continue

                        sessions.append(session)

    return sessions


def get_seat_layout(
    api: APIRequestContext,
    showtime_id: int,
) -> dict[str, Any]:
    url = (
        f"{API_BASE}/ticketing/api/v1/"
        f"theatre/{THEATRE_ID}/showtime/"
        f"{showtime_id}/seat-layout"
    )

    return api_get_json(api, url)


def get_seat_availability(
    api: APIRequestContext,
    showtime_id: int,
) -> dict[str, Any]:
    url = (
        f"{API_BASE}/ticketing/api/v1/"
        f"theatre/{THEATRE_ID}/showtime/"
        f"{showtime_id}/seat-availability"
    )

    return api_get_json(api, url)


def build_seat_lookup(
    layout: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Map seat IDs such as 1_3_10 to labels such as H10."""

    lookup: dict[str, dict[str, Any]] = {}

    areas = [
        layout.get("standardSeats"),
        layout.get("dboxSeats"),
        layout.get("balconySeats"),
    ]

    for area in areas:
        if not isinstance(area, dict):
            continue

        for row in area.get("rows", []):
            for seat in row.get("seats", []):
                seat_id = seat.get("id")

                if seat_id:
                    lookup[seat_id] = seat

    return lookup


def find_adjacent_pair(
    layout: dict[str, Any],
    availability: dict[str, Any],
) -> tuple[str, str] | None:
    seat_lookup = build_seat_lookup(layout)

    statuses = availability.get(
        "seatAvailabilities",
        {},
    )

    available_labels: set[str] = set()

    for seat_id, status in statuses.items():
        if str(status).lower() != "available":
            continue

        seat = seat_lookup.get(seat_id)

        if not seat:
            continue

        if seat.get("type") != "Standard":
            continue

        label = str(seat.get("label", "")).upper()

        if label:
            available_labels.add(label)

    print(
        "Available standard seats:",
        ", ".join(sorted(available_labels)) or "none",
    )

    # 严格按照 H → I → G 的优先顺序。
    for row, first_number, last_number in SEAT_RULES:
        for number in range(first_number, last_number):
            seat_one = f"{row}{number}"
            seat_two = f"{row}{number + 1}"

            if (
                seat_one in available_labels
                and seat_two in available_labels
            ):
                return seat_one, seat_two

    return None


def load_state() -> set[str]:
    if not STATE_FILE.exists():
        return set()

    try:
        data = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        return set(data.get("notified", []))

    except Exception:
        return set()


def save_state(notified: set[str]) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {"notified": sorted(notified)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def telegram_send(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError(
            "Telegram secrets are missing."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )

    response.raise_for_status()


def format_showtime(
    raw_value: str,
) -> str:
    try:
        parsed = datetime.fromisoformat(raw_value)
        return parsed.strftime("%A, %B %d, %Y at %I:%M %p")
    except (TypeError, ValueError):
        return raw_value


def main() -> None:
    print("Starting real Langley IMAX 70mm seat check")

    notified = load_state()
    new_notifications = 0
    sessions_checked = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features="
                "AutomationControlled",
            ],
        )

        context = browser.new_context(
            locale="en-CA",
            timezone_id="America/Vancouver",
            user_agent=(
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        # 先访问 Cineplex 页面，让浏览器取得正常会话和 Cookie。
        response = page.goto(
            MOVIE_URL,
            wait_until="domcontentloaded",
            timeout=90_000,
        )

        print(
            "Cineplex page HTTP:",
            response.status if response else "none",
        )

        page.wait_for_timeout(8_000)

        bookable_dates = get_bookable_dates(
            context.request
        )

        print(
            f"Bookable dates found: "
            f"{len(bookable_dates)}"
        )

        for show_date in bookable_dates:
            print(
                "\nChecking date:",
                show_date.date().isoformat(),
            )

            try:
                sessions = get_sessions_for_date(
                    context.request,
                    show_date,
                )
            except Exception as exc:
                print(
                    f"Could not load showtimes: {exc}"
                )
                continue

            for session in sessions:
                showtime_id = int(
                    session["vistaSessionId"]
                )

                start_time = str(
                    session.get(
                        "showStartDateTime",
                        "",
                    )
                )

                sessions_checked += 1

                print(
                    f"\nChecking showtime "
                    f"{showtime_id}: "
                    f"{start_time}"
                )

                try:
                    layout = get_seat_layout(
                        context.request,
                        showtime_id,
                    )

                    availability = (
                        get_seat_availability(
                            context.request,
                            showtime_id,
                        )
                    )

                    pair = find_adjacent_pair(
                        layout,
                        availability,
                    )

                except Exception as exc:
                    print(
                        f"Seat check failed for "
                        f"{showtime_id}: {exc}"
                    )
                    continue

                if not pair:
                    print(
                        "No preferred adjacent pair."
                    )
                    continue

                seat_one, seat_two = pair

                notification_key = (
                    f"{showtime_id}:"
                    f"{seat_one}:{seat_two}"
                )

                preview_url = (
                    "https://www.cineplex.com/"
                    "en/ticketing/preview"
                    f"?theatreId={THEATRE_ID}"
                    f"&showtimeId={showtime_id}"
                    "&dbox=false"
                )

                print(
                    "MATCH FOUND:",
                    seat_one,
                    seat_two,
                )

                if notification_key in notified:
                    print(
                        "This exact result was already "
                        "notified."
                    )
                    continue

                message = (
                    "🎬 The Odyssey — IMAX 70mm\n\n"
                    f"📍 {THEATRE_NAME}\n"
                    f"🗓 {format_showtime(start_time)}\n"
                    f"🪑 {seat_one} + {seat_two}\n\n"
                    f"Book / preview:\n{preview_url}"
                )

                telegram_send(message)

                notified.add(notification_key)
                new_notifications += 1
                save_state(notified)

        context.close()
        browser.close()

    print("\nSeat check finished.")
    print(f"Sessions checked: {sessions_checked}")
    print(
        f"New Telegram notifications: "
        f"{new_notifications}"
    )


if __name__ == "__main__":
    main()
