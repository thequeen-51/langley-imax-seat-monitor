import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import httpx
from playwright.async_api import async_playwright, Response

API_BASE = "https://apis.cineplex.com/prod/cpx/theatrical/api/v1"
PUBLIC_API_KEY = os.getenv("CINEPLEX_API_KEY", "dcdac5601d864addbc2675a2e96cb1f8")
THEATRE_ID = os.getenv("THEATRE_ID", "1405")
MOVIE_TITLE = os.getenv("MOVIE_TITLE", "The Odyssey")
DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", "120"))
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
DEBUG_DIR = Path("debug")

PREFERRED = [
    ("第一优先", "H", range(10, 16)),
    ("第二优先", "I", range(10, 16)),
    ("第三优先", "G", range(10, 16)),
]

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def walk(obj: Any) -> Iterable[tuple[list[str], Any]]:
    stack = [([], obj)]
    while stack:
        path, value = stack.pop()
        yield path, value
        if isinstance(value, dict):
            for k, v in value.items():
                stack.append((path + [str(k)], v))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                stack.append((path + [str(i)], v))


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def is_target_movie(name: str) -> bool:
    return normalize_title(MOVIE_TITLE) in normalize_title(name)


def is_target_experience(exp: dict[str, Any]) -> bool:
    text = json.dumps(exp, ensure_ascii=False).lower()
    return "imax" in text and ("70mm" in text or "70 mm" in text or "70-millimeter" in text)


