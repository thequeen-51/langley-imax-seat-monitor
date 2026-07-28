from pathlib import Path

from playwright.sync_api import sync_playwright


CINEPLEX_URL = "https://www.cineplex.com/theatre/cineplex-cinemas-langley"


def main() -> None:
    debug_dir = Path("debug")
    debug_dir.mkdir(exist_ok=True)

    print("Starting Cineplex browser test")
    print(f"Opening: {CINEPLEX_URL}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
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
                CINEPLEX_URL,
                wait_until="domcontentloaded",
                timeout=90000,
            )

            if response:
                print(f"HTTP status: {response.status}")
            else:
                print("No HTTP response object was returned.")

            page.wait_for_timeout(10000)

            # Try to close common cookie/privacy popups.
            popup_labels = [
                "Accept",
                "Accept All",
                "I Accept",
                "Agree",
                "Got it",
            ]

            for label in popup_labels:
                try:
                    button = page.get_by_role("button", name=label, exact=False)
                    if button.count() > 0:
                        button.first.click(timeout=2000)
                        print(f"Closed popup using button: {label}")
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass

            title = page.title()
            body_text = page.locator("body").inner_text(timeout=30000)

            print(f"Page title: {title}")
            print(f"Final URL: {page.url}")
            print(f"Body text length: {len(body_text)}")

            if "the odyssey" in body_text.lower():
                print("SUCCESS: The Odyssey was found on the page.")
            else:
                print("WARNING: The Odyssey was not found in visible page text.")

            # Save page text for diagnosis.
            (debug_dir / "page-text.txt").write_text(
                body_text,
                encoding="utf-8",
            )

            # Save the rendered page.
            page.screenshot(
                path=str(debug_dir / "cineplex-langley.png"),
                full_page=True,
            )

            # Save the HTML.
            (debug_dir / "page.html").write_text(
                page.content(),
                encoding="utf-8",
            )

            print("Saved diagnostic files in the debug folder.")

        except Exception as exc:
            print(f"Browser test failed: {type(exc).__name__}: {exc}")

            try:
                page.screenshot(
                    path=str(debug_dir / "error.png"),
                    full_page=True,
                )
            except Exception:
                pass

            raise

        finally:
            context.close()
            browser.close()

    print("Cineplex browser test finished.")


if __name__ == "__main__":
    main()
