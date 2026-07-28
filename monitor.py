from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


MOVIE_URL = (
    "https://www.cineplex.com/movie/"
    "imax70-the-odyssey-the-imax-experience-in-7"
)


def save_debug(page: Page, debug_dir: Path, name: str) -> None:
    """Save screenshot, HTML and visible page text."""

    page.screenshot(
        path=str(debug_dir / f"{name}.png"),
        full_page=True,
    )

    (debug_dir / f"{name}.html").write_text(
        page.content(),
        encoding="utf-8",
    )

    try:
        body_text = page.locator("body").inner_text(timeout=15_000)
    except Exception:
        body_text = ""

    (debug_dir / f"{name}.txt").write_text(
        body_text,
        encoding="utf-8",
    )


def close_popups(page: Page) -> None:
    """Close common cookie/privacy popups when present."""

    labels = [
        "Accept All",
        "Accept",
        "I Accept",
        "Agree",
        "Got it",
        "OK",
    ]

    for label in labels:
        try:
            button = page.get_by_role(
                "button",
                name=label,
                exact=False,
            )

            if button.count() > 0 and button.first.is_visible():
                button.first.click(timeout=3_000)
                print(f"Closed popup: {label}")
                page.wait_for_timeout(1_500)
                return
        except Exception:
            pass


def print_links_and_buttons(page: Page) -> None:
    """Print useful page controls to the Actions log."""

    print("\nVISIBLE BUTTONS:")

    buttons = page.get_by_role("button")

    for index in range(min(buttons.count(), 50)):
        try:
            button = buttons.nth(index)

            if not button.is_visible():
                continue

            text = button.inner_text().strip()

            if text:
                print(f"BUTTON: {text}")
        except Exception:
            pass

    print("\nVISIBLE LINKS:")

    links = page.locator("a")

    for index in range(min(links.count(), 100)):
        try:
            link = links.nth(index)

            if not link.is_visible():
                continue

            text = link.inner_text().strip()
            href = link.get_attribute("href")

            if text or href:
                absolute_href = (
                    urljoin(page.url, href)
                    if href
                    else ""
                )

                print(
                    f"LINK: {text!r} -> {absolute_href}"
                )
        except Exception:
            pass


def click_get_tickets(page: Page) -> bool:
    """Try several robust ways to click Get Tickets."""

    candidates = [
        page.get_by_role(
            "button",
            name="Get Tickets",
            exact=False,
        ),
        page.get_by_role(
            "link",
            name="Get Tickets",
            exact=False,
        ),
        page.get_by_text(
            "Get Tickets",
            exact=True,
        ),
    ]

    for candidate in candidates:
        try:
            count = candidate.count()

            print(
                "Get Tickets candidate count:",
                count,
            )

            for index in range(count):
                item = candidate.nth(index)

                if not item.is_visible():
                    continue

                print(
                    f"Clicking visible Get Tickets "
                    f"candidate #{index + 1}"
                )

                item.scroll_into_view_if_needed()
                page.wait_for_timeout(500)

                try:
                    with page.expect_navigation(
                        wait_until="domcontentloaded",
                        timeout=20_000,
                    ):
                        item.click(timeout=10_000)
                except PlaywrightTimeoutError:
                    # Many modern websites update without a traditional
                    # browser navigation event.
                    item.click(
                        timeout=10_000,
                        force=True,
                    )

                return True

        except Exception as exc:
            print(
                "Candidate click error:",
                type(exc).__name__,
                str(exc),
            )

    return False


def main() -> None:
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)

    print("Starting Odyssey IMAX 70mm ticket-page test")
    print(f"Movie URL: {MOVIE_URL}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1200,
            },
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

        # Record network responses that may reveal the current
        # showtime or ticket API.
        def log_response(response) -> None:
            url = response.url.lower()

            keywords = [
                "showtime",
                "performance",
                "schedule",
                "ticket",
                "seat",
                "theatre",
                "movie",
            ]

            if any(keyword in url for keyword in keywords):
                print(
                    f"NETWORK {response.status}: "
                    f"{response.url}"
                )

        page.on("response", log_response)

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
            close_popups(page)

            print(f"Initial title: {page.title()}")
            print(f"Initial URL: {page.url}")

            save_debug(
                page,
                debug_dir,
                "01-movie-page",
            )

            print_links_and_buttons(page)

            clicked = click_get_tickets(page)

            print(f"Get Tickets clicked: {clicked}")

            if not clicked:
                raise RuntimeError(
                    "Could not find a visible Get Tickets control."
                )

            page.wait_for_timeout(12_000)

            print(f"After-click title: {page.title()}")
            print(f"After-click URL: {page.url}")

            close_popups(page)

            save_debug(
                page,
                debug_dir,
                "02-after-get-tickets",
            )

            print_links_and_buttons(page)

            print(
                "SUCCESS: Ticket flow opened. "
                "Review the second screenshot and Actions log."
            )

        except Exception as exc:
            print(
                f"TEST FAILED: "
                f"{type(exc).__name__}: {exc}"
            )

            try:
                save_debug(
                    page,
                    debug_dir,
                    "error",
                )
            except Exception:
                pass

            raise

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
