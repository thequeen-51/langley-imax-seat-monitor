from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, sync_playwright


MOVIE_URL = (
    "https://www.cineplex.com/movie/"
    "imax70-the-odyssey-the-imax-experience-in-7"
)

TARGET_THEATRE = "Cineplex Cinemas Langley"


def save_page(page: Page, folder: Path, name: str) -> None:
    """Save screenshot, HTML, visible text and URL."""

    try:
        page.screenshot(
            path=str(folder / f"{name}.png"),
            full_page=True,
        )
    except Exception as exc:
        print(f"Screenshot failed for {name}: {exc}")

    try:
        html = page.content()
        (folder / f"{name}.html").write_text(
            html,
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"HTML save failed for {name}: {exc}")

    try:
        text = page.locator("body").inner_text(timeout=15_000)
    except Exception:
        text = ""

    (folder / f"{name}.txt").write_text(
        f"URL: {page.url}\n\n{text}",
        encoding="utf-8",
    )


def click_first_visible(locator: Locator, label: str) -> bool:
    for index in range(locator.count()):
        item = locator.nth(index)

        try:
            if not item.is_visible():
                continue

            print(f"Clicking {label} candidate #{index + 1}")
            item.scroll_into_view_if_needed()
            item.click(timeout=10_000)
            return True

        except Exception as exc:
            print(
                f"{label} click failed: "
                f"{type(exc).__name__}: {exc}"
            )

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
                print(f"Closed cookie banner: {label}")
                page.wait_for_timeout(1_500)
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

    opened = False

    for candidate in theatre_candidates:
        if click_first_visible(candidate, "theatre selector"):
            opened = True
            page.wait_for_timeout(3_000)
            break

    if not opened:
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
            item = candidate.nth(index)

            try:
                if item.is_visible():
                    search_field = item
                    break
            except Exception:
                pass

        if search_field is not None:
            break

    if search_field is None:
        raise RuntimeError("Could not find theatre search field.")

    search_field.fill("Langley")
    page.wait_for_timeout(4_000)

    results = page.get_by_text(TARGET_THEATRE, exact=True)

    if not click_first_visible(results, TARGET_THEATRE):
        results = page.get_by_text(TARGET_THEATRE, exact=False)

        if not click_first_visible(results, TARGET_THEATRE):
            raise RuntimeError("Could not select Langley theatre.")

    page.wait_for_timeout(7_000)

    body_text = page.locator("body").inner_text(timeout=15_000)

    if TARGET_THEATRE.lower() not in body_text.lower():
        raise RuntimeError("Langley selection could not be confirmed.")

    print("Langley theatre selected successfully.")


def find_showtime_buttons(page: Page) -> list[Locator]:
    """Return all visible buttons whose aria-label starts with Book show at."""

    locator = page.locator(
        'button[aria-label^="Book show at"]'
    )

    buttons: list[Locator] = []

    print(f"Book-show button count: {locator.count()}")

    for index in range(locator.count()):
        item = locator.nth(index)

        try:
            if not item.is_visible():
                continue

            label = item.get_attribute("aria-label")
            text = item.inner_text().strip()

            print(
                f"SHOWTIME #{len(buttons) + 1}: "
                f"text={text!r}, aria-label={label!r}"
            )

            buttons.append(item)

        except Exception as exc:
            print(f"Could not inspect showtime #{index + 1}: {exc}")

    return buttons


def save_network_log(lines: list[str], folder: Path) -> None:
    (folder / "network-log.txt").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> None:
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)

    network_log: list[str] = []

    print("Starting Cineplex showtime-click investigation")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            locale="en-CA",
            timezone_id="America/Vancouver",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        def record_response(response) -> None:
            url_lower = response.url.lower()

            keywords = [
                "seat",
                "showtime",
                "performance",
                "booking",
                "ticket",
                "checkout",
                "reservation",
                "schedule",
            ]

            if any(word in url_lower for word in keywords):
                line = (
                    f"{response.status} "
                    f"{response.request.method} "
                    f"{response.url}"
                )
                print(f"NETWORK: {line}")
                network_log.append(line)

        page.on("response", record_response)

        try:
            response = page.goto(
                MOVIE_URL,
                wait_until="domcontentloaded",
                timeout=90_000,
            )

            print(
                "Initial HTTP status:",
                response.status if response else "none",
            )

            page.wait_for_timeout(10_000)
            close_cookie_banner(page)

            open_ticket_drawer(page)
            select_langley(page)

            save_page(
                page,
                debug_dir,
                "01-langley-showtimes",
            )

            showtimes = find_showtime_buttons(page)

            if not showtimes:
                raise RuntimeError(
                    "No bookable showtime buttons were found."
                )

            first_showtime = showtimes[0]
            selected_time = first_showtime.inner_text().strip()

            print(f"Testing first available showtime: {selected_time}")

            pages_before = len(context.pages)
            old_url = page.url

            first_showtime.scroll_into_view_if_needed()
            first_showtime.click(timeout=15_000)

            print("Showtime click issued.")
            page.wait_for_timeout(15_000)

            print(f"Original URL before click: {old_url}")
            print(f"Original page URL now: {page.url}")
            print(f"Browser pages before click: {pages_before}")
            print(f"Browser pages after click: {len(context.pages)}")

            for index, current_page in enumerate(
                context.pages,
                start=1,
            ):
                try:
                    current_page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=30_000,
                    )
                except Exception:
                    pass

                title = ""

                try:
                    title = current_page.title()
                except Exception:
                    pass

                print(
                    f"PAGE #{index}: "
                    f"title={title!r}, "
                    f"url={current_page.url}"
                )

                save_page(
                    current_page,
                    debug_dir,
                    f"02-after-showtime-page-{index}",
                )

            save_network_log(network_log, debug_dir)

            print("Showtime-click investigation finished.")

        except Exception as exc:
            print(
                f"SHOWTIME CLICK FAILED: "
                f"{type(exc).__name__}: {exc}"
            )

            try:
                save_page(page, debug_dir, "error")
                save_network_log(network_log, debug_dir)
            except Exception:
                pass

            raise

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
