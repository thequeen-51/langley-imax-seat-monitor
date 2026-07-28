from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright


MOVIE_URL = (
    "https://www.cineplex.com/movie/"
    "imax70-the-odyssey-the-imax-experience-in-7"
)

TARGET_THEATRE = "Cineplex Cinemas Langley"


def save_page(page: Page, folder: Path, name: str) -> None:
    """Save screenshot, page text and HTML for diagnosis."""

    page.screenshot(
        path=str(folder / f"{name}.png"),
        full_page=True,
    )

    try:
        body_text = page.locator("body").inner_text(timeout=15_000)
    except Exception:
        body_text = ""

    (folder / f"{name}.txt").write_text(
        f"URL: {page.url}\n\n{body_text}",
        encoding="utf-8",
    )

    (folder / f"{name}.html").write_text(
        page.content(),
        encoding="utf-8",
    )


def click_first_visible(locator: Locator, description: str) -> bool:
    """Click the first visible item in a locator collection."""

    print(f"{description}: {locator.count()} candidate(s)")

    for index in range(locator.count()):
        item = locator.nth(index)

        try:
            if not item.is_visible():
                continue

            print(f"Clicking {description} candidate #{index + 1}")
            item.scroll_into_view_if_needed()
            item.click(timeout=10_000)
            return True

        except Exception as exc:
            print(
                f"{description} candidate #{index + 1} failed: "
                f"{type(exc).__name__}: {exc}"
            )

    return False


def close_cookie_banner(page: Page) -> None:
    """Close the cookie banner when it is present."""

    for label in ["OK", "Accept All", "Accept", "I Accept", "Agree"]:
        try:
            button = page.get_by_role("button", name=label, exact=True)

            if button.count() and button.first.is_visible():
                button.first.click(timeout=5_000)
                print(f"Closed cookie banner using: {label}")
                page.wait_for_timeout(1_500)
                return
        except Exception:
            pass


def open_ticket_drawer(page: Page) -> None:
    """Open the Get Tickets drawer."""

    candidates = [
        page.get_by_role("button", name="Get Tickets", exact=True),
        page.get_by_role("link", name="Get Tickets", exact=True),
        page.get_by_text("Get Tickets", exact=True),
    ]

    for candidate in candidates:
        if click_first_visible(candidate, "Get Tickets"):
            page.wait_for_timeout(7_000)
            return

    raise RuntimeError("Could not click Get Tickets.")


def print_visible_inputs(page: Page) -> None:
    """Print visible input details to the Actions log."""

    inputs = page.locator("input")

    print(f"Total input elements: {inputs.count()}")

    for index in range(inputs.count()):
        item = inputs.nth(index)

        try:
            if not item.is_visible():
                continue

            print(
                "VISIBLE INPUT:",
                {
                    "index": index,
                    "type": item.get_attribute("type"),
                    "name": item.get_attribute("name"),
                    "placeholder": item.get_attribute("placeholder"),
                    "aria-label": item.get_attribute("aria-label"),
                    "value": item.input_value(),
                },
            )
        except Exception as exc:
            print(f"Could not inspect input #{index}: {exc}")


def open_theatre_selector(page: Page) -> None:
    """Open the theatre/location selector in the ticket drawer."""

    candidates = [
        page.get_by_text("Theatres", exact=True),
        page.get_by_text("Theatre", exact=True),
        page.get_by_role("button", name="Theatres", exact=False),
        page.get_by_role("button", name="Theatre", exact=False),
        page.locator(
            "button, [role='button']"
        ).filter(has_text="Theatre"),
    ]

    for candidate in candidates:
        if click_first_visible(candidate, "theatre selector"):
            page.wait_for_timeout(3_000)
            return

    # Fallback: inspect elements that contain the word THEATRE.
    matches = page.get_by_text("THEATRE", exact=False)

    print(f"Fallback THEATRE text matches: {matches.count()}")

    for index in range(matches.count()):
        item = matches.nth(index)

        try:
            if not item.is_visible():
                continue

            info = item.evaluate(
                """
                element => ({
                    tag: element.tagName,
                    text: element.innerText,
                    outerHTML: element.outerHTML
                })
                """
            )

            print(f"THEATRE element #{index + 1}: {info}")

            # Click the closest interactive parent.
            item.evaluate(
                """
                element => {
                    const clickable = element.closest(
                        'button, a, [role="button"]'
                    );
                    if (clickable) {
                        clickable.click();
                    } else {
                        element.click();
                    }
                }
                """
            )

            print("Clicked theatre selector using JavaScript fallback.")
            page.wait_for_timeout(3_000)
            return

        except Exception as exc:
            print(
                f"THEATRE fallback #{index + 1} failed: "
                f"{type(exc).__name__}: {exc}"
            )

    raise RuntimeError("Could not open the theatre selector.")


