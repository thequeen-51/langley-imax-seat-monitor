from typing import Any

from playwright.sync_api import Response, sync_playwright


THEATRE_ID = "1405"
SHOWTIME_ID = "534854"

PREVIEW_URL = (
    "https://www.cineplex.com/en/ticketing/preview"
    f"?theatreId={THEATRE_ID}"
    f"&showtimeId={SHOWTIME_ID}"
    "&dbox=false"
)

SEAT_PRIORITY = [
    ("H", 10, 15),
    ("I", 10, 15),
    ("G", 10, 15),
]


def build_seat_lookup(
    layout: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Map Cineplex seat IDs to labels such as H12."""

    lookup: dict[str, dict[str, Any]] = {}

    for area_name in [
        "standardSeats",
        "dboxSeats",
        "balconySeats",
    ]:
        area = layout.get(area_name)

        if not isinstance(area, dict):
            continue

        for row in area.get("rows", []):
            for seat in row.get("seats", []):
                seat_id = seat.get("id")

                if seat_id:
                    lookup[str(seat_id)] = seat

    return lookup


def find_preferred_pair(
    layout: dict[str, Any],
    availability: dict[str, Any],
) -> tuple[str, str] | None:
    lookup = build_seat_lookup(layout)

    statuses = availability.get(
        "seatAvailabilities",
        {},
    )

    available_labels: set[str] = set()

    for seat_id, status in statuses.items():
        if str(status).lower() != "available":
            continue

        seat = lookup.get(str(seat_id))

        if not seat:
            continue

        if seat.get("type") != "Standard":
            continue

        label = str(seat.get("label", "")).upper()

        if label:
            available_labels.add(label)

    print(
        "Available preferred-area seats:",
        sorted(
            seat
            for seat in available_labels
            if seat[:1] in {"H", "I", "G"}
        ),
    )

    # Strict priority: H, then I, then G.
    for row, first_seat, last_seat in SEAT_PRIORITY:
        for number in range(first_seat, last_seat):
            seat_one = f"{row}{number}"
            seat_two = f"{row}{number + 1}"

            if (
                seat_one in available_labels
                and seat_two in available_labels
            ):
                return seat_one, seat_two

    return None


def main() -> None:
    print("Starting real Cineplex seat parser test")
    print(f"Preview URL: {PREVIEW_URL}")

    seat_layout: dict[str, Any] | None = None
    seat_availability: dict[str, Any] | None = None

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

        def capture_response(response: Response) -> None:
            nonlocal seat_layout
            nonlocal seat_availability

            url = response.url.lower()

            try:
                if "/seat-layout" in url:
                    print(
                        "Captured seat-layout:",
                        response.status,
                    )
                    seat_layout = response.json()

                elif "/seat-availability" in url:
                    print(
                        "Captured seat-availability:",
                        response.status,
                    )
                    seat_availability = response.json()

            except Exception as exc:
                print(
                    "Could not parse response:",
                    type(exc).__name__,
                    exc,
                )

        page.on("response", capture_response)

        response = page.goto(
            PREVIEW_URL,
            wait_until="domcontentloaded",
            timeout=90_000,
        )

        print(
            "Preview page HTTP:",
            response.status if response else "none",
        )

        page.wait_for_timeout(15_000)

        page.screenshot(
            path="seat-preview-test.png",
            full_page=True,
        )

        context.close()
        browser.close()

    if seat_layout is None:
        raise RuntimeError(
            "The seat-layout response was not captured."
        )

    if seat_availability is None:
        raise RuntimeError(
            "The seat-availability response was not captured."
        )

    print(
        "Seat availability entries:",
        len(
            seat_availability.get(
                "seatAvailabilities",
                {},
            )
        ),
    )

    print(
        "Sold out:",
        seat_availability.get("isSoldOut"),
    )

    pair = find_preferred_pair(
        seat_layout,
        seat_availability,
    )

    if pair:
        print(
            f"MATCH FOUND: {pair[0]} + {pair[1]}"
        )
    else:
        print(
            "NO MATCH: No preferred adjacent pair "
            "is currently available."
        )

    print("Seat parser test finished successfully.")


if __name__ == "__main__":
    main()
