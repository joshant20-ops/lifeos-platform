#!/usr/bin/env bash
set -Eeuo pipefail

# #759 boundary diagnostic. Run before OpenHands so a 900s agent timeout cannot
# hide whether Engineer can reach the exact Governor OpenAI-compatible endpoint.
# This intentionally reads the existing Engineer broker config remotely and never
# prints its token. Added after controlled run 35531936975 reached OpenHands SDK
# startup on aligned deployed code but emitted no action before the 900s ceiling.
echo 'ENGINEER_BROKER_PROBE=START'
ssh -o BatchMode=yes -o ConnectTimeout=8 Engineer 'bash -s' <<'REMOTE'
set -Eeuo pipefail
cfg="$HOME/.config/lifeos/governor-broker.env"
[[ -f "$cfg" && ! -L "$cfg" ]] || { echo 'ENGINEER_BROKER_CONFIG=FAIL'; exit 20; }
url=$(sed -n 's/^LIFEOS_GOVERNOR_BROKER_URL=//p' "$cfg" | tail -1)
token=$(sed -n 's/^LIFEOS_GOVERNOR_BROKER_TOKEN=//p' "$cfg" | tail -1)
[[ -n "$url" && -n "$token" ]] || { echo 'ENGINEER_BROKER_CONFIG=FAIL'; exit 20; }
echo 'ENGINEER_BROKER_CONFIG=PASS'
python3 - "$url" "$token" <<'PY'
import json,sys,urllib.request,urllib.error,time
url=sys.argv[1].rstrip('/')+'/v1/chat/completions'; token=sys.argv[2]
def call(payload,label):
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
    t=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=90) as r:
            body=json.load(r)
    except Exception as e:
        print(f'{label}=FAIL type={type(e).__name__}')
        raise
    print(f'{label}=PASS elapsed_s={time.monotonic()-t:.1f}')
    return body
base={'model':'openai/lifeos-local-only-normal','messages':[{'role':'user','content':'Reply with exactly BROKER_BASIC_PASS'}],'temperature':0}
body=call(base,'ENGINEER_BROKER_BASIC')
content=((body.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
if 'BROKER_BASIC_PASS' not in content:
    print('ENGINEER_BROKER_BASIC_ASSERTION=FAIL'); sys.exit(31)
print('ENGINEER_BROKER_BASIC_ASSERTION=PASS')
tool={'type':'function','function':{'name':'lifeos_probe','description':'Return a diagnostic marker','parameters':{'type':'object','properties':{'marker':{'type':'string'}},'required':['marker']}}}
payload={'model':'openai/lifeos-local-only-normal','messages':[{'role':'user','content':'Call lifeos_probe exactly once with marker BROKER_TOOL_PASS. Do not answer normally.'}],'tools':[tool],'tool_choice':'required','temperature':0}
body=call(payload,'ENGINEER_BROKER_TOOL')
msg=((body.get('choices') or [{}])[0].get('message') or {})
calls=msg.get('tool_calls') or []
if not calls:
    print('ENGINEER_BROKER_TOOL_ASSERTION=FAIL reason=no_tool_calls'); sys.exit(32)
args=calls[0].get('function',{}).get('arguments','{}')
try: parsed=json.loads(args)
except Exception: parsed={}
if calls[0].get('function',{}).get('name')!='lifeos_probe' or parsed.get('marker')!='BROKER_TOOL_PASS':
    print('ENGINEER_BROKER_TOOL_ASSERTION=FAIL reason=wrong_tool_call'); sys.exit(33)
print('ENGINEER_BROKER_TOOL_ASSERTION=PASS')
PY
REMOTE
echo 'ENGINEER_BROKER_PROBE=PASS'
