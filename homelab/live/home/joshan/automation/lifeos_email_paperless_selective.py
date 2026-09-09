#!/usr/bin/env python3
"""Selective local-only Email to Paperless adapter.

AI recommends a disposition. Deterministic code alone authorizes writes.
"""
from __future__ import annotations

import email
import imaplib
import json
import os
import re
import ssl
import sys
import time
import uuid
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO = Path(os.getenv("LIFEOS_PLATFORM_REPO", "/home/joshan/lifeos-platform"))
sys.path.insert(0, str(REPO))
from governor import ai_broker

PAPERLESS_URL = os.getenv("PAPERLESS_URL", "http://127.0.0.1:8010").rstrip("/")
ALLOWED = {
    "ignore",
    "event/action only",
    "archive authoritative attachment",
    "archive important body-derived evidence",
    "duplicate/link existing evidence",
}
MAX_ATTACHMENT = 10 * 1024 * 1024


class BoundaryError(RuntimeError):
    pass


def secret(env_name, candidates):
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    directory = os.getenv("CREDENTIALS_DIRECTORY")
    paths = ([Path(directory) / x for x in candidates] if directory else [])
    paths += [Path("/etc/lifeos/secrets") / x for x in candidates]
    for path in paths:
        if path.is_file() and not path.is_symlink():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    raise BoundaryError(env_name.lower() + "_unavailable")


def imap_credentials():
    user = secret("LIFEOS_IMAP_USER", ("gmail-imap-user", "imap-user", "gmail-user"))
    password = secret(
        "LIFEOS_IMAP_PASSWORD",
        ("gmail-imap-password", "imap-password", "gmail-app-password"),
    )
    return user, password


def paperless_token():
    return secret("PAPERLESS_TOKEN", ("paperless-api-token", "paperless_token"))


def paperless(method, path, body=None, content_type=None):
    headers = {
        "Authorization": "Token " + paperless_token(),
        "Accept": "application/json; version=10",
        "User-Agent": "LifeOS-PA-Selective/1",
    }
    if content_type:
        headers["Content-Type"] = content_type
    req = Request(PAPERLESS_URL + path, data=body, method=method, headers=headers)
    with urlopen(req, timeout=30) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def multipart(fields, filename, payload, mime):
    boundary = "----lifeos" + uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts += [
            "--" + boundary,
            'Content-Disposition: form-data; name="' + key + '"',
            "",
            str(value),
        ]
    head = ("\r\n".join(parts) + "\r\n--" + boundary + "\r\n"
            + 'Content-Disposition: form-data; name="document"; filename="' + filename + '"\r\n'
            + "Content-Type: " + mime + "\r\n\r\n").encode()
    return head + payload + ("\r\n--" + boundary + "--\r\n").encode(), "multipart/form-data; boundary=" + boundary


def append_fetch_synthetic(client, mailbox, message):
    raw = message.as_bytes()
    status, _ = client.append(mailbox, None, imaplib.Time2Internaldate(time.time()), raw)
    if status != "OK":
        raise BoundaryError("imap_append_failed")
    message_id = message["Message-ID"]
    status, rows = client.search(None, "HEADER", "Message-ID", '"' + message_id + '"')
    if status != "OK" or not rows or not rows[0]:
        raise BoundaryError("imap_search_failed")
    uid = rows[0].split()[-1]
    status, data = client.fetch(uid, "(RFC822)")
    if status != "OK":
        raise BoundaryError("imap_fetch_failed")
    fetched = next(x[1] for x in data if isinstance(x, tuple))
    return uid, email.message_from_bytes(fetched)


def extract_attachment(message):
    for part in message.walk():
        name = part.get_filename()
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        return {
            "filename": Path(name).name,
            "mime": part.get_content_type(),
            "payload": payload,
        }
    raise BoundaryError("synthetic_attachment_missing")


def local_triage(message, attachment):
    subject = str(message.get("Subject", ""))[:300]
    prompt = """Classify this synthetic Email for local Personal Administration.
Return JSON only with keys disposition, reason, event_title, obligation.
Allowed disposition values:
ignore
event/action only
archive authoritative attachment
archive important body-derived evidence
duplicate/link existing evidence
The attachment is a synthetic authoritative appointment notice.
No external action.

Subject: """ + subject + """
Attachment MIME: """ + attachment["mime"] + """
Attachment name: """ + attachment["filename"]
    raw = ai_broker._ollama(prompt, ai_broker.OLLAMA_MODEL)
    text = str(raw).strip()
    try:
        decision = json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        decision = json.loads(text[start:end + 1])
    return decision


