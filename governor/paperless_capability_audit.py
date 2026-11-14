"""Bounded local REST inventory. Only explicitly selected aggregates leave host."""
import json
import os
import pathlib
import re
import urllib.request

BASE = "http://127.0.0.1:8010/api/"
TOKEN = pathlib.Path("/etc/lifeos/secrets/paperless-api-token")
LIMIT = 131072
COUNTS = ("workflows", "custom_fields", "saved_views", "mail_accounts", "mail_rules")
STATS = ("documents_total", "documents_inbox", "character_count", "tag_count",
         "correspondent_count", "document_type_count", "storage_path_count")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def number(value):
    return value if type(value) is int and 0 <= value <= 10**15 else "UNKNOWN"


def collect(get):
    out = {"SCOPE": "TOKEN_VISIBLE_ONLY", "MUTATIONS": "NONE"}
    stats = get("statistics/")
    for key in STATS:
        out[key.upper()] = number(stats.get(key)) if isinstance(stats, dict) else "UNKNOWN"
    for endpoint in COUNTS:
        payload = get(endpoint + "/?page_size=1")
        out[endpoint.upper() + "_COUNT"] = number(payload.get("count")) if isinstance(payload, dict) else "UNKNOWN"
    out["COMPLETENESS"] = "PARTIAL" if "UNKNOWN" in out.values() else "AVAILABLE"
    return out


def main():
    try:
        if os.getloadavg()[0] >= 3:
            print("PAPERLESS_CAPABILITY_RESULT=DEFERRED_LOAD")
            return
    except OSError:
        print("PAPERLESS_CAPABILITY_RESULT=RESOURCE_UNKNOWN")
        return
    try:
        if TOKEN.is_symlink() or not TOKEN.is_file() or TOKEN.stat().st_size > 4096:
            raise ValueError()
        token = TOKEN.read_text().strip()
        if not token or any(c in token for c in "\r\n"):
            raise ValueError()
    except (OSError, ValueError, UnicodeError):
        print("PAPERLESS_CAPABILITY_RESULT=TOKEN_UNAVAILABLE")
        return
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(path):
        try:
            request = urllib.request.Request(BASE + path, headers={"Authorization": "Token " + token, "Accept": "application/json"})
            with opener.open(request, timeout=4) as response:
                raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                return None
            return json.loads(raw)
        except Exception:
            # Exception text can contain private response content: suppress it.
            return None

    for key, value in collect(get).items():
        print(f"PAPERLESS_CAPABILITY_{key}={value}")


if __name__ == "__main__":
    main()
