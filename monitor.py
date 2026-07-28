import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import APIRequestContext, Page, sync_playwright


MOVIE_URL = (
    "https://www.cineplex.com/movie/"
    "imax70-the-odyssey-the-imax-experience-in-7"
)

THEATRE_ID = "1405"
THEATRE_NAME = "Cineplex Cinemas Langley"
FILM_ID = "37617"

DEBUG_DIR = Path("debug")


def click_first_visible(locator, description: str) -> bool:
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
            print(f"{description} click attempt failed: {exc}")

    return False


def close_cookie_banner(page: Page) -> None:
    for label in ["OK", "Accept All", "Accept", "I Accept", "Agree"]:
        try:
            button = page.get_by_role(
                "button",
                name=label,
                exact=True,
            )

            if button.count() and button.first.is_visible():
                button.first.click(timeout=5_000)
                page.wait_for_timeout(1_000)
                return
        except Exception:
            pass


def open_ticket_drawer(page: Page) -> None:
    candidates = [
        page.get_by_role("button", name="Get Tickets", exact=True),
        page.get_by_role("link", name="Get Tickets", exact=True),
        page.get_by_text("Get Tickets", exact=True),
    ]

    for candidate in candidates:
        if click_first_visible(candidate, "Get Tickets"):
            page.wait_for_timeout(6_000)
            return

    raise RuntimeError("Could not open the ticket drawer.")


def select_langley(page: Page) -> None:
    theatre_candidates = [
        page.get_by_text("Theatres", exact=True),
        page.get_by_text("Theatre", exact=True),
        page.get_by_role("button", name="Theatres", exact=False),
        page.get_by_role("button", name="Theatre", exact=False),
        page.locator("button, [role='button']").filter(
            has_text="Theatre"
        ),
    ]

    for candidate in theatre_candidates:
        if click_first_visible(candidate, "theatre selector"):
            page.wait_for_timeout(3_000)
            break
    else:
        raise RuntimeError("Could not open theatre selector.")

    search_candidates = [
        page.get_by_placeholder("Search", exact=False),
        page.get_by_placeholder("city", exact=False),
        page.get_by_placeholder("theatre", exact=False),
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
        raise RuntimeError("Could not find theatre search input.")

    search_field.fill("Langley")
    page.wait_for_timeout(4_000)

    results = page.get_by_text(THEATRE_NAME, exact=True)

    if not click_first_visible(results, THEATRE_NAME):
        results = page.get_by_text(THEATRE_NAME, exact=False)

        if not click_first_visible(results, THEATRE_NAME):
            raise RuntimeError("Could not select Langley theatre.")

    page.wait_for_timeout(7_000)
    print("Langley selected.")


def clean_api_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {
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
        if key.lower() in allowed
    }


def api_get_json(
    api: APIRequestContext,
    url: str,
    headers: dict[str, str],
) -> Any:
    print(f"API GET: {url}")

    response = api.get(
        url,
        headers=headers,
        timeout=60_000,
    )

    print(f"API HTTP: {response.status}")

    if not response.ok:
        raise RuntimeError(
            f"API request failed: HTTP {response.status} "
            f"{response.text()[:500]}"
        )

    return response.json()


def extract_date_strings(value: Any) -> set[str]:
    results: set[str] = set()

    if isinstance(value, str):
        if re.fullmatch(
            r"\d{4}-\d{2}-\d{2}(?:T[^ ]+)?",
            value,
        ):
            results.add(value[:10])

    elif isinstance(value, list):
        for item in value:
            results.update(extract_date_strings(item))

    elif isinstance(value, dict):
        for item in value.values():
            results.update(extract_date_strings(item))

    return results


def extract_sessions(value: Any) -> list[dict[str, str]]:
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

    unique: dict[str, dict[str, str]] = {}

    for session in sessions:
        unique[session["showtime_id"]] = session

    return list(unique.values())


def main() -> None:
    DEBUG_DIR.mkdir(exist_ok=True)

    captured_headers: dict[str, str] | None = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            locale="en-CA",
            timezone_id="America/Vancouver",
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        def capture_request(request) -> None:
            nonlocal captured_headers

            url = request.url.lower()

            if (
                "apis.cineplex.com" in url
                and (
                    "/showtimes?" in url
                    or "/dates/bookable?" in url
                )
            ):
                headers = clean_api_headers(
                    request.all_headers()
                )

                if "ocp-apim-subscription-key" in {
                    key.lower() for key in headers
                }:
                    captured_headers = headers
                    print(
                        "Captured authenticated Cineplex API headers."
                    )

        page.on("request", capture_request)

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

        if captured_headers is None:
            raise RuntimeError(
                "Could not capture Cineplex API authentication headers."
            )

        print("Authentication headers captured successfully.")

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

        (DEBUG_DIR / "bookable-dates.json").write_text(
            json.dumps(
                dates_payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        dates = sorted(extract_date_strings(dates_payload))

        print(f"Bookable dates found: {len(dates)}")

        all_sessions: list[dict[str, str]] = []

        for date_text in dates:
            year, month, day = date_text.split("-")
            cineplex_date = f"{int(month)}/{int(day)}/{year}"

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
                print(f"Could not load {date_text}: {exc}")
                continue

            sessions = extract_sessions(payload)

            print(
                f"{date_text}: "
                f"{len(sessions)} session(s)"
            )

            for session in sessions:
                session["date"] = date_text
                all_sessions.append(session)

        unique_sessions: dict[str, dict[str, str]] = {
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

        (DEBUG_DIR / "all-showtimes.json").write_text(
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
                f"showtimeId={session['showtime_id']}",
            )

        print(
            f"\nTotal unique showtimes: "
            f"{len(final_sessions)}"
        )

        context.close()
        browser.close()

    if not final_sessions:
        raise RuntimeError(
            "No Langley IMAX 70mm showtimes were discovered."
        )

    print("All-showtimes discovery completed successfully.")


if __name__ == "__main__":
    main()