def policy(decision, attachment):
    disposition = str(decision.get("disposition", "")).strip().lower()
    authorized = (
        disposition == "archive authoritative attachment"
        and attachment["mime"] == "application/pdf"
        and attachment["filename"].lower().endswith(".pdf")
        and 0 < len(attachment["payload"]) <= MAX_ATTACHMENT
        and attachment["filename"].startswith("lifeos-synthetic-")
    )
    return {"disposition": disposition, "authorized": authorized, "allowed": disposition in ALLOWED}


def upload_and_verify(marker, attachment):
    body, kind = multipart(
        {"title": marker},
        attachment["filename"],
        attachment["payload"],
        attachment["mime"],
    )
    task = paperless("POST", "/api/documents/post_document/", body, kind)
    task_id = task if isinstance(task, str) else (task or {}).get("task_id")
    for _ in range(30):
        query = urlencode({"query": marker, "page_size": 10})
        result = paperless("GET", "/api/documents/?" + query)
        rows = result if isinstance(result, list) else (result or {}).get("results", [])
        for row in rows:
            if str(row.get("title")) == marker:
                return int(row["id"]), str(task_id or "")
        time.sleep(2)
    raise BoundaryError("paperless_verification_timeout")


def synthetic_pdf(marker):
    text = ("LifeOS synthetic authoritative appointment evidence " + marker).encode("ascii")
    stream = b"BT /F1 12 Tf 72 720 Td (" + text + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out.extend(str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    xref = len(out)
    out.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(("%010d 00000 n \n" % offset).encode())
    out.extend(b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n")
    return bytes(out)


def acceptance():
    marker = "LIFEOS-SYNTHETIC-" + uuid.uuid4().hex
    mailbox = os.getenv("LIFEOS_IMAP_TEST_MAILBOX", "INBOX")
    user, password = imap_credentials()
    client = imaplib.IMAP4_SSL(
        os.getenv("LIFEOS_IMAP_HOST", "imap.gmail.com"),
        int(os.getenv("LIFEOS_IMAP_PORT", "993")),
        ssl_context=ssl.create_default_context(),
    )
    email_uid = None
    document_id = None
    try:
        client.login(user, password)
        client.select(mailbox)
        message = EmailMessage()
        message["From"] = user
        message["To"] = user
        message["Subject"] = "LifeOS Synthetic Appointment " + marker
        message["Message-ID"] = "<" + marker.lower() + "@lifeos.invalid>"
        message.set_content("Synthetic test evidence only.")
        message.add_attachment(
            synthetic_pdf(marker),
            maintype="application",
            subtype="pdf",
            filename="lifeos-synthetic-" + marker + ".pdf",
        )
        email_uid, fetched = append_fetch_synthetic(client, mailbox, message)
        attachment = extract_attachment(fetched)
        decision = local_triage(fetched, attachment)
        result = policy(decision, attachment)
        if not result["allowed"] or not result["authorized"]:
            raise BoundaryError("deterministic_policy_rejected:" + result["disposition"])
        document_id, task_id = upload_and_verify(marker, attachment)
        evidence = {
            "paperless_document_id": document_id,
            "paperless_api_path": "/api/documents/" + str(document_id) + "/",
            "email_message_id": message["Message-ID"],
            "task_id_present": bool(task_id),
        }
        assert evidence["paperless_document_id"] > 0
        print("EMAIL_ADAPTER=REAL")
        print("LOCAL_TRIAGE=REAL_LOCAL_AI")
        print("DETERMINISTIC_POLICY=REAL")
        print("PAPERLESS_SUBMISSION=REAL")
        print("PAPERLESS_VERIFICATION=REAL")
        print("EVIDENCE_LINK=REAL")
        print("EVIDENCE_DOCUMENT_ID=" + str(document_id))
        return evidence
    finally:
        if document_id is not None:
            paperless("DELETE", "/api/documents/" + str(document_id) + "/")
            query = urlencode({"query": marker, "page_size": 10})
            rows = paperless("GET", "/api/documents/?" + query)
            values = rows if isinstance(rows, list) else (rows or {}).get("results", [])
            if values:
                raise BoundaryError("paperless_cleanup_failed")
            print("PAPERLESS_CLEANUP=PASS")
        if email_uid is not None:
            client.store(email_uid, "+FLAGS", "\\Deleted")
            client.expunge()
            status, rows = client.search(None, "HEADER", "Message-ID", '"<' + marker.lower() + '@lifeos.invalid>"')
            if status != "OK" or (rows and rows[0]):
                raise BoundaryError("email_cleanup_failed")
            print("EMAIL_CLEANUP=PASS")
        try:
            client.logout()
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "acceptance":
        raise SystemExit("usage: lifeos_email_paperless_selective.py acceptance")
    acceptance()
    print("RESULT=PASS")
