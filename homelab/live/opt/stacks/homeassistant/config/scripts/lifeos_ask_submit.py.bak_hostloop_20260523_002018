#!/usr/bin/env python3
import sys, json, time
from pathlib import Path

HA = Path("/config")
q = " ".join(sys.argv[1:]).strip()
now = int(time.time())

data = {
  "ok": None,
  "status": "thinking",
  "question": q,
  "question_time": now,
  "answer": "Thinking...",
  "answer_time": 0,
  "route": "local_only"
}

(HA / "lifeos_ask_request.json").write_text(json.dumps({
  "question": q,
  "question_time": now
}, indent=2))

(HA / "lifeos_ask_answer.json").write_text(json.dumps(data, indent=2))
print(json.dumps(data))
