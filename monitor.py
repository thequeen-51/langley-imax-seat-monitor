import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Locator, Page, Response, sync_playwright


MOVIE_URL = (
    "https://www.cineplex.com/movie/"
    "imax70-the-odyssey-the-imax-experience-in-7"
)

TARGET_THEATRE = "Cineplex Cinemas Langley"


def safe_filename(value: str, limit: int = 120) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value)
    return value[:limit].strip("_") or "response"


def save_page(page: Page, folder: Path, name: str) -> None:
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


def click_first_visible(locator: Locator, description: str) -> bool:
    print(f"{description}: {locator.count()} candidate(s)")

    for index in range(locator.count()):
        item = locator.nth(index)

        try:
            if not item.is_visible():
                continue

            print(f"Clicking {description} candidate #{index + 1}")
            item.scroll_into_view_if_needed()
            page_box = item.bounding_box()
            print(f"Bounding box: {page_box}")

            try:
                item.click(timeout=10_000)
            except Exception as exc:
                print(f"Normal click failed: {exc}")
                item.evaluate("element => element.click()")

            return True

        except Exception as exc:
            print(
                f"{description} candidate #{index + 1} failed: "
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
                page.wait_for_timeout(1_500)
                print(f"Closed cookie banner: {label}")
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

    raise RuntimeError("Could not open ticket drawer.")


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
        raise RuntimeError("Could not find theatre search input.")

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
        raise RuntimeError("Langley theatre selection was not confirmed.")

    print("Langley theatre selected.")


def click_preview_seats(page: Page) -> None:
    candidates = [
        page.get_by_role(
            "button",
            name=re.compile(r"preview seats", re.IGNORECASE),
        ),
        page.get_by_role(
            "link",
            name=re.compile(r"preview seats", re.IGNORECASE),
        ),
        page.get_by_text(
            re.compile(r"preview seats", re.IGNORECASE),
        ),
    ]

    for candidate in candidates:
        if click_first_visible(candidate, "Preview seats"):
            print("Preview seats click issued.")
            return

    matches = page.locator(
        "button, a, [role='button'], div, span"
    ).filter(has_text=re.compile(r"Preview seats", re.IGNORECASE))

    print(f"Preview seats fallback matches: {matches.count()}")

    for index in range(min(matches.count(), 30)):
        item = matches.nth(index)

        try:
            if not item.is_visible():
                continue

            info = item.evaluate(
                """
                element => ({
                    tag: element.tagName,
                    text: (element.innerText || "").trim(),
                    html: element.outerHTML
                })
                """
            )

            print(f"Preview fallback element: {info}")

            item.evaluate(
                """
                element => {
                    const clickable = element.closest(
                        'button, a, [role="button"]'
                    );
                    (clickable || element).click();
                }
                """
            )

            print("Preview seats JavaScript fallback click issued.")
            return

        except Exception as exc:
            print(f"Preview fallback failed: {exc}")

    raise RuntimeError("Could not find or click Preview seats.")


def main() -> None:
    debug_dir = Path("debug")
    responses_dir = debug_dir / "responses"

    debug_dir.mkdir(exist_ok=True)
    responses_dir.mkdir(exist_ok=True)

    network_lines: list[str] = []
    response_counter = 0

    interesting_keywords = [
        "seat",
        "preview",
        "showtime",
        "performance",
        "availability",
        "auditorium",
        "layout",
        "booking",
        "ticket",
        "reservation",
        "checkout",
        "connect.cineplex",
        "apis.cineplex",
    ]

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

        def record_request(request) -> None:
            url_lower = request.url.lower()

            if any(word in url_lower for word in interesting_keywords):
                line = f"REQUEST {request.method} {request.url}"
                print(line)
                network_lines.append(line)

        def record_response(response: Response) -> None:
            nonlocal response_counter

            url_lower = response.url.lower()

            if not any(
                word in url_lower
                for word in interesting_keywords
            ):
                return

            line = (
                f"RESPONSE {response.status} "
                f"{response.request.method} {response.url}"
            )

            print(line)
            network_lines.append(line)

            try:
                content_type = (
                    response.headers.get("content-type", "").lower()
                )

                if (
                    "json" not in content_type
                    and "text" not in content_type
                    and "javascript" not in content_type
                ):
                    return

                body = response.text()

                if not body:
                    return

                response_counter += 1
                parsed_url = urlparse(response.url)
                name = safe_filename(
                    f"{response_counter:03d}_"
                    f"{parsed_url.netloc}_"
                    f"{parsed_url.path}"
                )

                extension = (
                    ".json"
                    if "json" in content_type
                    else ".txt"
                )

                output_path = responses_dir / f"{name}{extension}"
                output_path.write_text(body, encoding="utf-8")

                meta_path = responses_dir / f"{name}.meta.txt"
                meta_path.write_text(
                    "\n".join(
                        [
                            f"URL: {response.url}",
                            f"Status: {response.status}",
                            f"Method: {response.request.method}",
                            f"Content-Type: {content_type}",
                        ]
                    ),
                    encoding="utf-8",
                )

                print(f"Saved response body: {output_path}")

            except Exception as exc:
                print(
                    f"Could not save response body: "
                    f"{type(exc).__name__}: {exc}"
                )

        page.on("request", record_request)
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
                "01-before-preview-seats",
            )

            click_preview_seats(page)

            print("Waiting for preview-seat response...")
            page.wait_for_timeout(20_000)

            print(f"Current URL: {page.url}")
            print(f"Open browser pages: {len(context.pages)}")

            for index, current_page in enumerate(
                context.pages,
                start=1,
            ):
                try:
                    current_page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=20_000,
                    )
                except Exception:
                    pass

                print(
                    f"PAGE #{index}: "
                    f"title={current_page.title()!r}, "
                    f"url={current_page.url}"
                )

                save_page(
                    current_page,
                    debug_dir,
                    f"02-after-preview-page-{index}",
                )

            print(
                f"Saved {response_counter} relevant response bodies."
            )

        except Exception as exc:
            print(
                f"PREVIEW-SEATS TEST FAILED: "
                f"{type(exc).__name__}: {exc}"
            )

            try:
                save_page(page, debug_dir, "error")
            except Exception:
                pass

            raise

        finally:
            (debug_dir / "network-log.txt").write_text(
                "\n".join(network_lines),
                encoding="utf-8",
            )

            context.close()
            browser.close()


if __name__ == "__main__":
    main()