def first_value(d: dict[str, Any], names: list[str]) -> Any:
    lowered = {str(k).lower(): v for k, v in d.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


async def api_get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
    r = await client.get(
        f"{API_BASE}/{path}",
        params=params,
        headers={"Ocp-Apim-Subscription-Key": PUBLIC_API_KEY},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


async def discover_showtimes() -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    today = datetime.now()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for offset in range(DAYS_AHEAD):
            day = today + timedelta(days=offset)
            params = {
                "language": "en",
                "locationId": THEATRE_ID,
                "date": day.strftime("%m/%d/%Y"),
            }
            try:
                data = await api_get(client, "showtimes", params)
            except Exception as e:
                print(f"[showtimes] {day.date()}: {e}", file=sys.stderr)
                continue

            for _, node in walk(data):
                if not isinstance(node, dict):
                    continue
                name = first_value(node, ["name", "movieName", "filmName", "title"])
                if not isinstance(name, str) or not is_target_movie(name):
                    continue

                experiences = first_value(node, ["experiences", "formats"]) or []
                if not isinstance(experiences, list):
                    continue

                for exp in experiences:
                    if not isinstance(exp, dict) or not is_target_experience(exp):
                        continue
                    sessions = first_value(exp, ["sessions", "showtimes"]) or []
                    if not isinstance(sessions, list):
                        continue

                    for session in sessions:
                        if not isinstance(session, dict):
                            continue
                        showtime_id = first_value(session, ["showtimeId", "sessionId", "id"])
                        start = first_value(session, ["showStartDateTime", "startDateTime", "startTime"])
                        category = first_value(
                            session,
                            ["vistaHOCategoryCode", "hoCategoryCode", "categoryCode"],
                        ) or "0000000001"
                        if showtime_id is None:
                            continue

                        showtime_id = str(showtime_id)
                        query = urlencode(
                            {
                                "theatreId": THEATRE_ID,
                                "showtimeId": showtime_id,
                                "dbox": "False",
                                "vistaHOCategoryCode": str(category),
                            }
                        )
                        found[showtime_id] = {
                            "showtime_id": showtime_id,
                            "start": str(start or day.date()),
                            "category": str(category),
                            "experience": first_value(exp, ["name", "experienceName", "description"]) or "IMAX 70mm",
                            "url": f"https://www.cineplex.com/ticketing/tickets?{query}",
                        }

    return sorted(found.values(), key=lambda x: x["start"])


def looks_like_seat_payload(data: Any) -> bool:
    text = json.dumps(data, ensure_ascii=False).lower()
    seat_words = sum(word in text for word in ["seat", "row", "available", "occupied", "sold"])
    labels = len(re.findall(r'"?[a-z]\s*[-_]?\s*\d{1,3}"?', text))
    return seat_words >= 2 and labels >= 2


def seat_status_from_node(node: dict[str, Any]) -> tuple[str, bool] | None:
    row = first_value(node, ["row", "rowLabel", "rowName", "seatRow"])
    number = first_value(node, ["number", "seatNumber", "column", "columnNumber", "label"])
    name = first_value(node, ["seatName", "displayName", "name", "code"])

    label = None
    if row is not None and number is not None:
        label = f"{row}{number}"
    elif isinstance(name, str):
        match = re.search(r"\b([A-Za-z])\s*[- ]?\s*(\d{1,3})\b", name)
        if match:
            label = f"{match.group(1)}{match.group(2)}"

    if not label:
        return None

    label = label.upper().replace(" ", "").replace("-", "")
    if not re.fullmatch(r"[A-Z]\d{1,3}", label):
        return None

    available = first_value(node, ["isAvailable", "available", "canBook", "selectable"])
    occupied = first_value(node, ["isOccupied", "occupied", "isSold", "sold"])
    status = first_value(node, ["status", "seatStatus", "availabilityStatus", "state"])

    if isinstance(available, bool):
        is_available = available
    elif isinstance(occupied, bool):
        is_available = not occupied
    elif status is not None:
        s = str(status).lower()
        is_available = any(x in s for x in ["available", "free", "open", "selectable"]) and not any(
            x in s for x in ["unavailable", "occupied", "sold", "blocked", "held"]
        )
    else:
        return None

    return label, is_available


def extract_available_seats(payloads: list[Any]) -> set[str]:
    seats: dict[str, bool] = {}
    for payload in payloads:
        for _, node in walk(payload):
            if isinstance(node, dict):
                result = seat_status_from_node(node)
                if result:
                    label, available = result
                    seats[label] = available
    return {label for label, available in seats.items() if available}


async def collect_seat_payloads(showtime: dict[str, Any]) -> tuple[list[Any], str]:
    payloads: list[Any] = []
    candidate_urls: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="en-CA",
            timezone_id="America/Vancouver",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126 Safari/537.36"
            ),
        )
        page = await context.new_page()

        async def on_response(response: Response) -> None:
            content_type = (await response.all_headers()).get("content-type", "")
            if "json" not in content_type.lower():
                return
            try:
                data = await response.json()
            except Exception:
                return
            if looks_like_seat_payload(data):
                payloads.append(data)
                candidate_urls.append(response.url)

        page.on("response", on_response)

        try:
            await page.goto(showtime["url"], wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(8000)

            # Try common consent and seat-preview controls without purchasing anything.
            for pattern in [
                r"accept",
                r"agree",
                r"preview seats",
                r"view seats",
                r"choose seats",
                r"select seats",
            ]:
                try:
                    locator = page.get_by_role("button", name=re.compile(pattern, re.I))
                    if await locator.count():
                        await locator.first.click(timeout=3000)
                        await page.wait_for_timeout(5000)
                except Exception:
                    pass

            # Save diagnostics so a site change is visible in Actions artifacts.
            DEBUG_DIR.mkdir(exist_ok=True)
            sid = showtime["showtime_id"]
            await page.screenshot(path=DEBUG_DIR / f"{sid}.png", full_page=True)
            (DEBUG_DIR / f"{sid}.html").write_text(await page.content(), encoding="utf-8")
        finally:
            await browser.close()

    return payloads, "\n".join(candidate_urls)


def find_pairs(available: set[str]) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for priority, row, numbers in PREFERRED:
        nums = list(numbers)
        for left, right in zip(nums, nums[1:]):
            a, b = f"{row}{left}", f"{row}{right}"
            if a in available and b in available:
                matches.append({"priority": priority, "seats": f"{a}–{b}"})
    return matches


async def telegram(text: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=30,
        )
        r.raise_for_status()


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"active": {}, "known_showtimes": []}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"active": {}, "known_showtimes": []}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    state = load_state()
    showtimes = await discover_showtimes()
    print(f"Found {len(showtimes)} future target showtimes.")

    current_ids = {s["showtime_id"] for s in showtimes}
    old_ids = set(state.get("known_showtimes", []))
    new_ids = current_ids - old_ids

    for s in showtimes:
        if s["showtime_id"] in new_ids and old_ids:
            await telegram(
                "🚨 Cineplex 新增场次\n"
                f"🎬 {MOVIE_TITLE} — IMAX 70mm\n"
                f"📍 Langley\n"
                f"🕒 {s['start']}\n"
                f"🎟 {s['url']}"
            )

    next_active: dict[str, bool] = {}
    had_payload = False

    for s in showtimes:
        payloads, source_urls = await collect_seat_payloads(s)
        if payloads:
            had_payload = True
        available = extract_available_seats(payloads)
        pairs = find_pairs(available)

        for pair in pairs:
            key = hashlib.sha256(
                f"{s['showtime_id']}|{pair['seats']}".encode()
            ).hexdigest()[:20]
            next_active[key] = True
            if not state.get("active", {}).get(key):
                await telegram(
                    "🎉 发现两张理想连座！\n"
                    f"🎬 {MOVIE_TITLE} — IMAX 70mm\n"
                    f"📍 Cineplex Cinemas Langley\n"
                    f"🕒 {s['start']}\n"
                    f"💺 {pair['seats']}（{pair['priority']}）\n"
                    f"🎟 立即购买：{s['url']}"
                )

        if source_urls:
            print(f"[{s['showtime_id']}] candidate seat responses:\n{source_urls}")

    state["active"] = next_active
    state["known_showtimes"] = sorted(current_ids)
    state["last_run"] = datetime.now().isoformat()
    state["seat_payload_detected"] = had_payload
    save_state(state)

    if showtimes and not had_payload:
        print(
            "::warning::Showtimes were found, but no seat-map JSON response was detected. "
            "Download the debug artifact and inspect the saved screenshot/HTML."
        )


if __name__ == "__main__":
    asyncio.run(main())
