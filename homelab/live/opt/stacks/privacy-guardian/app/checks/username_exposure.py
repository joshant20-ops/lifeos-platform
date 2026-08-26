import time
import urllib.parse
import requests
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "PrivacyGuardian/1.0 (+https://example.local)"
}

SEARCH_ENGINES = [
    "https://duckduckgo.com/html/?q={query}",
]


def _ddg_query(q: str) -> str:
    return SEARCH_ENGINES[0].format(query=urllib.parse.quote(q))


def check_username_public_exposure(username: str):
    """
    Checks whether a username/handle appears to be publicly indexed.
    Conservative: looks for the literal username in result HTML.
    """
    username = (username or "").strip()
    if not username:
        return {
            "username": username,
            "publicly_indexed": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "reason": "empty",
            "engines_checked": [],
        }

    # Keep it polite + avoid overly broad tiny tokens
    if len(username) < 4:
        return {
            "username": username,
            "publicly_indexed": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "reason": "too_short",
            "engines_checked": [],
        }

    found_anywhere = False
    checked = []

    # Quote it to reduce noise
    query = f"\"{username}\""

    for engine in SEARCH_ENGINES:
        url = engine.format(query=urllib.parse.quote(query))
        checked.append(url)
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            if username.lower() in r.text.lower():
                found_anywhere = True
        except requests.RequestException:
            continue

        time.sleep(2)

    return {
        "username": username,
        "publicly_indexed": found_anywhere,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "engines_checked": checked,
    }


def usernames_from_emails(emails):
    """
    Extract potential usernames from emails (local-part before @).
    Also adds some normalized variants.
    """
    out = set()
    for e in emails or []:
        if not e or "@" not in e:
            continue
        local = e.split("@", 1)[0].strip()
        if not local:
            continue
        out.add(local)
        out.add(local.replace(".", ""))
        out.add(local.replace("_", ""))
        out.add(local.replace("-", ""))
    # drop empties
    return sorted([u for u in out if u])