def search_for_langley(page: Page) -> None:
    """Find the theatre search input and search for Langley."""

    print_visible_inputs(page)

    search_candidates = [
        page.get_by_placeholder("Search", exact=False),
        page.get_by_placeholder("city", exact=False),
        page.get_by_placeholder("theatre", exact=False),
        page.get_by_role("searchbox"),
        page.locator("input[type='search']"),
        page.locator("input").filter(visible=True),
    ]

    for candidate in search_candidates:
        for index in range(candidate.count()):
            field = candidate.nth(index)

            try:
                if not field.is_visible():
                    continue

                field_type = field.get_attribute("type")

                if field_type in {"hidden", "checkbox", "radio"}:
                    continue

                print(
                    f"Trying search input #{index + 1}, "
                    f"placeholder={field.get_attribute('placeholder')!r}"
                )

                field.click(timeout=5_000)
                field.fill("Langley", timeout=5_000)
                page.wait_for_timeout(4_000)

                if "langley" in field.input_value().lower():
                    print("Successfully entered Langley.")
                    return

            except Exception as exc:
                print(
                    f"Search input attempt failed: "
                    f"{type(exc).__name__}: {exc}"
                )

    raise RuntimeError("Could not find a usable theatre search input.")


def choose_langley(page: Page) -> None:
    """Select Cineplex Cinemas Langley from the visible results."""

    exact = page.get_by_text(TARGET_THEATRE, exact=True)

    if click_first_visible(exact, TARGET_THEATRE):
        page.wait_for_timeout(7_000)
        return

    partial = page.get_by_text(TARGET_THEATRE, exact=False)

    if click_first_visible(partial, f"partial {TARGET_THEATRE}"):
        page.wait_for_timeout(7_000)
        return

    # Fallback for cards whose child contains the theatre name.
    cards = page.locator(
        "button, a, [role='button'], li, article, div"
    ).filter(has_text=TARGET_THEATRE)

    print(f"Langley fallback card count: {cards.count()}")

    for index in range(min(cards.count(), 20)):
        card = cards.nth(index)

        try:
            if not card.is_visible():
                continue

            text = card.inner_text().strip()

            if TARGET_THEATRE.lower() not in text.lower():
                continue

            print(f"Trying Langley result card: {text[:300]!r}")

            card.scroll_into_view_if_needed()

            try:
                card.click(timeout=5_000)
            except Exception:
                card.evaluate(
                    """
                    element => {
                        const clickable = element.closest(
                            'button, a, [role="button"]'
                        );
                        (clickable || element).click();
                    }
                    """
                )

            page.wait_for_timeout(7_000)
            return

        except Exception as exc:
            print(
                f"Langley result card failed: "
                f"{type(exc).__name__}: {exc}"
            )

    raise RuntimeError(
        "Cineplex Cinemas Langley did not appear in the results."
    )


def main() -> None:
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)

    print("Starting Langley theatre-selection test")

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

            print("Ticket drawer opened.")
            save_page(page, debug_dir, "01-ticket-drawer")

            open_theatre_selector(page)

            print("Theatre selector opened.")
            save_page(page, debug_dir, "02-theatre-selector")

            search_for_langley(page)

            print("Langley search entered.")
            save_page(page, debug_dir, "03-langley-search")

            choose_langley(page)

            print("Langley result clicked.")
            save_page(page, debug_dir, "04-langley-selected")

            final_text = page.locator("body").inner_text(
                timeout=15_000
            )

            if TARGET_THEATRE.lower() in final_text.lower():
                print(
                    "SUCCESS: Cineplex Cinemas Langley appears "
                    "in the ticket drawer."
                )
            else:
                print(
                    "WARNING: Langley was clicked, but the final "
                    "page text does not clearly confirm the selection."
                )

        except Exception as exc:
            print(
                f"THEATRE TEST FAILED: "
                f"{type(exc).__name__}: {exc}"
            )

            try:
                save_page(page, debug_dir, "error")
            except Exception:
                pass

            raise

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
