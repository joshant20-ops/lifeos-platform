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


def extract_address_tokens(address_text: str):
    """
    Derive conservative search tokens from a free-form address block.
    """
    if not address_text:
        return {}

    lines = [l.strip() for l in address_text.splitlines() if l.strip()]
    street = None
    postcode = None
    town = None

    for l in lines:
        if any(c.isdigit() for c in l) and len(l) > 5 and not street:
            street = l
        if len(l.replace(" ", "")) >= 5 and any(c.isdigit() for c in l) and any(c.isalpha() for c in l):
            postcode = l
        if not town and l.isalpha():
            town = l

    return {
        "street": street,
        "postcode": postcode,
        "town": town,
    }


def build_address_queries(full_name: str, address_text: str):
    tokens = extract_address_tokens(address_text)
    queries = []

    street = tokens.get("street")
    postcode = tokens.get("postcode")
    town = tokens.get("town")

    if full_name and street:
        queries.append(f"\"{full_name}\" \"{street}\"")

    if street and postcode:
        queries.append(f"\"{street}\" \"{postcode}\"")

    if street and town:
        queries.append(f"\"{street}\" \"{town}\"")

    if full_name and postcode:
        queries.append(f"\"{full_name}\" \"{postcode}\"")

    # de-duplicate
    return list(dict.fromkeys([q for q in queries if q]))


def check_address_public_exposure(full_name: str, address_text: str):
    queries = build_address_queries(full_name, address_text)
    checked = []
    found = False

    for q in queries:
        url = SEARCH_ENGINES[0].format(query=urllib.parse.quote(q))
        checked.append(url)

        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue

            if full_name.lower() in r.text.lower() or (address_text.splitlines()[0].lower() in r.text.lower()):
                found = True
                break
        except requests.RequestException:
            continue

        time.sleep(2)

    return {
        "queries": queries,
        "publicly_indexed": found,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "engines_checked": checked,
    }
