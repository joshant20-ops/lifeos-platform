import traceback
#!/usr/bin/env python3
import json
import subprocess
import sys
sys.path.insert(0, '/home/joshan/automation')
from lifeos_ask.lifeos_local_paperless_lookup import paperless_search, paperless_memory_first
import sys
from pathlib import Path
from datetime import datetime, timezone

# Z97 AUTHORISED PA WORKER CLIENT
try:
    from z97_pa_worker_client import answer_from_pa_worker
except Exception:
    answer_from_pa_worker = None


BASE = Path("/home/joshan/automation")
LOGS = BASE / "logs"
LOGS.mkdir(parents=True, exist_ok=True)

QUESTION_FILE = Path("/opt/stacks/homeassistant/config/lifeos_ask_question.txt")
ANSWER_JSON = Path("/opt/stacks/homeassistant/config/lifeos_ask_answer.json")
ANSWER_TXT = Path("/opt/stacks/homeassistant/config/lifeos_ask_answer.txt")
ASK_TRIGGER_FILE = Path("/opt/stacks/homeassistant/config/lifeos_ask_trigger.txt")
CONTEXT_JSON = LOGS / "lifeos_ask_context.json"
HISTORY = LOGS / "lifeos_ask_history.jsonl"

PA = BASE / "pa_request.sh"
ENGINEER = BASE / "engineer_request.sh"
AUDIT = BASE / "chat_audit_request.sh"

# PARKED 2026-05-06: raw Ollama access forbidden from Pi5 Steward/LifeOS Ask
# Use /home/joshan/automation/config/z97_worker_endpoints.json instead.
LOCAL_OLLAMA = None
MINI_MODEL = "tinyllama"


# LIFEOS_STEWARD_SEMANTIC_CONTRACT_READER_V1

# LIFEOS_CANONICAL_SEMANTIC_ROUTER_IMPORT_V1
def lifeos_try_canonical_semantic_router_v1(question):
    """
    Canonical semantic/useful-information router.
    Production replacement path for PA temporary semantic route patch.
    Safety: read-only, no accepted fact mutation, no Paperless writeback.
    """
    try:
        import importlib.util
        from pathlib import Path
        router_path = Path("/home/joshan/automation/lifeos_ask/lifeos_canonical_semantic_query_router_v1.py")
        spec = importlib.util.spec_from_file_location("lifeos_canonical_semantic_query_router_v1", str(router_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out = mod.route(question)
        if isinstance(out, dict) and out.get("ok") is True:
            out["route"] = "canonical_semantic_query_router_v1"
            out["production_replacement_for"] = "pa_patch_semantic_gold_route_v1"
            return out
    except Exception:
        return None
    return None

def lifeos_load_steward_semantic_contract_v1():
    """
    Read-only Steward semantic extraction contract loader.

    Safety:
    - no PA imports
    - no accepted fact mutation
    - no Paperless writeback
    - no execution
    - file/state contract only
    """
    from pathlib import Path
    import json
    from datetime import datetime

    contract_path = Path("/home/joshan/automation/lifeos_state/steward_semantic_extractor_contract_v1.json")
    status_path = Path("/home/joshan/automation/logs/steward_semantic_contract_reader_status_v1.json")
    www_status_path = Path("/opt/stacks/homeassistant/config/www/lifeos/steward_semantic_contract_reader_status_v1.json")

    status = {
        "ok": False,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "contract_path": str(contract_path),
        "contract_exists": contract_path.exists(),
        "contract_loaded": False,
        "runtime_steward_code_changed": True,
        "read_only_loader": True,
        "accepted_facts_mutated": False,
        "paperless_writeback_performed": False,
        "execution_performed": False,
        "pa_runtime_import": False,
    }

    contract = {}
    try:
        if contract_path.exists():
            contract = json.loads(contract_path.read_text())
            status["contract_loaded"] = True
            status["ok"] = True
            status["schema"] = contract.get("schema")
            status["semantic_template_count"] = len(contract.get("semantic_type_templates", []))
            status["hard_safety_rule_count"] = len(contract.get("hard_safety_rules", []))
    except Exception as e:
        status["error"] = str(e)

    try:
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True))
        www_status_path.parent.mkdir(parents=True, exist_ok=True)
        www_status_path.write_text(json.dumps(status, indent=2, sort_keys=True))
    except Exception:
        pass

    return contract, status
# END LIFEOS_STEWARD_SEMANTIC_CONTRACT_READER_V1



