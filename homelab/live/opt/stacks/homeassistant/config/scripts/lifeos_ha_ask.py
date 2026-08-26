#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone

CONFIG = Path("/config")
QUESTION_FILE = CONFIG / "lifeos_ask_question.txt"
ANSWER_JSON = CONFIG / "lifeos_ask_answer.json"
ANSWER_TXT = CONFIG / "lifeos_ask_answer.txt"

question = QUESTION_FILE.read_text().strip() if QUESTION_FILE.exists() else ""

payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "question": question,
    "answer": "",
    "status": "received_in_ha_container" if question else "blocked_no_question",
    "mode": "ha_container_bridge_test",
    "write_actions_enabled": False
}

payload["answer"] = (
    "HA Ask button works. Question received: " + question
    if question else
    "No question entered."
)

ANSWER_JSON.write_text(json.dumps(payload, indent=2))
ANSWER_TXT.write_text(payload["answer"])
print(payload["answer"][:255])
