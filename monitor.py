import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, sync_playwright


MOVIE_URL = (
    "https://www.cineplex.com/movie/"
    "imax70-the-odyssey-the-imax-experience-in-7"
)

TARGET_THEATRE = "Cineplex Cinemas Langley"


def save_debug(page: Page, folder: Path, name: str) -> None:
    page.screenshot(
        path=str(folder / f"{name}.png"),
        full_page=True,
    )

    (folder / f"{name}.html").write_text(
        page.content(),
        encoding="utf-8",
    )

    try:
        text = page.locator("body").inner_text(timeout=15_000)
    except Exception:
        text = ""

    (folder / f"{name}.txt").write_text(
        f"URL: {page.url}\n\n{text}",
        encoding="utf-8",
    )


def click_first_visible(locator: Locator, description: str) -> bool:
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
                f"{description} click failed: "
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


def open_theatre_selector(page: Page) -> None:
    candidates = [
        page.get_by_text("Theatres", exact=True),
        page.get_by_text("Theatre", exact=True),
        page.get_by_role("button", name="Theatres", exact=False),
        page.get_by_role("button", name="Theatre", exact=False),
        page.locator("button, [role='button']").filter(
            has_text="Theatre"
        ),
    ]

    for candidate in candidates:
        if click_first_visible(candidate, "theatre selector"):
            page.wait_for_timeout(3_000)
            return

    raise RuntimeError("Could not open theatre selector.")


def search_and_choose_langley(page: Page) -> None:
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

        if search_field:
            break

    if not search_field:
        raise RuntimeError("Could not find theatre search field.")

    search_field.fill("Langley")
    print("Entered Langley in theatre search.")
    page.wait_for_timeout(4_000)

    results = page.get_by_text(TARGET_THEATRE, exact=True)

    if not click_first_visible(results, TARGET_THEATRE):
        results = page.get_by_text(TARGET_THEATRE, exact=False)

        if not click_first_visible(results, TARGET_THEATRE):
            raise RuntimeError(
                "Could not select Cineplex Cinemas Langley."
            )

    page.wait_for_timeout(7_000)


def element_info(item: Locator) -> dict[str, Any]:
    return item.evaluate(
        """
        element => {
            const clickable = element.closest(
                'button, a, [role="button"]'
            ) || element;

            return {
                tag: element.tagName,
                text: (element.innerText || "").trim(),
                ariaLabel: element.getAttribute("aria-label"),
                href: clickable.href || clickable.getAttribute("href"),
                clickableTag: clickable.tagName,
                clickableText: (clickable.innerText || "").trim(),
                clickableHTML: clickable.outerHTML
            };
        }
        """
    )


def discover_showtimes(page: Page, folder: Path) -> list[dict[str, Any]]:
    print("\nDiscovering all visible showtime controls...")

    time_pattern = re.compile(
        r"\b(?:1[0-2]|0?[1-9]):[0-5][0-9]\s*(?:AM|PM)\b",
        re.IGNORECASE,
    )

    candidates = page.locator(
        "button, a, [role='button'], time"
    )

    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()

    print(f"Interactive candidate count: {candidates.count()}")

    for index in range(candidates.count()):
        item = candidates.nth(index)

        try:
            if not item.is_visible():
                continue

            text = item.inner_text().strip()
            aria_label = item.get_attribute("aria-label") or ""
            combined = f"{text} {aria_label}".strip()

            if not combined:
                continue

            is_time = bool(time_pattern.search(combined))
            is_relevant_format = any(
                word in combined.lower()
                for word in [
                    "imax",
                    "70mm",
                    "odyssey",
                    "showtime",
                ]
            )

            if not is_time and not is_relevant_format:
                continue

            info = element_info(item)
            unique_key = (
                info.get("clickableHTML")
                or info.get("clickableText")
                or combined
            )

            if unique_key in seen:
                continue

            seen.add(unique_key)
            discovered.append(info)

            print("\nSHOWTIME CANDIDATE")
            print(json.dumps(info, ensure_ascii=False, indent=2))

        except Exception as exc:
            print(
                f"Could not inspect candidate #{index + 1}: "
                f"{type(exc).__name__}: {exc}"
            )

    (folder / "showtime-candidates.json").write_text(
        json.dumps(
            discovered,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return discovered


def main() -> None:
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)

    print("Starting Langley all-showtimes discovery test")

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
            open_theatre_selector(page)
            search_and_choose_langley(page)

            print("Langley theatre selected.")
            save_debug(
                page,
                debug_dir,
                "01-langley-showtimes",
            )

            showtimes = discover_showtimes(
                page,
                debug_dir,
            )

            print(
                f"\nTotal relevant showtime candidates found: "
                f"{len(showtimes)}"
            )

            if not showtimes:
                raise RuntimeError(
                    "No visible showtime controls were detected."
                )

            print(
                "SUCCESS: Langley showtime candidates were saved."
            )

        except Exception as exc:
            print(
                f"SHOWTIME DISCOVERY FAILED: "
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
