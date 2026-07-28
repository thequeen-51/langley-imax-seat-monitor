import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import (
    APIRequestContext,
    Page,
    sync_playwright,
)


MOVIE_URL = (
    "https://www.cineplex.com/movie/"
    "imax70-the-odyssey-the-imax-experience-in-7"
)

THEATRE_ID = "1405"
THEATRE_NAME = "Cineplex Cinemas Langley"
FILM_ID = "37617"

DEBUG_DIR = Path("debug")

SEAT_PRIORITY = [
    ("H", 10, 15),
    ("I", 10, 15),
    ("G", 10, 15),
]


def click_first_visible(
    locator: Any,
    description: str,
) -> bool:
    """Click the first visible item in a Playwright locator."""

    for index in range(locator.count()):
        item = locator.nth(index)

        try:
            if not item.is_visible():
                continue

            print(f"Clicking {description}")

            item.scroll_into_view_if_needed()
            item.click(timeout=10_000)

            return True

        except Exception as exc:
            print(
                f"{description} click attempt failed:",
                type(exc).__name__,
                str(exc),
            )

    return False


def close_cookie_banner(page: Page) -> None:
    """Close a cookie banner if Cineplex displays one."""

    labels = [
        "OK",
        "Accept All",
        "Accept",
        "I Accept",
        "Agree",
    ]

    for label in labels:
        try:
            button = page.get_by_role(
                "button",
                name=label,
                exact=True,
            )

            if (
                button.count() > 0
                and button.first.is_visible()
            ):
                button.first.click(timeout=5_000)
                page.wait_for_timeout(1_000)
                return

        except Exception:
            pass


def open_ticket_drawer(page: Page) -> None:
    """Open the Cineplex ticket drawer."""

    candidates = [
        page.get_by_role(
            "button",
            name="Get Tickets",
            exact=True,
        ),
        page.get_by_role(
            "link",
            name="Get Tickets",
            exact=True,
        ),
        page.get_by_text(
            "Get Tickets",
            exact=True,
        ),
    ]

    for candidate in candidates:
        if click_first_visible(
            candidate,
            "Get Tickets",
        ):
            page.wait_for_timeout(6_000)
            return

    raise RuntimeError(
        "Could not open the ticket drawer."
    )


def select_langley(page: Page) -> None:
    """Select Cineplex Cinemas Langley."""

    theatre_candidates = [
        page.get_by_text(
            "Theatres",
            exact=True,
        ),
        page.get_by_text(
            "Theatre",
            exact=True,
        ),
        page.get_by_role(
            "button",
            name="Theatres",
            exact=False,
        ),
        page.get_by_role(
            "button",
            name="Theatre",
            exact=False,
        ),
        page.locator(
            "button, [role='button']"
        ).filter(
            has_text="Theatre"
        ),
    ]

    theatre_selector_opened = False

    for candidate in theatre_candidates:
        if click_first_visible(
            candidate,
            "theatre selector",
        ):
            page.wait_for_timeout(3_000)
            theatre_selector_opened = True
            break

    if not theatre_selector_opened:
        raise RuntimeError(
            "Could not open theatre selector."
        )

    search_candidates = [
        page.get_by_placeholder(
            "Search",
            exact=False,
        ),
        page.get_by_placeholder(
            "city",
            exact=False,
        ),
        page.get_by_placeholder(
            "theatre",
            exact=False,
        ),
        page.get_by_role("searchbox"),
        page.locator("input[type='search']"),
    ]

    search_field = None

    for candidate in search_candidates:
        for index in range(candidate.count()):
            field = candidate.nth(index)

            try:
                if field.is_visible():
                    search_field = field
                    break

            except Exception:
                pass

        if search_field is not None:
            break

    if search_field is None:
        raise RuntimeError(
            "Could not find theatre search input."
        )

    search_field.fill("Langley")
    page.wait_for_timeout(4_000)

    exact_results = page.get_by_text(
        THEATRE_NAME,
        exact=True,
    )

    if not click_first_visible(
        exact_results,
        THEATRE_NAME,
    ):
        partial_results = page.get_by_text(
            THEATRE_NAME,
            exact=False,
        )

        if not click_first_visible(
            partial_results,
            THEATRE_NAME,
        ):
            raise RuntimeError(
                "Could not select Langley theatre."
            )

    page.wait_for_timeout(7_000)
    print("Langley selected.")


