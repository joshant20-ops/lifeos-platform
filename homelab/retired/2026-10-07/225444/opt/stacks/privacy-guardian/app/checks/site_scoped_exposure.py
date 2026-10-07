import os
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus, unquote

import requests

SITES = [
    "github.com",
    "pastebin.com",
    "gitlab.com",
    "stackoverflow.com",
    "reddit.com",
    "replit.com",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (PrivacyGuardian)"}

# --- tunables via env ---
PG_DDG_TIMEOUT = float(os.getenv("PG_DDG_TIMEOUT", "20"))
PG_DDG_RETRIES = int(os.getenv("PG_DDG_RETRIES", "2"))
PG_DDG_DELAY = float(os.getenv("PG_DDG_DELAY", "2.5"))
PG_DDG_JITTER = float(os.getenv("PG_DDG_JITTER", "1.5"))
PG_DDG_BACKOFF = float(os.getenv("PG_DDG_BACKOFF", "2.0"))

# DuckDuckGo html results include links like:
# <a rel="nofollow" class="result__a" href="...">Title</a>
RESULT_LINK_RE = re.compile(r'class="result__a"[^>]*href="([^"]+)"', re.IGNORECASE)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _sleep_base():
    time.sleep(PG_DDG_DELAY + random.uniform(0, PG_DDG_JITTER))


def _ddg_fetch(session: requests.Session, query: str) -> tuple[str | None, str | None]:
    """
    Returns (html, error). Never raises.
    """
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        r = session.get(url, headers=HEADERS, timeout=PG_DDG_TIMEOUT)
        if r.status_code in (403, 429, 503):
            return None, f"blocked_or_ratelimited_http_{r.status_code}"
        if r.status_code >= 400:
            return None, f"http_{r.status_code}"
        text = r.text or ""
        low = text.lower()
        if "captcha" in low or "unusual traffic" in low or "verify you are a human" in low:
            return None, "captcha_or_block_page"
        return text, None
    except Exception as e:
        return None, str(e)


def _extract_result_urls(html: str) -> list[str]:
    urls = []
    for m in RESULT_LINK_RE.finditer(html):
        href = m.group(1)
        # DDG sometimes URL-encodes things; normalize
        urls.append(unquote(href))
    return urls


def _is_real_hit(value: str, urls: list[str]) -> bool:
    """
    IMPORTANT: do NOT match against the whole HTML (it echoes the query).
    Instead, decide based on extracted result URLs.
    """
    v = value.strip().lower()
    if not v:
        return False

    # A conservative match:
    # - if the value appears in any result URL, count as hit.
    # (This avoids the "query echoed in HTML" false-positive.)
    for u in urls:
        if v in u.lower():
            return True
    return False


def check_site_scoped(value: str) -> dict:
    """
    site:<domain> "<value>" across several sites.

    publicly_indexed:
      True  : at least one definite hit
      False : at least one successful fetch and zero hits
      None  : all sites failed/blocked (UNKNOWN)
    """
    value = (value or "").strip()
    if not value:
        return {
            "value": value,
            "publicly_indexed": None,
            "checked_at": utc_now_iso(),
            "sites_checked": [],
            "error": "empty value",
        }

    session = requests.Session()

    any_success = False
    any_hit = False
    sites_checked = []

    for site in SITES:
        query = f'site:{site} "{value}"'
        entry = {"site": site, "query": query, "found": None}

        attempt = 0
        delay = PG_DDG_DELAY

        while attempt <= PG_DDG_RETRIES:
            html, err = _ddg_fetch(session, query)

            if html is not None:
                any_success = True
                urls = _extract_result_urls(html)
                found = _is_real_hit(value, urls)
                entry["found"] = bool(found)
                # keep a small sample for debugging
                entry["sample_urls"] = urls[:3]
                if found:
                    any_hit = True
                break

            entry["error"] = err
            attempt += 1
            if attempt <= PG_DDG_RETRIES:
                time.sleep(delay + random.uniform(0, PG_DDG_JITTER))
                delay *= PG_DDG_BACKOFF

        sites_checked.append(entry)
        _sleep_base()

    if any_hit:
        publicly_indexed = True
    else:
        publicly_indexed = False if any_success else None

    return {
        "value": value,
        "publicly_indexed": publicly_indexed,
        "checked_at": utc_now_iso(),
        "sites_checked": sites_checked,
    }