# LIFEOS_USEFUL_INFO_FAST_PATH_V1
def lifeos_useful_information_fast_path_v1(question):
    """
    Fast path for broad useful-information questions.

    Purpose:
    Avoid slow generic Ask/LLM/Paperless route for questions like:
    "What useful information does LifeOS know?"

    Safety:
    - reads render-only semantic JSON
    - no accepted fact mutation
    - no Paperless writeback
    - no execution
    - no PA import
    """
    q = str(question or "").lower().strip()

    broad_phrases = [
        "what useful information",
        "useful information",
        "what does lifeos know",
        "what information does lifeos know",
        "show useful information",
        "important information",
    ]

    if not any(p in q for p in broad_phrases):
        return None

    import json
    from pathlib import Path
    from datetime import datetime

    source = Path("/home/joshan/automation/logs/lifeos_rendered_useful_information_semantic_v1.json")
    fallback = Path("/home/joshan/automation/logs/lifeos_rendered_useful_information_balanced_confidence.json")
    status_path = Path("/home/joshan/automation/logs/lifeos_useful_information_fast_path_status_v1.json")
    www_status_path = Path("/opt/stacks/homeassistant/config/www/lifeos/lifeos_useful_information_fast_path_status_v1.json")

    chosen = source if source.exists() else fallback

    out = {
        "ok": True,
        "route": "useful_information_fast_path_v1",
        "answer": "",
        "created_utc": datetime.now().isoformat(timespec="seconds"),
        "source": str(chosen),
        "accepted_facts_mutated": False,
        "paperless_writeback_performed": False,
        "execution_performed": False,
    }

    try:
        data = json.loads(chosen.read_text()) if chosen.exists() else {}
        items = data.get("items", [])[:12]

        if not items:
            answer = "No useful information items are currently available from the render-only semantic view."
        else:
            lines = ["Useful information currently visible from LifeOS:"]
            for item in items:
                title = item.get("title") or item.get("semantic_type") or "Untitled"
                family = item.get("event_family") or item.get("domain") or "general"
                semantic_type = item.get("semantic_type") or item.get("lifecycle_type") or "unknown"
                lines.append(f"• {title} — {family} / {semantic_type}")
            answer = "\n".join(lines)

        out["answer"] = answer
        out["item_count"] = len(items)

    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
        out["answer"] = "Useful information fast path failed safely."

    try:
        status_path.write_text(json.dumps(out, indent=2, sort_keys=True))
        www_status_path.parent.mkdir(parents=True, exist_ok=True)
        www_status_path.write_text(json.dumps(out, indent=2, sort_keys=True))
    except Exception:
        pass

    return out
# END LIFEOS_USEFUL_INFO_FAST_PATH_V1


def now():
    return datetime.now(timezone.utc).isoformat()

def read_question():
    q = " ".join(sys.argv[1:]).strip()
    if q:
        return q
    if QUESTION_FILE.exists():
        return QUESTION_FILE.read_text(encoding="utf-8").strip()
    return sys.stdin.read().strip()

def needs_z97(question):
    q = question.lower()

    hard_terms = [
        "homelab", "docker", "container", "watchman", "engineer",
        "z97", "proxmox", "vm", "ollama", "home assistant",
        "adguard", "network", "ssh", "service", "system",
        "cpu", "ram", "memory", "error", "alert", "paperless",
        "document", "mortgage", "calendar", "email", "tenant",
        "mot", "tax", "invoice", "writeback", "execute",
        "delete", "change", "patch", "script", "backup", "restore"
    ]

    if any(t in q for t in hard_terms):
        return True, "keyword_escalation"

    if len(question) > 240:
        return True, "long_question"

    return False, "mini_first"

def classify_z97_route(question):
    q = question.lower()
    engineer_terms = [
        "homelab", "docker", "container", "watchman", "engineer",
        "pi5", "pi 5", "z97", "proxmox", "vm", "ollama",
        "home assistant", "adguard", "network", "ssh", "service",
        "system", "cpu", "ram", "memory", "error", "alert",
        "script", "patch", "backup", "restore"
    ]
    if any(t in q for t in engineer_terms):
        return "engineer"
    return "pa"

def call_local_mini(question):
    prompt = (
        "You are the Pi5 mini chat assistant. Answer briefly. "
        "If unsure or if the question needs documents, homelab reasoning, safety review, "
        "or complex planning, return JSON with escalate=true. "
        "Return JSON only with keys: status, summary, confidence, escalate, reason.\n"
        f"Question: {question}"
    )

    payload = {
        "model": MINI_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 120,
            "temperature": 0
        }
    }

    try:
        import urllib.request
        req = urllib.request.Request(
            LOCAL_OLLAMA,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read().decode("utf-8", errors="replace")
        outer = json.loads(raw)
        text = outer.get("response", "").strip()
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = {
                "status": "ok",
                "summary": text,
                "confidence": "medium",
                "escalate": False,
                "reason": "mini_plain_response"
            }
        return {
            "ok": True,
            "route": "pi5_mini_llm",
            "model": MINI_MODEL,
            "response": parsed,
            "raw_response": text
        }
    except Exception as e:
        return {
            "ok": False,
            "route": "pi5_mini_llm",
            "error": str(e),
            "response": {
                "status": "error",
                "summary": "",
                "confidence": "low",
                "escalate": True,
                "reason": "mini_failed"
            }
        }

def run_z97(route, question):
    wrapper = ENGINEER if route == "engineer" else PA
    prompt = (
        f"LifeOS Ask escalated from Pi5 mini LLM to Z97 {route.upper()} agent. "
        "Return JSON only. Do not execute. Do not write back. "
        "If action is needed, produce recommendations only and mark watchman_required=true. "
        f"User question: {question}"
    )
    result = subprocess.run(
        [str(wrapper), prompt],
        text=True,
        capture_output=True,
        timeout=1200
    )
    try:
        return json.loads(result.stdout.strip())
    except Exception:
        return {
            "ok": False,
            "error": "non_json_z97_output",
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-2000:]
        }

def run_audit_if_needed(question, answer_summary, escalated):
    if not escalated:
        return {
            "ok": True,
            "skipped": True,
            "reason": "mini_answer_no_audit_needed"
        }

    prompt = (
        "Audit this Pi5-facing answer. Check correctness, missing risk, and whether "
        "it should be amended. Return JSON only. "
        f"Question: {question}\nAnswer: {answer_summary}"
    )
    result = subprocess.run(
        [str(AUDIT), prompt],
        text=True,
        capture_output=True,
        timeout=1200
    )
    try:
        return json.loads(result.stdout.strip())
    except Exception:
        return {
            "ok": False,
            "error": "audit_non_json_output",
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-1000:]
        }


def clean_mini_summary(text):
    import json
    import re

