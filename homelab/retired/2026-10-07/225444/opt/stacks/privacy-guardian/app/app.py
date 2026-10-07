import csv
import json
import os
from datetime import datetime, timezone, timedelta
from glob import glob

import yaml
from flask import Flask, render_template, redirect, url_for, request

from checks.public_exposure import check_email_public_exposure
from checks.username_exposure import check_username_public_exposure, usernames_from_emails
from checks.phone_exposure import check_phone_public_exposure
from checks.address_exposure import check_address_public_exposure
from checks.site_scoped_exposure import check_site_scoped

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BROKERS_FILE = os.path.join(APP_DIR, "brokers.csv")
PROFILES_DIR = os.path.join(APP_DIR, "profiles")
DATA_DIR = os.path.join(APP_DIR, "data")

app = Flask(__name__)

# ---------------- Time helpers ----------------

def utc_now():
    return datetime.now(timezone.utc)

def utc_now_z():
    return utc_now().isoformat().replace("+00:00", "Z")

def parse_ts(ts: str | None):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

# ---------------- Profile helpers ----------------

def list_profiles():
    files = sorted(glob(os.path.join(PROFILES_DIR, "*.yaml")))
    return [os.path.splitext(os.path.basename(f))[0] for f in files]

def load_profile(profile_name):
    path = os.path.join(PROFILES_DIR, f"{profile_name}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Profile not found: {profile_name}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def status_file(profile_name):
    return os.path.join(DATA_DIR, f"{profile_name}.status.json")

def load_status(profile_name):
    sf = status_file(profile_name)
    if not os.path.exists(sf):
        return {}
    with open(sf, "r", encoding="utf-8") as f:
        return json.load(f)

def save_status(profile_name, status):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(status_file(profile_name), "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

def ensure_status_exists(profile_name):
    """
    Create an initial status file for new profiles so the UI has something to render
    even before the first run.
    """
    sf = status_file(profile_name)
    if os.path.exists(sf):
        return
    init = {
        "_meta": {
            "created": utc_now_z(),
            "last_run_started": None,
            "last_run_finished": None,
            "last_run_mode": None,
            "last_run_result": None,
        }
    }
    save_status(profile_name, init)

def normalize_user(cfg: dict):
    """
    Backward compatible profile parsing.

    Standard output keys:
      full_name: str|None
      address: str|None
      emails: list[str]
      phones: list[str]
      usernames: list[str]
    """
    user = cfg.get("user", {}) if isinstance(cfg.get("user"), dict) else {}

    emails = user.get("emails") or ([user.get("email")] if user.get("email") else [])
    emails = [e.strip() for e in emails if isinstance(e, str) and e.strip()]

    phones = user.get("phones") or ([user.get("phone")] if user.get("phone") else [])
    phones = [p.strip() for p in phones if isinstance(p, str) and p.strip()]

    usernames = user.get("usernames") or ([user.get("username")] if user.get("username") else [])
    usernames = [u.strip() for u in usernames if isinstance(u, str) and u.strip()]

    full_name = user.get("full_name")
    address = user.get("address")

    return {
        "full_name": full_name.strip() if isinstance(full_name, str) and full_name.strip() else None,
        "address": address if isinstance(address, str) and address.strip() else None,
        "emails": emails,
        "phones": phones,
        "usernames": usernames,
    }

# ---------------- Brokers ----------------

def load_brokers():
    if not os.path.exists(BROKERS_FILE):
        return []
    brokers = []
    with open(BROKERS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            brokers.append(
                {
                    "id": row.get("id", "").strip(),
                    "name": row.get("name", "").strip(),
                    "contact_email": row.get("contact_email", "").strip(),
                    "notes": row.get("notes", "").strip(),
                }
            )
    return brokers

# ---------------- Email stub (still disabled) ----------------

def send_email(profile_config, broker):
    return "dry-run (email disabled)"

# ---------------- YES confirmation logic (24h) ----------------

def update_signal(status: dict, key: str, publicly_indexed: bool | None):
    """
    States:
      - NO  => confirmed False immediately
      - YES => suspected on first YES, confirmed only if YES again >= 24h later
      - None => treat as UNKNOWN (kept as publicly_indexed=None, confirmed=None)
    """
    now = utc_now()
    entry = status.get(key, {}) if isinstance(status.get(key), dict) else {}

    if publicly_indexed is None:
        status[key] = {
            "publicly_indexed": None,
            "confirmed": None,
            "last_checked": utc_now_z(),
            "error": entry.get("error"),
        }
        return

    # Clean NO: clears any suspected state
    if publicly_indexed is False:
        status[key] = {
            "publicly_indexed": False,
            "confirmed": False,
            "last_checked": utc_now_z(),
        }
        return

    # YES: confirm only after 24h
    if publicly_indexed is True:
        if entry.get("suspected") is True:
            first_seen = parse_ts(entry.get("first_seen"))
            if first_seen and now >= first_seen + timedelta(hours=24):
                status[key] = {
                    "publicly_indexed": True,
                    "confirmed": True,
                    "last_checked": utc_now_z(),
                }
            else:
                # still suspected, update last_checked
                entry["last_checked"] = utc_now_z()
                status[key] = entry
        else:
            status[key] = {
                "publicly_indexed": True,
                "suspected": True,
                "confirmed": None,
                "first_seen": utc_now_z(),
                "last_checked": utc_now_z(),
                "next_check": (now + timedelta(hours=24)).isoformat(),
            }

# ---------------- Change detection ----------------

def detect_confirmed_changes(prev_status: dict, new_status: dict):
    """
    Only logs changes when CONFIRMED value flips:
      confirmed False <-> confirmed True
    (suspected YES does not count as confirmed)
    """
    changes = []
    keys = sorted(set(prev_status.keys()) | set(new_status.keys()))
    for k in keys:
        pv = prev_status.get(k)
        nv = new_status.get(k)
        if not isinstance(pv, dict) or not isinstance(nv, dict):
            continue
        before = pv.get("confirmed")
        after = nv.get("confirmed")
        if before is None or after is None:
            continue
        if before != after:
            changes.append(
                {
                    "ts": utc_now_z(),
                    "signal": k,
                    "before": before,
                    "after": after,
                }
            )
    return changes

# ---------------- Runner ----------------

def run_profiles(selected_profile: str | None = None, retry_only: bool = False, run_mode: str = "core"):
    profiles = list_profiles()
    if selected_profile:
        profiles = [selected_profile] if selected_profile in profiles else []

    if not profiles:
        print("No profiles found.")
        return

    for profile in profiles:
        ensure_status_exists(profile)

        prev = load_status(profile)
        status = load_status(profile)

        # run metadata (per-profile)
        status.setdefault("_meta", {})
        status["_meta"]["last_run_started"] = utc_now_z()
        status["_meta"]["last_run_finished"] = None
        status["_meta"]["last_run_mode"] = run_mode
        status["_meta"]["last_run_result"] = None

        cfg = load_profile(profile)
        nu = normalize_user(cfg)

        emails = nu["emails"]
        phones = nu["phones"]
        explicit_usernames = nu["usernames"]
        full_name = nu["full_name"]
        address = nu["address"]

        now = utc_now()

        def due(key: str):
            # only run suspected signals when retry_only
            if not retry_only:
                return True
            entry = status.get(key, {})
            if not isinstance(entry, dict):
                return True
            if entry.get("suspected") is True:
                nc = entry.get("next_check")
                nct = parse_ts(nc) if nc else None
                return (nct is None) or (now >= nct)
            return False

        print(f"[RUN] Profile: {profile}")

        # ADDRESS
        if full_name and address and due("address_exposure"):
            res = check_address_public_exposure(full_name, address)
            update_signal(status, "address_exposure", res.get("publicly_indexed"))
            # keep context for UI
            entry = status.get("address_exposure", {})
            if isinstance(entry, dict):
                entry["queries"] = res.get("queries")
                entry["engine"] = "duckduckgo_html"
                status["address_exposure"] = entry

        # PHONE
        for p in phones:
            key = f"phone_exposure|{p}"
            if not due(key):
                continue
            res = check_phone_public_exposure(p)
            update_signal(status, key, res.get("publicly_indexed"))
            entry = status.get(key, {})
            if isinstance(entry, dict):
                entry["engine"] = "duckduckgo_html"
                entry["variants_checked"] = res.get("variants_checked")
                status[key] = entry

        # USERNAMES:
        #  - from profile explicitly (new feature)
        #  - plus derived from emails (existing behavior)
        derived_usernames = usernames_from_emails(emails)
        all_usernames = []
        seen = set()
        for u in (explicit_usernames + derived_usernames):
            if u and u not in seen:
                seen.add(u)
                all_usernames.append(u)

        for uname in all_usernames:
            key = f"username_exposure|{uname}"
            if not due(key):
                continue
            res = check_username_public_exposure(uname)
            update_signal(status, key, res.get("publicly_indexed"))
            entry = status.get(key, {})
            if isinstance(entry, dict):
                entry["engine"] = "duckduckgo_html"
                status[key] = entry

        # EMAIL exposure
        for e in emails:
            key = f"public_exposure|{e}"
            if not due(key):
                continue
            res = check_email_public_exposure(e)
            update_signal(status, key, res.get("publicly_indexed"))
            entry = status.get(key, {})
            if isinstance(entry, dict):
                entry["engine"] = "duckduckgo_html"
                entry["queries"] = res.get("queries")
                status[key] = entry

        # SITE-SCOPED (optional; controlled elsewhere via env/flags)
        # NOTE: keeping your existing behaviour—only runs if your current code path enables it.
        # If site-scoped is disabled, check_site_scoped should short-circuit or return UNKNOWNs.
        # (We are NOT changing that policy here.)
        try:
            site_res = check_site_scoped(emails=emails, usernames=all_usernames)
            if isinstance(site_res, dict):
                for k, v in site_res.items():
                    if not isinstance(v, dict):
                        continue
                    key = f"site_scoped|{k}"
                    if not due(key):
                        continue
                    update_signal(status, key, v.get("publicly_indexed"))
                    entry = status.get(key, {})
                    if isinstance(entry, dict):
                        entry["engine"] = v.get("engine") or "site_scoped"
                        entry["context"] = v.get("context")
                        status[key] = entry
        except Exception as e:
            # never crash a whole run due to site-scoped
            status.setdefault("_meta", {})
            status["_meta"]["site_scoped_error"] = str(e)

        # compute & store confirmed flips
        changes = detect_confirmed_changes(prev, status)
        if changes:
            status.setdefault("_changes", [])
            status["_changes"].extend(changes)

        status["_meta"]["last_run_finished"] = utc_now_z()
        status["_meta"]["last_run_result"] = "ok"
        save_status(profile, status)

# ---------------- CLI ----------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Privacy Guardian")
    parser.add_argument("--profile", help="Run a single profile (by filename without .yaml)")
    parser.add_argument("--run-all", action="store_true", help="Run all profiles")
    parser.add_argument("--retry-only", action="store_true", help="Only re-check due suspected signals")
    args = parser.parse_args()

    if args.profile:
        run_profiles(selected_profile=args.profile, retry_only=args.retry_only, run_mode="core")
    elif args.run_all:
        run_profiles(selected_profile=None, retry_only=args.retry_only, run_mode="core")
    else:
        # default behaviour: run all
        run_profiles(selected_profile=None, retry_only=args.retry_only, run_mode="core")

# ---------------- Flask routes ----------------

@app.route("/")
def index():
    profiles = list_profiles()
    if not profiles:
        return "No profiles found in /app/profiles", 404

    selected = request.args.get("profile") or profiles[0]
    if selected not in profiles:
        selected = profiles[0]

    ensure_status_exists(selected)
    status = load_status(selected)
    cfg = load_profile(selected)
    user = normalize_user(cfg)
    meta = status.get("_meta", {}) if isinstance(status.get("_meta"), dict) else {}
    changes = status.get("_changes", []) if isinstance(status.get("_changes"), list) else []

    exposure = []
    for email in user.get("emails", []):
        entry = status.get(f"email|{email}", {})
        if isinstance(entry, dict):
            exposure.append({
                "email": email,
                "publicly_indexed": entry.get("publicly_indexed"),
                "confirmed": entry.get("confirmed"),
                "last_checked": entry.get("last_checked"),
                "error": entry.get("error"),
                "engine": entry.get("engine"),
            })

    username_exposure = []
    for username in user.get("usernames", []):
        entry = status.get(f"username|{username}", {})
        if isinstance(entry, dict):
            username_exposure.append({
                "username": username,
                "publicly_indexed": entry.get("publicly_indexed"),
                "confirmed": entry.get("confirmed"),
                "last_checked": entry.get("last_checked"),
                "error": entry.get("error"),
                "engine": entry.get("engine"),
            })

    phone_exposure = []
    for phone in user.get("phones", []):
        entry = status.get(f"phone|{phone}", {})
        if isinstance(entry, dict):
            phone_exposure.append({
                "phone": phone,
                "publicly_indexed": entry.get("publicly_indexed"),
                "confirmed": entry.get("confirmed"),
                "last_checked": entry.get("last_checked"),
                "error": entry.get("error"),
                "engine": entry.get("engine"),
            })

    address_exposure = None
    if user.get("address"):
        entry = status.get("address", {})
        if isinstance(entry, dict) and entry:
            address_exposure = {
                "publicly_indexed": entry.get("publicly_indexed"),
                "confirmed": entry.get("confirmed"),
                "last_checked": entry.get("last_checked"),
                "error": entry.get("error"),
                "engine": entry.get("engine"),
                "queries": entry.get("queries"),
            }

    site_scoped = []
    for key, entry in status.items():
        if not key.startswith("site_scoped|") or not isinstance(entry, dict):
            continue
        value = key.split("|", 1)[1]
        kind = "email" if "@" in value else "username"
        context = entry.get("context") if isinstance(entry.get("context"), dict) else {}
        site_scoped.append({
            "kind": kind,
            "value": value,
            "publicly_indexed": entry.get("publicly_indexed"),
            "confirmed": entry.get("confirmed"),
            "last_checked": entry.get("last_checked"),
            "sites": context.get("hits", []),
        })

    broker_rows = []
    for b in load_brokers():
        broker_rows.append({
            "id": b.get("id"),
            "name": b.get("name"),
            "status": "dry-run",
            "last_request": "",
        })

    return render_template(
        "index.html",
        profiles=profiles,
        active_profile=selected,
        profile_meta={"mode": meta.get("last_run_mode")},
        last_run=meta.get("last_run_finished") or meta.get("last_run_started"),
        user=user,
        change_log=changes,
        exposure=exposure,
        username_exposure=username_exposure,
        phone_exposure=phone_exposure,
        address_exposure=address_exposure,
        site_scoped=site_scoped,
        brokers=broker_rows,
    )

@app.route("/run", methods=["POST"])
def run_now():
    profile = request.form.get("profile")
    if profile and profile not in list_profiles():
        return redirect(url_for("index"))

    # run single profile if provided, else all
    run_profiles(selected_profile=profile or None, retry_only=False, run_mode="core")
    return redirect(url_for("index", profile=profile) if profile else url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