def clean_api_headers(
    headers: dict[str, str],
) -> dict[str, str]:
    """
    Keep only headers needed when repeating Cineplex API
    requests.
    """

    allowed_headers = {
        "accept",
        "accept-language",
        "ocp-apim-subscription-key",
        "origin",
        "referer",
        "user-agent",
    }

    return {
        key: value
        for key, value in headers.items()
        if key.lower() in allowed_headers
    }


def api_get_json(
    api: APIRequestContext,
    url: str,
    headers: dict[str, str],
) -> Any:
    """Call a Cineplex API and parse its JSON response."""

    print(f"API GET: {url}")

    response = api.get(
        url,
        headers=headers,
        timeout=60_000,
    )

    print(f"API HTTP: {response.status}")

    if not response.ok:
        response_text = response.text()

        raise RuntimeError(
            f"API request failed: HTTP {response.status}. "
            f"{response_text[:500]}"
        )

    return response.json()


def extract_date_strings(
    value: Any,
) -> set[str]:
    """Recursively extract YYYY-MM-DD date strings."""

    results: set[str] = set()

    if isinstance(value, str):
        if re.fullmatch(
            r"\d{4}-\d{2}-\d{2}(?:T[^ ]+)?",
            value,
        ):
            results.add(value[:10])

    elif isinstance(value, list):
        for item in value:
            results.update(
                extract_date_strings(item)
            )

    elif isinstance(value, dict):
        for item in value.values():
            results.update(
                extract_date_strings(item)
            )

    return results


def extract_sessions(
    value: Any,
) -> list[dict[str, str]]:
    """Recursively extract showtime sessions from API JSON."""

    sessions: list[dict[str, str]] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            showtime_id = (
                item.get("vistaSessionId")
                or item.get("showtimeId")
                or item.get("sessionId")
            )

            if showtime_id:
                start_time = (
                    item.get("showStartDateTime")
                    or item.get("startDateTime")
                    or item.get("showTime")
                    or item.get("startTime")
                    or ""
                )

                sessions.append(
                    {
                        "showtime_id": str(showtime_id),
                        "start_time": str(start_time),
                    }
                )

            for child in item.values():
                walk(child)

        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)

    unique_sessions: dict[
        str,
        dict[str, str],
    ] = {}

    for session in sessions:
        unique_sessions[
            session["showtime_id"]
        ] = session

    return list(unique_sessions.values())


def build_seat_lookup(
    layout: Any,
) -> dict[str, str]:
    """
    Build a mapping from Cineplex internal seat ID
    to visible seat label such as H12.
    """

    lookup: dict[str, str] = {}

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            seat_id = item.get("id")

            label = (
                item.get("label")
                or item.get("seatLabel")
                or item.get("name")
            )

            if (
                seat_id is not None
                and isinstance(label, str)
            ):
                normalized = (
                    label.strip().upper()
                )

                if re.fullmatch(
                    r"[A-Z]+\d+",
                    normalized,
                ):
                    lookup[str(seat_id)] = normalized

            for child in item.values():
                walk(child)

        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(layout)

    return lookup


def find_preferred_pair(
    layout: Any,
    availability: Any,
) -> tuple[str, str] | None:
    """
    Find two adjacent available seats using the priority:
    H first, then I, then G.
    """

    seat_lookup = build_seat_lookup(layout)

    if not isinstance(availability, dict):
        return None

    statuses = availability.get(
        "seatAvailabilities",
        {},
    )

    if not isinstance(statuses, dict):
        return None

    available_labels: set[str] = set()

    for seat_id, status in statuses.items():
        if str(status).lower() != "available":
            continue

        label = seat_lookup.get(str(seat_id))

        if label:
            available_labels.add(label)

    preferred_available = sorted(
        label
        for label in available_labels
        if label[:1] in {"H", "I", "G"}
    )

    print(
        "Available preferred-area seats:",
        preferred_available,
    )

    for (
        row,
        first_number,
        last_number,
    ) in SEAT_PRIORITY:
        for number in range(
            first_number,
            last_number,
        ):
            seat_one = f"{row}{number}"
            seat_two = f"{row}{number + 1}"

            if (
                seat_one in available_labels
                and seat_two in available_labels
            ):
                return seat_one, seat_two

    return None


