import time
import urllib.parse
import requests
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "PrivacyGuardian/1.0 (+https://example.local)"
}

SEARCH_ENGINES = [
    # DuckDuckGo HTML endpoint (no JS, lightweight)
    "https://duckduckgo.com/html/?q={query}",
]


def check_email_public_exposure(email: str):
    """
    Checks whether an email address appears to be publicly indexed.
    This does NOT scrape pages and does NOT bypass protections.
    It only checks whether search results exist.
    """

    encoded = urllib.parse.quote(f"\"{email}\"")
    found_anywhere = False
    checked_engines = []

    for engine in SEARCH_ENGINES:
        url = engine.format(query=encoded)
        checked_engines.append(url)

        try:
            r = requests.get(url, headers=HEADERS, timeout=10)

            if r.status_code != 200:
                continue

            # Extremely conservative signal:
            # If the email literal appears anywhere in result HTML
            if email.lower() in r.text.lower():
                found_anywhere = True

        except requests.RequestException:
            continue

        # Be polite
        time.sleep(2)

    return {
        "email": email,
        "publicly_indexed": found_anywhere,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "engines_checked": checked_engines,
    }
