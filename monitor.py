from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


MOVIE_URL = (
    "https://www.cineplex.com/movie/"
    "imax70-the-odyssey-the-imax-experience-in-7"
)


def save_page(page: Page, folder: Path, name: str) -> None:
    """Save screenshot, HTML, visible text and current URL."""

    try:
        page.screenshot(
            path=str(folder / f"{name}.png"),
            full_page=True,
        )
    except Exception as exc:
        print(f"Could not save screenshot {name}: {exc}")

    try:
        (folder / f"{name}.html").write_text(
            page.content(),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"Could not save HTML {name}: {exc}")

    try:
        text = page.locator("body").inner_text(timeout=15_000)
    except Exception:
        text = ""

    (folder / f"{name}.txt").write_text(
        f"URL: {page.url}\n\n{text}",
        encoding="utf-8",
    )


def close_cookie_banner(page: Page) -> None:
    """Close the cookie banner visible at the bottom of the page."""

    possible_buttons = [
        "OK",
        "Accept",
        "Accept All",
        "I Accept",
        "Agree",
        "Got it",
    ]

    for label in possible_buttons:
        try:
            button = page.get_by_role(
                "button",
                name=label,
                exact=True,
            )

            if button.count() and button.first.is_visible():
                print(f"Closing cookie banner with: {label}")
                button.first.click(timeout=5_000)
                page.wait_for_timeout(1_500)
                return
        except Exception:
            pass

    print("No cookie button was closed.")


def describe_get_tickets(page: Page) -> None:
    """Print details about every element containing Get Tickets."""

    matches = page.get_by_text("Get Tickets", exact=True)
    print(f"Exact Get Tickets matches: {matches.count()}")

    for index in range(matches.count()):
        item = matches.nth(index)

        try:
            info: dict[str, Any] = item.evaluate(
                """
                element => ({
                    tag: element.tagName,
                    text: element.innerText,
                    href: element.href || null,
                    role: element.getAttribute('role'),
                    className: element.className,
                    outerHTML: element.outerHTML
                })
                """
            )

            print(f"GET TICKETS ELEMENT #{index + 1}")
            print(info)
            print(f"Visible: {item.is_visible()}")

        except Exception as exc:
            print(f"Could not inspect match #{index + 1}: {exc}")


def click_get_tickets(page: Page) -> None:
    """Click the visible Get Tickets control using robust fallbacks."""

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

    for group_number, candidate in enumerate(candidates, start=1):
        count = candidate.count()
        print(f"Candidate group {group_number}: {count} matches")

        for index in range(count):
            item = candidate.nth(index)

            try:
                if not item.is_visible():
                    continue

                print(
                    f"Using candidate group {group_number}, "
                    f"item {index + 1}"
                )

                item.scroll_into_view_if_needed()
                page.wait_for_timeout(1_000)

                box = item.bounding_box()
                print(f"Bounding box: {box}")

                # First attempt: normal Playwright click.
                try:
                    item.click(timeout=10_000)
                    print("Normal Playwright click completed.")
                    return
                except Exception as exc:
                    print(
                        "Normal click failed:",
                        type(exc).__name__,
                        str(exc),
                    )

                # Second attempt: click the centre with the mouse.
                if box:
                    page.mouse.click(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
                    print("Mouse-coordinate click completed.")
                    return

                # Final attempt: dispatch the browser click event.
                item.evaluate("element => element.click()")
                print("JavaScript click completed.")
                return

            except Exception as exc:
                print(
                    f"Candidate item failed: "
                    f"{type(exc).__name__}: {exc}"
                )

    raise RuntimeError("No visible Get Tickets control could be clicked.")


def main() -> None:
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)

    print("Starting Cineplex Get Tickets investigation")
    print(f"Movie URL: {MOVIE_URL}")

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

        page.on(
            "console",
            lambda message: print(
                f"BROWSER CONSOLE [{message.type}]: {message.text}"
            ),
        )

        page.on(
            "dialog",
            lambda dialog: (
                print(
                    f"BROWSER DIALOG: "
                    f"{dialog.type}: {dialog.message}"
                ),
                dialog.accept(),
            ),
        )

        def record_response(response) -> None:
            url = response.url.lower()

            important_words = [
                "showtime",
                "performance",
                "seat",
                "ticket",
                "booking",
                "schedule",
                "theatre",
            ]

            if any(word in url for word in important_words):
                print(
                    f"NETWORK RESPONSE {response.status}: "
                    f"{response.url}"
                )

        page.on("response", record_response)

        opened_pages: list[Page] = []

        def record_new_page(new_page: Page) -> None:
            print("NEW PAGE OR POPUP DETECTED")
            opened_pages.append(new_page)

        context.on("page", record_new_page)

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
            page.wait_for_timeout(2_000)

            print(f"Before-click URL: {page.url}")
            print(f"Before-click title: {page.title()}")

            save_page(
                page,
                debug_dir,
                "01-before-click",
            )

            describe_get_tickets(page)
            click_get_tickets(page)

            print("Click issued. Waiting for website response...")
            page.wait_for_timeout(15_000)

            print(f"Original page URL after click: {page.url}")
            print(f"Number of browser pages: {len(context.pages)}")

            for index, open_page in enumerate(
                context.pages,
                start=1,
            ):
                try:
                    open_page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=30_000,
                    )
                except Exception:
                    pass

                print(
                    f"PAGE #{index}: "
                    f"title={open_page.title()!r}, "
                    f"url={open_page.url}"
                )

                save_page(
                    open_page,
                    debug_dir,
                    f"02-result-page-{index}",
                )

            print("Investigation finished successfully.")

        except Exception as exc:
            print(
                f"INVESTIGATION FAILED: "
                f"{type(exc).__name__}: {exc}"
            )

            try:
                save_page(
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
