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


def normalize_phone(phone: str):
    """
    Produce common public-facing variants of a phone number.
    Assumes input is international format (+44...).
    """
    if not phone:
        return []

    p = phone.strip()
    variants = set()

    # Raw
    variants.add(p)

    # Remove spaces
    variants.add(p.replace(" ", ""))

    # Without +
    if p.startswith("+"):
        variants.add(p[1:])

    # UK-specific common formats
    if p.startswith("+44"):
        local = "0" + p[3:]
        variants.add(local)
        variants.add(local.replace(" ", ""))
        variants.add("+44 " + p[3:])
        variants.add("0 " + p[3:])

    return sorted(v for v in variants if len(v) >= 7)


def check_phone_public_exposure(phone: str):
    """
    Checks whether a phone number appears to be publicly indexed.
    Conservative boolean signal only.
    """
    variants = normalize_phone(phone)
    found_anywhere = False
    checked = []

    for variant in variants:
        query = f"\"{variant}\""
        url = SEARCH_ENGINES[0].format(query=urllib.parse.quote(query))
        checked.append(url)

        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue

            if variant.lower() in r.text.lower():
                found_anywhere = True
                break
        except requests.RequestException:
            continue

        time.sleep(2)

    return {
        "phone": phone,
        "publicly_indexed": found_anywhere,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "variants_checked": variants,
        "engines_checked": checked,
    }