def check_showtime_seats(
    api: APIRequestContext,
    headers: dict[str, str],
    showtime_id: str,
) -> tuple[str, str] | None:
    """Download and check seats for one showtime."""

    base_url = (
        "https://apis.cineplex.com/prod/"
        f"ticketing/api/v1/theatre/{THEATRE_ID}/"
        f"showtime/{showtime_id}"
    )

    layout = api_get_json(
        api,
        f"{base_url}/seat-layout",
        headers,
    )

    availability = api_get_json(
        api,
        f"{base_url}/seat-availability",
        headers,
    )

    if isinstance(availability, dict):
        if (
            availability.get("isPostShowtime")
            is True
        ):
            print(
                "Skipping: showtime has already passed."
            )
            return None

        if (
            availability.get("isSoldOut")
            is True
        ):
            print(
                "Skipping: showtime is sold out."
            )
            return None

    return find_preferred_pair(
        layout,
        availability,
    )


def main() -> None:
    """Run the complete Langley IMAX 70mm seat check."""

    DEBUG_DIR.mkdir(exist_ok=True)

    print(
        "Starting Langley IMAX 70mm monitor test."
    )

    captured_headers: dict[str, str] | None = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                (
                    "--disable-blink-features="
                    "AutomationControlled"
                ),
            ],
        )

        context = browser.new_context(
            locale="en-CA",
            timezone_id="America/Vancouver",
            viewport={
                "width": 1440,
                "height": 1200,
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        def capture_request(request: Any) -> None:
            nonlocal captured_headers

            url = request.url.lower()

            is_cineplex_api = (
                "apis.cineplex.com" in url
            )

            is_useful_request = (
                "/showtimes?" in url
                or "/dates/bookable?" in url
            )

            if (
                is_cineplex_api
                and is_useful_request
            ):
                headers = clean_api_headers(
                    request.all_headers()
                )

                header_names = {
                    key.lower()
                    for key in headers
                }

                if (
                    "ocp-apim-subscription-key"
                    in header_names
                ):
                    captured_headers = headers

                    print(
                        "Captured authenticated "
                        "Cineplex API headers."
                    )

        page.on(
            "request",
            capture_request,
        )

        response = page.goto(
            MOVIE_URL,
            wait_until="domcontentloaded",
            timeout=90_000,
        )

        print(
            "Movie page HTTP:",
            response.status if response else "none",
        )

        page.wait_for_timeout(10_000)

        close_cookie_banner(page)
        open_ticket_drawer(page)
        select_langley(page)

        page.wait_for_timeout(8_000)

        page.screenshot(
            path=str(
                DEBUG_DIR
                / "langley-selected.png"
            ),
            full_page=True,
        )

        if captured_headers is None:
            raise RuntimeError(
                "Could not capture Cineplex API "
                "authentication headers."
            )

        print(
            "Authentication headers captured "
            "successfully."
        )

        dates_url = (
            "https://apis.cineplex.com/prod/"
            "cpx/theatrical/api/v1/dates/bookable?"
            + urlencode(
                {
                    "locationId": THEATRE_ID,
                    "experiences": "imax-70mm",
                }
            )
        )

        dates_payload = api_get_json(
            context.request,
            dates_url,
            captured_headers,
        )

        (
            DEBUG_DIR / "bookable-dates.json"
        ).write_text(
            json.dumps(
                dates_payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        dates = sorted(
            extract_date_strings(
                dates_payload
            )
        )

        print(
            f"Bookable dates found: {len(dates)}"
        )

        all_sessions: list[
            dict[str, str]
        ] = []

        for date_text in dates:
            year, month, day = date_text.split("-")

            cineplex_date = (
                f"{int(month)}/{int(day)}/{year}"
            )

            showtimes_url = (
                "https://apis.cineplex.com/prod/"
                "cpx/theatrical/api/v1/showtimes?"
                + urlencode(
                    {
                        "language": "en",
                        "locationId": THEATRE_ID,
                        "date": cineplex_date,
                        "filmId": FILM_ID,
                        "experiences": "imax-70mm",
                    }
                )
            )

            try:
                payload = api_get_json(
                    context.request,
                    showtimes_url,
                    captured_headers,
                )

            except Exception as exc:
                print(
                    f"Could not load {date_text}:",
                    type(exc).__name__,
                    str(exc),
                )
                continue

            sessions = extract_sessions(
                payload
            )

            print(
                f"{date_text}: "
                f"{len(sessions)} session(s)"
            )

            for session in sessions:
                session["date"] = date_text
                all_sessions.append(session)

        unique_sessions: dict[
            str,
            dict[str, str],
        ] = {
            item["showtime_id"]: item
            for item in all_sessions
        }

        final_sessions = sorted(
            unique_sessions.values(),
            key=lambda item: (
                item.get("date", ""),
                item.get("start_time", ""),
            ),
        )

        (
            DEBUG_DIR / "all-showtimes.json"
        ).write_text(
            json.dumps(
                final_sessions,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print("\nALL IMAX 70MM SHOWTIMES")

        for session in final_sessions:
            print(
                session.get("date", ""),
                session.get("start_time", ""),
                (
                    "showtimeId="
                    f'{session["showtime_id"]}'
                ),
            )

        print(
            "\nTotal unique showtimes:",
            len(final_sessions),
        )

        if not final_sessions:
            raise RuntimeError(
                "No Langley IMAX 70mm "
                "showtimes were discovered."
            )

        print("\nSTARTING SEAT CHECKS")

        matches: list[
            dict[str, str]
        ] = []

        failed_checks: list[
            dict[str, str]
        ] = []

        for index, session in enumerate(
            final_sessions,
            start=1,
        ):
            showtime_id = session[
                "showtime_id"
            ]

            date_text = session.get(
                "date",
                "",
            )

            start_time = session.get(
                "start_time",
                "",
            )

            print(
                f"\n[{index}/{len(final_sessions)}] "
                f"Checking {date_text} {start_time} "
                f"showtimeId={showtime_id}"
            )

            try:
                pair = check_showtime_seats(
                    context.request,
                    captured_headers,
                    showtime_id,
                )

            except Exception as exc:
                print(
                    "CHECK FAILED:",
                    type(exc).__name__,
                    str(exc),
                )

                failed_checks.append(
                    {
                        "date": date_text,
                        "start_time": start_time,
                        "showtime_id": showtime_id,
                        "error": str(exc),
                    }
                )

                continue

            if pair is None:
                print("NO MATCH")
                continue

            print(
                f"MATCH FOUND: "
                f"{pair[0]} + {pair[1]}"
            )

            matches.append(
                {
                    "date": date_text,
                    "start_time": start_time,
                    "showtime_id": showtime_id,
                    "seat_one": pair[0],
                    "seat_two": pair[1],
                }
            )

        (
            DEBUG_DIR / "seat-matches.json"
        ).write_text(
            json.dumps(
                matches,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        (
            DEBUG_DIR
            / "failed-seat-checks.json"
        ).write_text(
            json.dumps(
                failed_checks,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print("\nSEAT CHECK SUMMARY")

        print(
            "Showtimes checked:",
            len(final_sessions),
        )

        print(
            "Preferred pairs found:",
            len(matches),
        )

        print(
            "Failed checks:",
            len(failed_checks),
        )

        if matches:
            print(
                "\nAVAILABLE PREFERRED SEATS"
            )

            for match in matches:
                print(
                    match["date"],
                    match["start_time"],
                    (
                        f'{match["seat_one"]} + '
                        f'{match["seat_two"]}'
                    ),
                    (
                        "showtimeId="
                        f'{match["showtime_id"]}'
                    ),
                )

        else:
            print(
                "No preferred adjacent seats "
                "are currently available."
            )

        context.close()
        browser.close()

    print(
        "All-showtimes and seat checking "
        "completed successfully."
    )


if __name__ == "__main__":
    main()
