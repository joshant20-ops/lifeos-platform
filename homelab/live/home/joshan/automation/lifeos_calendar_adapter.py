#!/usr/bin/env python3
import json
import sys
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

BASE_URL = "http://127.0.0.1:5232"
TEST_COLLECTION = "lifeos-test"


def req(method, url, data=None, headers=None, timeout=15):
    r = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers or {},
    )
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, resp.read()


def ensure_collection():
    url = f"{BASE_URL}/{TEST_COLLECTION}/"
    body = b"""<?xml version="1.0" encoding="utf-8" ?>
<mkcalendar xmlns="urn:ietf:params:xml:ns:caldav">
  <set>
    <prop xmlns="DAV:">
      <displayname>LifeOS Test</displayname>
    </prop>
  </set>
</mkcalendar>"""

    try:
        status, _ = req("MKCOL", url)
        return status in (201, 204)
    except Exception as e:
        # Collection may already exist.
        try:
            status, _ = req("PROPFIND", url)
            return status in (200, 207)
        except Exception:
            raise e


def create_test_event(title, date, time):
    uid = f"lifeos-{uuid.uuid4()}@local"
    dt = datetime.fromisoformat(f"{date}T{time}")

    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    start = dt.strftime("%Y%m%dT%H%M%S")
    end = dt.replace(hour=(dt.hour + 1) % 24).strftime("%Y%m%dT%H%M%S")

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//LifeOS//PA Test//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{stamp}
DTSTART:{start}
DTEND:{end}
SUMMARY:{title}
END:VEVENT
END:VCALENDAR
""".encode()

    url = f"{BASE_URL}/{TEST_COLLECTION}/{uid}.ics"

    status, _ = req(
        "PUT",
        url,
        data=ics,
        headers={"Content-Type": "text/calendar; charset=utf-8"},
    )

    if status not in (201, 204):
        raise RuntimeError(f"create failed: HTTP {status}")

    return {"uid": uid, "url": url}


def delete_event(url):
    status, _ = req("DELETE", url)
    return status in (200, 202, 204)


def main():
    if len(sys.argv) < 2:
        print("usage: lifeos_calendar_adapter.py test")
        return 2

    if sys.argv[1] != "test":
        print("unsupported command")
        return 2

    ensure_collection()

    event = create_test_event(
        "LifeOS Synthetic Appointment",
        "2099-10-15",
        "14:00",
    )

    print("CREATE=PASS")
    print("UID=" + event["uid"])

    if delete_event(event["url"]):
        print("DELETE=PASS")
    else:
        print("DELETE=FAIL")
        return 1

    print("RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
