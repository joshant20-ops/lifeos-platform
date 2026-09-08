from pathlib import Path

p = Path("governor/scripts/deploy-autonomous-agent-pi5.sh")
s = p.read_text()
start = s.index("BROKER_REQ=$(python3 - <<'PY'\n")
end_marker = "PY\n\nprintf '\\n===== 6/8 — UI + PRIVACY FAIL-CLOSED =====\\n'"
end = s.index(end_marker, start)
new = r'''BROKER_REQ=$(python3 - <<'PY'
import json
print(json.dumps({
    "model": "lifeos-engineering-normal",
    "messages": [{
        "role": "user",
        "content": "Call report_test_value with value GOVERNOR_LOCAL_TOOL_OK. Do not answer normally."
    }],
    "tools": [{
        "type": "function",
        "function": {
            "name": "report_test_value",
            "description": "Report a harmless deployment test value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"]
            }
        }
    }],
    "tool_choice": "required"
}))
PY
)
BROKER_OUT=$(curl -fsS --max-time 180 \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $(cat "$BROKER_TOKEN")" \
  -d "$BROKER_REQ" http://127.0.0.1:8790/v1/chat/completions)
python3 - "$BROKER_OUT" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert j['lifeos_privacy']=='normal', j
assert j['lifeos_provider']=='ollama', j
choice=j['choices'][0]
assert choice['finish_reason']=='tool_calls', choice
calls=choice['message'].get('tool_calls') or []
match=None
for call in calls:
    fn=call.get('function') or {}
    if fn.get('name') != 'report_test_value':
        continue
    args=fn.get('arguments') or '{}'
    if isinstance(args,str):
        args=json.loads(args)
    if args.get('value') == 'GOVERNOR_LOCAL_TOOL_OK':
        match=call
        break
assert match is not None, calls
print('BROKER_AUTHENTICATED_LOCAL_TOOL_CALL=PASS')
print('BROKER_PROVIDER=ollama')
PY
'''
p.write_text(s[:start] + new + s[end + 3:])
