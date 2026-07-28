import json
from datetime import date, timedelta

import requests


THEATRE_ID = "1405"
MOVIE_KEYWORD = "odyssey"
DAYS_TO_CHECK = 30


def main() -> None:
    print("Starting Cineplex showtime discovery test")
    print(f"Theatre ID: {THEATRE_ID}")

    found = []

    for offset in range(DAYS_TO_CHECK):
        show_date = date.today() + timedelta(days=offset)
        date_text = show_date.isoformat()

        url = (
            "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/"
            f"showtimes?language=en-us&locationId={THEATRE_ID}&date={date_text}"
        )

        print(f"Checking {date_text}")

        try:
            response = requests.get(
                url,
                timeout=30,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 Chrome/126 Safari/537.36"
                    ),
                    "Accept": "application/json",
                },
            )

            print(f"HTTP status: {response.status_code}")

            if response.status_code != 200:
                continue

            data = response.json()

            # Save one response for diagnosis.
            if offset == 0:
                with open("cineplex-response.json", "w", encoding="utf-8") as file:
                    json.dump(data, file, ensure_ascii=False, indent=2)

            text = json.dumps(data, ensure_ascii=False).lower()

            if MOVIE_KEYWORD in text:
                print(f"Possible Odyssey result found on {date_text}")
                found.append(date_text)

        except Exception as exc:
            print(f"Error on {date_text}: {type(exc).__name__}: {exc}")

    if found:
        print("Possible matching dates:")
        for item in found:
            print(f"- {item}")
    else:
        print("No Odyssey result found in the tested dates.")

    print("Discovery test finished.")


if __name__ == "__main__":
    main()