def classify_candidate_value(v):
    import re

    raw = str(v).strip()
    cleaned = "".join(c for c in raw if c.isalnum())
    low = raw.lower()

    result = {
        "raw": raw,
        "cleaned": cleaned,
        "type": "unknown",
        "confidence": 0
    }

    # postcode
    if re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}", cleaned, re.I):
        result["type"] = "postcode"
        result["confidence"] = 95
        return result

    # date
    if re.fullmatch(r"\d{1,2}/\d{4}", raw):
        result["type"] = "date"
        result["confidence"] = 90
        return result

    if re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)", low):
        result["type"] = "date"
        result["confidence"] = 80
        return result

    # regulator ids
    if cleaned.upper().startswith("FRN") and any(c.isdigit() for c in cleaned):
        result["type"] = "regulator_id"
        result["confidence"] = 95
        return result

    # VIN
    if len(cleaned) == 17 and sum(c.isdigit() for c in cleaned) >= 4:
        result["type"] = "vin"
        result["confidence"] = 90
        return result

    # identifier
    digits = sum(c.isdigit() for c in cleaned)
    letters = sum(c.isalpha() for c in cleaned)

    if digits >= 5 and len(cleaned) >= 6:
        result["type"] = "identifier"
        result["confidence"] = 75

        if letters >= 1 and digits >= 4:
            result["confidence"] = 85

        return result

    return result



    if not text:
        return ""

    t = str(text).strip()

    # If tinyllama wraps JSON in prose, extract the first JSON object.
    m = re.search(r'\{.*\}', t, flags=re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            summary = obj.get("summary")
            if summary:
                return str(summary).strip()
        except Exception:
            pass

    # Remove common prompt echo clutter.
    t = re.sub(r'^Question:\s*["“]?', '', t, flags=re.I).strip()
    t = re.sub(r'["”]?\s*JSON response:\s*', ' ', t, flags=re.I).strip()

    # Keep only first sensible line for casual mini chat.
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    if lines:
        t = lines[0]

    return t[:500].strip()

def extract_summary(result):
    try:
        return result["llm"]["response"].get("summary", "")
    except Exception:
        pass
    try:
        summary = result["response"].get("summary", "")
        if result.get("route") == "pi5_mini_llm":
            return clean_mini_summary(summary or result.get("raw_response", ""))
        return summary
    except Exception:
        pass
    return json.dumps(result)[:1000]



def fact_engine_first(question):
    """
    P07_DOCUMENT_FIRST — Step 0 in the answer pipeline.

    Calls lifeos_document_fact_engine.answer() against the local
    paperless_document_inventory.json snapshot.  No Docker exec.
    No network call.  Returns in < 100 ms for all 51 docs.

    Returns the engine result dict if ok=True and answer is non-empty.
    Returns None on any failure or empty result so the caller falls
    through to the existing paperless_memory_first() path unchanged.

    Contract:
    - Read-only. No writebacks. No execution.
    - Does not bypass Watchman — execution_performed stays False.
    - Route tag: "pi5_fact_engine_first" for audit trail.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lifeos_document_fact_engine",
            str(BASE / "lifeos_ask" / "lifeos_document_fact_engine.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.answer(question)
    except Exception:
        return None

    if not result:
        return None
    if not result.get("ok"):
        return None

    answer_text = (result.get("answer") or "").strip()
    if not answer_text:
        return None

    out = {
        "ok": True,
        "created_utc": now(),
        "route": "pi5_fact_engine_first",
        "question": question,
        "selected_agent": "lifeos_document_fact_engine_inventory_first_v2",
        "escalated_to_z97": False,
        "answer_summary": answer_text,
        "answer": answer_text,
        "writeback_performed": False,
        "execution_performed": False,
        "watchman_required_for_execution": False,
        "review_required": False,
        "status": "answered",
        "engine_result": result,
        "fact_engine_domain": result.get("domain"),
        "fact_engine_source_docs": result.get("source_docs", [])[:3],
    }

    ANSWER_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    ANSWER_TXT.write_text(answer_text, encoding="utf-8")

    log_dir = BASE / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "created_utc": out["created_utc"],
        "question": question,
        "answer": answer_text,
        "route": out["route"],
        "pa_review_status": "pending",
        "audit_review_status": "pending",
        "purpose": "Fact-engine-first answer. PA and auditor should confirm or flag."
    }
    with (log_dir / "lifeos_ask_answer_audit_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(audit) + "\n")
    (log_dir / "lifeos_ask_answer_audit_latest.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )

    return out

def local_first_answer_if_needed(question):
    q = (question or "").lower()
    keywords = ["mortgage", "account number", "mot", "insurance", "policy", "provider", "renewal", "paperless", "document", "bupa", "medical", "health", "dentist", "optician", "cover", "emergency", "breakdown", "account", "reference"]
    if not any(k in q for k in keywords):
        return None

    

    # P07_DOCUMENT_FIRST — try inventory-based fact engine before Docker exec.
    engine_out = fact_engine_first(question)
    if engine_out:
        return engine_out

    # Fall through to live Paperless lookup (Docker exec path).
    lookup = paperless_memory_first(question)

    try:
        top = lookup.get("top_match") or {}
        preview = top.get("content_preview","")

        answer_lines = []

        q = question.lower()

        import re

        def clean(v):
            return re.sub(r"\s+", " ", str(v or "")).strip(" :-\n\t")

        def add(label, value):
            value = clean(value)
            if value and value.lower() not in ["none", "unknown", "n/a"]:
                answer_lines.append(f"• {label}: {value}")

        text = preview or ""
        text_l = text.lower()

        # Generic entity/provider extraction.
        provider_candidates = []
        for name in [
            "Hastings Direct", "Aviva", "Aviva Zero", "Aldermore", "Bupa",
            "Churchill", "Simply Business", "247 Home Rescue", "DAS",
            "Lloyds Bank", "Royal Mail", "HMRC"
        ]:
            if name.lower() in text_l:
                provider_candidates.append(name)

        # Generic identifiers: label-first extraction, with false-value rejection.
        bad_values = {
            "agency", "specification", "number", "policy", "date", "reference",
            "document", "page", "company", "product", "premium", "amount",
            "total", "schedule", "statement", "insurance"
        }

        def good_identifier(v):
            if not v:
                return False

            raw = str(v).strip()
            low = raw.lower()

            banned_words = [
                "westcott",
                "northampton",
                "newbusiness",
                "premium",
                "specification",
                "agency",
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december"
            ]

            if any(x in low for x in banned_words):
                return False

            if "£" in raw:
                return False

            if "." in raw and any(c.isdigit() for c in raw):
                return False

            cleaned = "".join(c for c in raw if c.isalnum())

            meta = classify_candidate_value(raw)

            if meta["type"] in [
                "postcode",
                "date",
                "regulator_id"
            ]:
                return False

            if len(cleaned) < 6:
                return False

            if len(cleaned) > 24:
                return False

            letters = sum(c.isalpha() for c in cleaned)
            digits = sum(c.isdigit() for c in cleaned)

            if digits == 0:
                return False

            if letters > digits * 2:
                return False

            return True

        policy_refs = []
        labelled_identifier_patterns = [
            r"Policy\s*(?:number|reference|no\.?)\s*[:\n ]+\s*([A-Z0-9][A-Z0-9/.-]{4,})",
            r"Account\s*(?:number|no\.?)\s*[:\n ]+\s*([0-9][0-9 ]{5,})",
            r"Reference\s*[:\n ]+\s*([A-Z0-9][A-Z0-9/.-]{4,})",
            r"Agreement\s*(?:number|reference|no\.?)\s*[:\n ]+\s*([A-Z0-9][A-Z0-9/.-]{4,})",
            r"Policy\s+([A-Z]{1,5}\d{5,}[A-Z0-9/]*)",
        ]

        for pat in labelled_identifier_patterns:
            for m in re.finditer(pat, text, re.I):
                v = clean(m.group(1))
                if good_identifier(v) and v not in policy_refs:
                    policy_refs.append(v)

        # OCR layout recovery: labels and values often split across nearby lines.
        lines = [clean(x) for x in text.splitlines() if clean(x)]
        label_words = ["policy", "account", "reference", "agreement", "number", "no"]
        candidate_ref_re = re.compile(r"^[A-Z0-9][A-Z0-9/.-]{5,}$", re.I)

        for i, line in enumerate(lines):
            lline = line.lower()
            if any(w in lline for w in label_words):
                window = lines[i+1:i+5] + lines[max(0, i-3):i]
                for w in window:
                    w2 = clean(w).replace(" ", "")
                    if good_identifier(w2) and candidate_ref_re.match(w2):
                        if w2 not in policy_refs:
                            policy_refs.append(w2)

        if not policy_refs:
            for m in re.finditer(r"\b([A-Z]{1,5}\d{5,}[A-Z0-9/]*)\b", text):
                v = clean(m.group(1))
                if good_identifier(v) and v not in policy_refs:
                    policy_refs.append(v)

        # Generic dates, preferring values near useful labels.
        dates = []
        for pat in [
            r"automatically renew on\s+(\d+(?:st|nd|rd|th)?\s+\w+\s+20\d{2})",
            r"renewal date\s+(\d+(?:st|nd|rd|th)?\s+\w+\s+20\d{2})",
            r"Due Date:\s*([0-9]{1,2}/[0-9]{1,2}/20\d{2})",
            r"start date:?\s*([0-9]{1,2}/[0-9]{1,2}/20\d{2})",
            r"issue date:?\s*(\d+(?:st|nd|rd|th)?\s+\w+\s+20\d{2})",
            r"Date:\s*([0-9]{1,2}/[0-9]{1,2}/20\d{2})",
            r"(\d+(?:st|nd|rd|th)?\s+\w+\s+20\d{2})",
            r"([0-9]{1,2}/[0-9]{1,2}/20\d{2})",
        ]:
            for m in re.finditer(pat, text, re.I):
                v = clean(m.group(1))
                if v and v not in dates:
                    dates.append(v)

        # Generic amounts, preferring labelled total/current/annual balances.
        amounts = []
        labelled_amounts = []
        for pat in [
            r"(?:total annual price|this year's total price|current balance|balance|amount due|total)\D{0,80}(£\d+(?:,\d{3})*(?:\.\d{2})?)",
            r"(£\d+(?:,\d{3})*(?:\.\d{2})?)"
        ]:
            for m in re.finditer(pat, text, re.I):
                v = clean(m.group(1))
                if v and v not in labelled_amounts:
                    labelled_amounts.append(v)
            if labelled_amounts:
                break
        amounts = labelled_amounts

        # Generic percentages/rates, avoiding useless 0.00% unless it is the only rate.
        rates_all = []
        for m in re.finditer(r"\b\d+(?:\.\d+)?%", text):
            v = clean(m.group(0))
            if v and v not in rates_all:
                rates_all.append(v)
        rates = [r for r in rates_all if r != "0.00%"] or rates_all

        # Generic vehicle registrations, guarded and false-value checked.
        regs = []
        if any(w in text_l for w in ["registration", "vehicle", "mot", "motorcycle", "car", "bike"]):
            for pat in [
                r"Registration number(?:\s+[a-z ]+)?\s*\n\s*([A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{2,3})",
                r"Vehicle:\s*([A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{2,3})",
                r"\b([A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{2,3})\b",
            ]:
                for m in re.finditer(pat, text, re.I | re.S):
                    v = clean(m.group(1)).upper()
                    if v.lower() not in bad_values and re.search(r"\d", v) and v not in regs:
                        regs.append(v)

        # Output is generic: no task-specific branches.
        if provider_candidates:
            add("Provider / organisation", provider_candidates[0])
        if policy_refs:
            add("Reference / account / policy number", policy_refs[0])
        if dates:
            add("Relevant date", dates[0])
        if amounts:
            add("Amount / price", amounts[0])
        if rates:
            add("Rate", rates[0])
        if regs:
            add("Vehicle registration", regs[0])

        answer_lines.append(
            f"• Source: Doc {top.get('document_id')} — {top.get('display_title') or top.get('title')}"
        )

        if answer_lines:
            lookup["human_answer"] = "\n".join(answer_lines)
            lookup["human_answer_mode"] = "generic_document_fact_extractor_v1"
    except Exception as e:
        lookup["human_answer_error"] = str(e)

    answer = lookup.get("answer", "Local-first lookup ran but did not return an answer.")

    out = {
        "ok": True,
        "created_utc": now(),
        "route": "pi5_local_first_review_logged",
        "question": question,
        "selected_agent": "local_paperless_first",
        "escalated_to_z97": False,
        "answer_summary": answer,
        "answer": answer,
        "writeback_performed": False,
        "execution_performed": False,
        "watchman_required_for_execution": False,
        "review_required": True,
            "status": "answered",
        "local_lookup": lookup
    }

    if isinstance(out.get("local_lookup"), dict) and out["local_lookup"].get("human_answer"):
        out["answer_summary"] = out["local_lookup"]["human_answer"]
        out["answer"] = out["local_lookup"]["human_answer"]
        out["review_required"] = False

    # Enrich normal answers with facts from related documents.
    # Relationships remain internal unless explicitly requested.
    out = lifeos_enrich_normal_answer_facts(out)

    if out.get("answer"):
        out["answer"] = lifeos_user_visible_answer_filter(out["answer"], question)
        out["answer_summary"] = lifeos_user_visible_answer_filter(out.get("answer_summary", out["answer"]), question)
        if isinstance(out.get("local_lookup"), dict):
            out["local_lookup"]["human_answer"] = out["answer"]
            out["local_lookup"]["relationship_evidence_internal"] = True
            out["local_lookup"]["relationships_hidden_unless_requested"] = True

    if isinstance(out.get("answer"), str):
        out["answer"] = out["answer"].replace("\n", "\n")
    if isinstance(out.get("answer_summary"), str):
        out["answer_summary"] = out["answer_summary"].replace("\n", "\n")

    ANSWER_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    ANSWER_TXT.write_text(answer, encoding="utf-8")

    log_dir = BASE / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "created_utc": out["created_utc"],
        "question": question,
        "answer": answer,
        "route": out["route"],
        "pa_review_status": "pending",
        "audit_review_status": "pending",
        "purpose": "PA and audit workers should confirm this local answer or explain why it was wrong."
    }
    with (log_dir / "lifeos_ask_answer_audit_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(audit) + "\n")
    (log_dir / "lifeos_ask_answer_audit_latest.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")

    return out





def lifeos_question_domain_safe_v1(question):
    q = str(question or "").lower()
    if any(x in q for x in ["bike", "motorbike", "motorcycle", "wr16"]):
        return "bike"
    if any(x in q for x in ["car", "vehicle", "registration", "ko67"]):
        return "car"
    if any(x in q for x in ["landlord", "house", "home", "property", "building"]):
        return "property"
    return "general"


def lifeos_fact_doc_allowed_safe_v1(doc, question, top_group=""):
    domain = lifeos_question_domain_safe_v1(question)
    group = str(doc.get("memory_group") or "")
    text = " ".join([
        str(doc.get("title") or ""),
        str(doc.get("display_title") or ""),
        str(doc.get("content_preview") or ""),
        " ".join(str(x) for x in doc.get("tags", [])),
        group,
    ]).lower()

    if top_group and group == top_group:
        return True

    if domain == "bike":
        return any(x in text for x in ["bike", "motorbike", "motorcycle", "wr16tfo", "hastings", "bike_insurance", "bike_mot"])

    if domain == "car":
        return any(x in text for x in ["ko67fjf", "certificate of motor insurance", "registration mark of vehicle", "darwin", "motor car"])

    if domain == "property":
        return any(x in text for x in ["landlord", "home emergency", "property", "residential landlord", "churchill", "simply business"])

    return True


def lifeos_enrich_normal_answer_facts(out):
    """
    Generic enrichment for user-facing answers.

    Uses line-based OCR layout across related matched docs.
    Relationships/evidence stay internal.
    """
    import re

    if not isinstance(out, dict):
        return out

    lookup = out.get("local_lookup") or {}
    if not isinstance(lookup, dict):
        return out

    answer = str(out.get("answer") or lookup.get("human_answer") or "")
    matches = lookup.get("matches") or []

    if not matches:
        return out

    top_match = lookup.get("top_match") or {}
    top_group = str(top_match.get("memory_group") or "")
    matches = [m for m in matches if lifeos_fact_doc_allowed_safe_v1(m, out.get("question", ""), top_group)]

    if not matches:
        return out

    # Convert literal escaped newline to real lines if present.
    answer = answer.replace("\\n", "\n")
    lines = [x.strip() for x in answer.splitlines() if x.strip()]

    def has(label):
        return label.lower() in "\n".join(lines).lower()

    def clean(v):
        return re.sub(r"\s+", " ", str(v or "")).strip(" :-\n\t")

    def doc_lines(doc):
        text = str(doc.get("content_preview") or "")
        return [clean(x) for x in text.splitlines() if clean(x)]

    def all_text(doc):
        return str(doc.get("content_preview") or "")

    def valid_ref(v):
        v = clean(v).replace(" ", "")
        if not v:
            return None
        low = v.lower()

        # Reject addresses, generic OCR junk, VINs and dates as policy/account refs.
        if any(x in low for x in ["westcott", "northampton", "hastingsdirect", "myaccount", "premium", "document"]):
            return None
        if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", v, re.I):
            return None
        if re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z]{3}", v, re.I):
            return None
        if re.fullmatch(r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}", v):
            return None

        if re.fullmatch(r"[A-Z]{1,6}[0-9]{5,}[A-Z0-9/.-]*", v, re.I):
            return v
        if re.fullmatch(r"[0-9]{6,12}", v):
            return v
        return None

    def find_ref():
        for doc in matches[:8]:
            ls = doc_lines(doc)

            # Pattern:
            # number
            # Policy
            # XA20013287635
            for i, line in enumerate(ls):
                low = line.lower()
                if low in ["policy", "policy number", "number", "reference", "account number"] or "policy number" in low:
                    window = ls[i+1:i+5]
                    for cand in window:
                        v = valid_ref(cand)
                        if v:
                            return v, doc

            # Inline patterns
            text = all_text(doc)
            for pat in [
                r"Policy\s*(?:number|reference)?\s*[:\n ]+\s*([A-Z0-9/.-]{6,})",
                r"Account\s*(?:number|No\.?|no\.?)?\s*[:\n ]+\s*([0-9]{6,})",
                r"number\s*\n\s*Policy\s*\n\s*([A-Z0-9/.-]{6,})",
            ]:
                m = re.search(pat, text, re.I | re.S)
                if m:
                    v = valid_ref(m.group(1))
                    if v:
                        return v, doc

        return None, None

    def find_date():
        for doc in matches[:8]:
            text = all_text(doc)

            # Prefer actual renewal/due dates over document issue dates.
            for pat in [
                r"automatically renew on\s+(\d+(?:st|nd|rd|th)?\s+\w+\s+20\d{2})",
                r"will\s+(\d+(?:st|nd|rd|th)?\s+\w+\s+20\d{2})\s+automatically renew",
                r"renews on\s+(\d+(?:st|nd|rd|th)?\s+\w+\s+20\d{2})",
                r"Due Date:\s*([0-9]{1,2}/[0-9]{1,2}/20\d{2})",
            ]:
                m = re.search(pat, text, re.I | re.S)
                if m:
                    return clean(m.group(1)), doc

        return None, None

    def find_amount():
        for doc in matches[:8]:
            text = all_text(doc)

            for pat in [
                r"Total annual price[\s\S]{0,160}?(£\s?[0-9,]+(?:\.[0-9]{2})?)",
                r"This year's total price[\s\S]{0,160}?(£\s?[0-9,]+(?:\.[0-9]{2})?)",
                r"Current balance[\s\S]{0,160}?(£\s?[0-9,]+(?:\.[0-9]{2})?)",
            ]:
                m = re.search(pat, text, re.I)
                if m:
                    return clean(m.group(1)), doc

        return None, None

    if not has("Reference / account / policy number"):
        ref, doc = find_ref()
        if ref:
            lines.append(f"• Reference / account / policy number: {ref}")

    # Vehicle registrations are facts, but not policy/account references.
    if not has("Vehicle registration"):
        for doc in matches[:8]:
            text = all_text(doc)
            m = re.search(r"\b([A-Z]{2}[0-9]{2}[A-Z]{3})\b", text, re.I)
            if m:
                lines.append(f"• Vehicle registration: {m.group(1).upper()}")
                break



    if not has("Relevant date"):
        date, doc = find_date()
        if date:
            lines.append(f"• Relevant date: {date}")

    if not has("Amount / price"):
        amount, doc = find_amount()
        if amount:
            lines.append(f"• Amount / price: {amount}")

    enriched = "\n".join(lines)

    out["answer"] = enriched
    out["answer_summary"] = enriched

    lookup["human_answer"] = enriched
    lookup["human_answer_mode"] = "generic_line_based_cross_doc_enrichment_v1"
    lookup["relationship_evidence_internal"] = True
    lookup["relationships_hidden_unless_requested"] = True
    out["local_lookup"] = lookup

    return out




def lifeos_strip_domain_wrong_facts_safe_v1(answer, question=""):
    import re
    domain = lifeos_question_domain_safe_v1(question)
    out = []

    for line in str(answer or "").replace("\\n", "\n").splitlines():
        raw = line.strip()
        if not raw:
            continue

        # Do not show vehicle registration for bike insurance/provider questions unless asked.
        if raw.startswith("• Vehicle registration:") and domain not in ["car", "bike"]:
            continue

        # Do not show car reg in bike answers.
        if raw.startswith("• Vehicle registration:") and domain == "bike" and "KO67FJF" in raw.upper():
            continue

        # VIN should not be shown as policy/account/reference.
        if raw.startswith("• Reference / account / policy number:"):
            val = raw.split(":", 1)[-1].strip().replace(" ", "")
            if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", val, re.I):
                continue
            if re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z]{3}", val, re.I):
                continue

        out.append(raw)

    return "\n".join(out)


def lifeos_user_visible_answer_filter(answer, question=""):
    """
    Hide relationship/evidence lines unless requested.
    Keep useful facts visible.
    """
    q = str(question or "").lower()
    answer = str(answer or "")

    wants_relationships = any(x in q for x in [
        "relationship",
        "related document",
        "related documents",
        "why did you choose",
        "supporting documents",
        "evidence",
        "show source chain",
        "document family"
    ])

    if wants_relationships:
        return answer

    hidden_phrases = [
        "relationship summary",
        "this document appears related",
        "same lifecycle",
        "same document family",
        "workflow memory",
        "relationship proposed",
        "content tab remains",
        "append-only memory",
        "supporting documents",
        "evidence chain",
        "source chain",
        "memory group:"
    ]

    kept = []

    for line in answer.splitlines():
        raw = line.strip()

        if not raw:
            continue

        low = raw.lower()

        if any(x in low for x in hidden_phrases):
            continue

        if raw.startswith("- Doc "):
            continue

        kept.append(raw)

    return "\n".join(kept) if kept else answer




def lifeos_vehicle_answer_postprocess_v1(out):
    """
    Final generic vehicle/property cleanup.

    Fixes:
    - VIN must not be shown as policy/account/reference.
    - Car insurance questions must prefer motor insurance documents over landlord/property insurance.
    - Registration questions should return vehicle registration if present.
    """
    import re

    if not isinstance(out, dict):
        return out

    q = str(out.get("question") or "").lower()
    lookup = out.get("local_lookup") or {}
    matches = lookup.get("matches") or []

    wants_car = any(x in q for x in ["car", "ko67", "vehicle registration", "car registration", "car insurance"])
    wants_reg = any(x in q for x in ["registration", "reg"])
    wants_policy = any(x in q for x in ["policy", "insurance"])
    wants_mot = "mot" in q

    def text_of(m):
        return " ".join([
            str(m.get("title") or ""),
            str(m.get("display_title") or ""),
            str(m.get("content_preview") or ""),
            " ".join(str(x) for x in m.get("tags", [])),
            str(m.get("memory_group") or ""),
        ])

    def clean_lines(ans):
        lines = []
        for raw in str(ans or "").replace("\\n", "\n").splitlines():
            line = raw.strip()
            if not line:
                continue

            if line.startswith("• Reference / account / policy number:"):
                val = line.split(":", 1)[-1].strip().replace(" ", "")
                # VIN
                if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", val, re.I):
                    continue
                # vehicle registration
                if re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z]{3}", val, re.I):
                    continue

            lines.append(line)
        return lines

    # Always remove VIN/registration masquerading as reference.
    lines = clean_lines(out.get("answer"))

    # For MOT questions, a due date + registration is enough. Do not need policy ref.
    if wants_mot:
        out["answer"] = "\n".join(lines)
        out["answer_summary"] = out["answer"]
        return out

    if wants_car:
        best = None
        best_score = -999

        for m in matches:
            t = text_of(m).lower()
            score = int(m.get("score") or 0)

            if "certificate of motor insurance" in t:
                score += 250
            if "registration mark of vehicle" in t:
                score += 200
            if "ko67fjf" in t:
                score += 200
            if "darwin" in t:
                score += 100

            # Strongly reject property/landlord docs for car questions.
            if "landlord" in t or "residential landlord" in t or "home emergency" in t:
                score -= 300

            if score > best_score:
                best_score = score
                best = m

        if best:
            txt = text_of(best)
            new_lines = []

            provider = None
            if re.search(r"\bDarwin\b", txt, re.I):
                provider = "Darwin"
            elif re.search(r"\bChurchill\b", txt, re.I):
                provider = "Churchill"
            elif re.search(r"\bU K Insurance Limited\b", txt, re.I):
                provider = "U K Insurance Limited"

            if provider:
                new_lines.append(f"• Provider / organisation: {provider}")

            if wants_policy:
                m = re.search(r"Policy Number:\s*([A-Z0-9/.-]{5,})", txt, re.I)
                if m:
                    new_lines.append(f"• Reference / account / policy number: {m.group(1).strip()}")

            m = re.search(r"Registration mark of vehicle\s+([A-Z]{2}[0-9]{2}[A-Z]{3})", txt, re.I)
            if not m:
                m = re.search(r"\b([A-Z]{2}[0-9]{2}[A-Z]{3})\b", txt, re.I)

            if m and (wants_reg or wants_car):
                new_lines.append(f"• Vehicle registration: {m.group(1).upper()}")

            new_lines.append(f"• Source: Doc {best.get('document_id')} — {best.get('title')}")

            lookup["top_match"] = best
            lookup["vehicle_postprocess_v1"] = True
            lookup["car_document_selected"] = True

            out["local_lookup"] = lookup
            out["answer"] = "\n".join(new_lines)
            out["answer_summary"] = out["answer"]
            out["review_required"] = False
            return out

    out["answer"] = "\n".join(lines)
    out["answer_summary"] = out["answer"]

    return out


def main(question_override=None):
    
    question = question_override if question_override else read_question()

    # LIFEOS_USEFUL_INFO_FAST_PATH_CALL_V3
    useful_fast = lifeos_useful_information_fast_path_v1(question)
    if useful_fast:
        return useful_fast



    if not question:
        out = {
            "ok": False,
            "status": "error",
            "error": "empty_question",
            "created_utc": now()
        }
        ANSWER_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
        ANSWER_TXT.write_text("No question provided.", encoding="utf-8")
        sys.exit(2)


    # LIFEOS_CANONICAL_SEMANTIC_ROUTER_CALL_V1
    canonical_semantic = lifeos_try_canonical_semantic_router_v1(question)
    if canonical_semantic:
        return canonical_semantic

    local_first = local_first_answer_if_needed(question)
    if local_first:
        return local_first

    force_z97, initial_reason = needs_z97(question)

    mini_result = None
    escalated = False
    selected_agent = "mini"
    escalation_reason = initial_reason

    if force_z97:
        escalated = True
    else:
        mini_result = call_local_mini(question)
        mini_response = mini_result.get("response", {})
        if mini_response.get("escalate") is True or mini_response.get("confidence") == "low":
            escalated = True
            escalation_reason = mini_response.get("reason", "mini_requested_escalation")

    if escalated:
        selected_agent = classify_z97_route(question)
        agent_result = run_z97(selected_agent, question)
        summary = extract_summary(agent_result)
    else:
        agent_result = mini_result
        summary = extract_summary(mini_result)

    audit_result = run_audit_if_needed(question, summary, escalated)

    out = {
        "ok": bool(agent_result.get("ok")),
        "created_utc": now(),
        "route": "pi5_mini_first" if not escalated else f"pi5_mini_escalated_to_z97_{selected_agent}",
        "question": question,
        "selected_agent": selected_agent,
        "escalated_to_z97": escalated,
        "escalation_reason": escalation_reason,
        "answer_summary": summary,
        "mini_result": mini_result,
        "agent_result": agent_result,
        "audit_result": audit_result,
        "writeback_performed": False,
        "execution_performed": False,
        "watchman_required_for_execution": bool(escalated)
    }

    ANSWER_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    ANSWER_TXT.write_text(summary or json.dumps(out)[:2000], encoding="utf-8")
    CONTEXT_JSON.write_text(json.dumps({
        "created_utc": out["created_utc"],
        "route": out["route"],
        "selected_agent": selected_agent,
        "escalated_to_z97": escalated,
        "escalation_reason": escalation_reason,
        "last_question": question,
        "last_answer_summary": summary,
        "audit_ok": bool(audit_result.get("ok"))
    }, indent=2), encoding="utf-8")

    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "created_utc": out["created_utc"],
            "question": question,
            "route": out["route"],
            "selected_agent": selected_agent,
            "escalated_to_z97": escalated,
            "ok": out["ok"],
            "summary": summary
        }) + "\n")

    try:
        subprocess.run(
            ["python3", str(BASE / "lifeos_z97_llm_export.py")],
            text=True,
            capture_output=True,
            timeout=30
        )
    except Exception:
        pass


    if not out["ok"]:
        sys.exit(1)

    return out

def lifeos_ask_via_z97_pa_worker(question, context=None):
    """
    Route LifeOS Ask question through authorised Z97 PA Worker.
    Safety: no execution, no writeback.
    """
    if answer_from_pa_worker is None:
        return "PA Worker client is not available."
    return answer_from_pa_worker(question, context=context or {})




def classify_candidate_type(v):
    import re

    v2 = re.sub(r"[^A-Z0-9]", "", str(v).upper())

    if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", v2):
        return "vin"

    if re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z]{3}", v2):
        return "vehicle_registration"

    if re.fullmatch(r"(POBOX|BOX)[A-Z0-9]+", v2):
        return "postal_reference"

    if re.fullmatch(r"[A-Z]{1,5}[0-9]{5,}", v2):
        return "policy_number"

    if re.fullmatch(r"[0-9]{6,12}", v2):
        return "numeric_identifier"

    if re.fullmatch(r"[0-9]{1,2}[\/\-][0-9]{1,2}[\/\-][0-9]{2,4}", v2):
        return "date"

    return "unknown"


def extract_candidate_pool(text):
    import re

    text = str(text)

    patterns = [
        r"\b[A-HJ-NPR-Z0-9]{17}\b",
        r"\b[A-Z]{2}[0-9]{2}[A-Z]{3}\b",
        r"\b[A-Z]{1,5}[0-9]{5,}\b",
        r"\b[0-9]{6,12}\b",
        r"\b(?:POBOX|Box|BOX)[A-Z0-9]+\b",
        r"\b[0-9]{1,2}[\/\-][0-9]{1,2}[\/\-][0-9]{2,4}\b",
        r"£\s?[0-9,]+(?:\.[0-9]{2})?"
    ]

    out = []
    seen = set()

    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.I):
            raw = m.group(0).strip()

            if raw in seen:
                continue

            seen.add(raw)

            out.append({
                "value": raw,
                "type": classify_candidate_type(raw),
                "position": m.start()
            })

    return out



def score_candidate(candidate, intent_group=None):
    import re

    value = str(candidate.get("value", "")).strip()
    label = str(candidate.get("label", "")).lower()

    score = 0

    if not value:
        return -999

    upper = value.upper()

    junk_patterns = [
        r'^POBOX',
        r'^NN[0-9]',
        r'^[0-9]{2}/[0-9]{4}$',
        r'^YES$',
        r'^NO$',
        r'^AGENCY$',
        r'^SPECIFICATION$',
        r'^PREMIER$',
        r'^DIRECT$',
        r'^DOCUMENT$',
    ]

    for ptn in junk_patterns:
        if re.match(ptn, upper):
            return -999

    if re.match(r'^[A-Z]{2,6}[0-9]{4,}[A-Z0-9]*$', upper):
        score += 80

    if re.match(r'^[A-HJ-NPR-Z0-9]{11,17}$', upper):
        score += 40

    if re.match(r'^[A-Z]{2}[0-9]{2}[A-Z]{3}$', upper):
        score += 30

    if any(x in label for x in [
        "policy",
        "account",
        "reference",
        "certificate",
        "member",
        "mortgage"
    ]):
        score += 25

    if any(c.isdigit() for c in value):
        score += 10

    if len(value) >= 6:
        score += 5

    return score

def best_candidate(candidates, wanted_types=None, intent_group=None):
    ranked = []

    for c in candidates:
        if wanted_types and c.get("type") not in wanted_types:
            continue

        c["score"] = score_candidate(c, intent_group)
        ranked.append(c)

    if not ranked:
        return None

    ranked.sort(key=lambda x: x["score"], reverse=True)

    return ranked[0]
















if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]).strip()

    try:
        result = main(q)
    except Exception as e:
        result = {
            "ok": False,
            "error": str(e)
        }

    print(json.dumps(result, indent=2))
