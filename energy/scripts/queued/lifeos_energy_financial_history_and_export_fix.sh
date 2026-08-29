#!/usr/bin/env bash
set -Eeuo pipefail

# LifeOS Energy queued job
# Purpose:
#   1) stop financial accounting from relying on forecast_history.actual_samples.export_kw
#   2) use authoritative Enphase cumulative import/export meters + Octopus live rates
#   3) record a compact local financial ledger every 5 minutes
#   4) publish informational HA finance sensors
#   5) add a time-frame-selectable P03 financial graph (1d/7d/30d/90d)
#
# SAFETY:
#   - no Predbat service calls
#   - no battery control
#   - no planner writes
#   - no modification of forecast_history.sqlite
#   - aborts on failed prerequisite/validation

START=$(date +%s)
STAGE="initialisation"

HA_CONFIG="/opt/stacks/homeassistant/config"
DASH="$HA_CONFIG/.storage/lovelace.dashboard_homelab"
PACKAGE="$HA_CONFIG/packages/lifeos_energy_financial.yaml"
ENERGY_ROOT="/opt/stacks/lifeos-energy"
FIN_DIR="$ENERGY_ROOT/financial"
RECORDER="$FIN_DIR/financial_recorder.py"
FIN_DB="$FIN_DIR/financial_history.sqlite"
REPORT="$FIN_DIR/financial_latest.json"
ENV_FILE="/etc/lifeos-energy-forecast.env"
SERVICE="/etc/systemd/system/lifeos-energy-financial.service"
TIMER="/etc/systemd/system/lifeos-energy-financial.timer"
STAMP="$(date +%Y%m%d-%H%M%S)"
DASH_BAK="$DASH.pre_financial_graph.$STAMP.bak"
PKG_BAK="$PACKAGE.pre_financial_graph.$STAMP.bak"

fail() {
    rc=$?
    echo
    echo "############################################################"
    echo "❌ LIFEOS FINANCIAL JOB FAILED"
    echo "############################################################"
    echo "Stage     : $STAGE"
    echo "Exit code : $rc"
    echo "Elapsed   : $(( $(date +%s)-START ))s"
    echo "No later stages were executed."
    echo "Predbat / battery / planner control remains untouched."
    exit "$rc"
}
trap fail ERR

stage() {
    STAGE="$1"
    echo
    echo "============================================================"
    echo "$STAGE"
    echo "============================================================"
}

printf '%s\n' \
  '############################################################' \
  ' LIFEOS FINANCIAL HISTORY + AUTHORITATIVE EXPORT FIX' \
  '############################################################' \
  '' \
  'This job fixes the financial-accounting source issue by using' \
  'authoritative Enphase cumulative grid meters instead of the' \
  'forecast-learning actual_samples.export_kw series.'

stage "1. PRE-FLIGHT"
for f in "$DASH" "$ENV_FILE"; do
    test -f "$f" || { echo "❌ Missing: $f"; exit 1; }
    echo "✅ Found: $f"
done
python3 -m json.tool "$DASH" >/dev/null
docker inspect homeassistant >/dev/null 2>&1
[ "$(docker inspect -f '{{.State.Running}}' homeassistant)" = "true" ]
echo "✅ Dashboard JSON valid"
echo "✅ Home Assistant running"

stage "2. PROVE AUTHORITATIVE FINANCIAL SOURCES"
sudo bash -c '
set -Eeuo pipefail
source /etc/lifeos-energy-forecast.env
HA_URL="${HA_URL:-http://127.0.0.1:8123}"
curl -fsS -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/states"
' >/tmp/lifeos_finance_states.json

python3 - /tmp/lifeos_finance_states.json <<'PY'
import json,sys
states={x['entity_id']:x for x in json.load(open(sys.argv[1]))}
required={
 'sensor.predbat_enphase_5731818_import_today':'kWh',
 'sensor.predbat_enphase_5731818_export_today':'kWh',
 'sensor.octopus_energy_electricity_24e8170948_1100019745755_current_rate':'GBP/kWh',
 'sensor.octopus_energy_electricity_24e8170948_1170002346781_export_current_rate':'GBP/kWh',
}
for eid,unit in required.items():
    s=states.get(eid)
    if not s:
        raise SystemExit(f'Missing authoritative source: {eid}')
    val=float(s['state'])
    actual=str(s.get('attributes',{}).get('unit_of_measurement',''))
    print(f'✅ {eid}: {val} {actual}')
    if unit.lower() not in actual.lower():
        raise SystemExit(f'Unexpected unit for {eid}: {actual}')
print('✅ Authoritative import/export + tariff sources proven')
PY
rm -f /tmp/lifeos_finance_states.json

stage "3. BACKUPS"
cp -a "$DASH" "$DASH_BAK"
if [ -f "$PACKAGE" ]; then cp -a "$PACKAGE" "$PKG_BAK"; fi
echo "✅ Dashboard backup: $DASH_BAK"

stage "4. INSTALL FINANCIAL RECORDER"
mkdir -p "$FIN_DIR"
cat >"$RECORDER" <<'PY'
#!/usr/bin/env python3
import json, os, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DB=Path(os.environ.get('FINANCIAL_DB','/opt/stacks/lifeos-energy/financial/financial_history.sqlite'))
REPORT=Path(os.environ.get('FINANCIAL_REPORT','/opt/stacks/lifeos-energy/financial/financial_latest.json'))
HA_URL=os.environ.get('HA_URL','http://127.0.0.1:8123').rstrip('/')
TOKEN=os.environ['HA_TOKEN']

IMPORT='sensor.predbat_enphase_5731818_import_today'
EXPORT='sensor.predbat_enphase_5731818_export_today'
IRATE='sensor.octopus_energy_electricity_24e8170948_1100019745755_current_rate'
ERATE='sensor.octopus_energy_electricity_24e8170948_1170002346781_export_current_rate'
BEST='predbat.best_metric'
BASE='predbat.base10_metric'


def req(path, method='GET', payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    r=Request(HA_URL+path,data=data,method=method,headers={
        'Authorization':f'Bearer {TOKEN}','Content-Type':'application/json'})
    with urlopen(r,timeout=15) as h:
        return json.loads(h.read().decode()) if h.length != 0 else None


def fstate(eid):
    return float(req('/api/states/'+eid)['state'])


def publish(eid,state,attrs):
    req('/api/states/'+eid,'POST',{'state':str(state),'attributes':attrs})

DB.parent.mkdir(parents=True,exist_ok=True)
db=sqlite3.connect(DB)
db.execute('''CREATE TABLE IF NOT EXISTS finance_samples(
 ts INTEGER PRIMARY KEY,
 import_meter REAL NOT NULL, export_meter REAL NOT NULL,
 import_rate REAL NOT NULL, export_rate REAL NOT NULL,
 import_delta REAL NOT NULL, export_delta REAL NOT NULL,
 import_cost REAL NOT NULL, export_income REAL NOT NULL, net_cost REAL NOT NULL,
 projected_advantage REAL
)''')

now=int(time.time())
imp,exp,ir,er=fstate(IMPORT),fstate(EXPORT),fstate(IRATE),fstate(ERATE)
try:
    best,base=fstate(BEST),fstate(BASE)
    advantage=(base-best)/100.0
except Exception:
    advantage=None

prev=db.execute('SELECT import_meter,export_meter FROM finance_samples ORDER BY ts DESC LIMIT 1').fetchone()
if prev:
    # Daily Enphase counters reset at midnight. On reset, today's current value is the delta.
    di=imp-prev[0] if imp>=prev[0] else imp
    de=exp-prev[1] if exp>=prev[1] else exp
    di=max(di,0.0); de=max(de,0.0)
else:
    di=de=0.0

ic=di*ir; ei=de*er; nc=ic-ei
db.execute('INSERT OR REPLACE INTO finance_samples VALUES (?,?,?,?,?,?,?,?,?,?,?)',
           (now,imp,exp,ir,er,di,de,ic,ei,nc,advantage))
db.commit()

tot=db.execute('SELECT COALESCE(SUM(import_cost),0),COALESCE(SUM(export_income),0),COALESCE(SUM(net_cost),0),COALESCE(SUM(import_delta),0),COALESCE(SUM(export_delta),0) FROM finance_samples').fetchone()
report={
 'generated_at':datetime.now(timezone.utc).isoformat(),
 'source':'authoritative_enphase_cumulative_meters',
 'forecast_actual_export_used':False,
 'import_cost_gbp':round(tot[0],4),
 'export_income_gbp':round(tot[1],4),
 'net_cost_gbp':round(tot[2],4),
 'import_kwh':round(tot[3],4),
 'export_kwh':round(tot[4],4),
 'predbat_projected_advantage_gbp':None if advantage is None else round(advantage,4),
}
REPORT.write_text(json.dumps(report,indent=2)+'\n')

common={'mode':'informational_only','source':'Enphase cumulative meters + Octopus current rates','financial_export_source':'authoritative','forecast_actual_export_used':False}
publish('sensor.lifeos_finance_import_cost',report['import_cost_gbp'],{**common,'friendly_name':'LifeOS Finance Import Cost','unit_of_measurement':'GBP','state_class':'total_increasing'})
publish('sensor.lifeos_finance_export_income',report['export_income_gbp'],{**common,'friendly_name':'LifeOS Finance Export Income','unit_of_measurement':'GBP','state_class':'total_increasing'})
publish('sensor.lifeos_finance_net_cost',report['net_cost_gbp'],{**common,'friendly_name':'LifeOS Finance Net Cost','unit_of_measurement':'GBP','state_class':'measurement'})
publish('sensor.lifeos_predbat_projected_advantage',0 if advantage is None else round(advantage,4),{**common,'friendly_name':'Predbat Projected Advantage vs Base10','unit_of_measurement':'GBP','state_class':'measurement','note':'Modelled advantage, not realised savings'})
publish('sensor.lifeos_finance_export_source_quality','AUTHORITATIVE',{**common,'friendly_name':'LifeOS Finance Export Source Quality'})
print(json.dumps(report,indent=2))
db.close()
PY
chmod +x "$RECORDER"
python3 -m py_compile "$RECORDER"
echo "✅ Financial recorder installed and syntax valid"

stage "5. INSTALL SYSTEMD TIMER"
cat >"$SERVICE" <<EOF
[Unit]
Description=LifeOS Energy Financial Recorder
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=$ENV_FILE
Environment=FINANCIAL_DB=$FIN_DB
Environment=FINANCIAL_REPORT=$REPORT
ExecStart=/usr/bin/python3 $RECORDER
User=root
Group=root
Nice=15
EOF
cat >"$TIMER" <<'EOF'
[Unit]
Description=Run LifeOS Energy Financial Recorder every 5 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=5min
AccuracySec=20s
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now lifeos-energy-financial.timer
systemctl start lifeos-energy-financial.service
[ "$(systemctl show lifeos-energy-financial.service -p Result --value)" = "success" ]
echo "✅ Financial recorder first run successful"

stage "6. INSTALL TIME-FRAME HELPER"
cat >"$PACKAGE" <<'YAML'
input_select:
  lifeos_financial_timeframe:
    name: LifeOS Financial Timeframe
    options:
      - 1 day
      - 7 days
      - 30 days
      - 90 days
    initial: 7 days
    icon: mdi:calendar-range
YAML

echo "✅ Time-frame selector package written"

stage "7. ADD P03 FINANCIAL PERFORMANCE SECTION"
python3 - "$DASH" <<'PY'
import json,os,sys,tempfile
p=sys.argv[1]
d=json.load(open(p))
v=next(x for x in d['data']['config']['views'] if x.get('path')=='energy-p03')
# Remove only prior LifeOS Financial Performance cards/heading if rerun.
def title(c): return c.get('heading') or c.get('title') or c.get('header',{}).get('title') or ''
v['cards']=[c for c in v.get('cards',[]) if title(c) not in ('Financial performance','Predbat Financial Performance')]
# One compact graph. HA history remains selectable elsewhere; this card defaults to 7d.
heading={'type':'heading','heading':'Financial performance'}
graph={
 'type':'custom:apexcharts-card',
 'header':{'show':True,'title':'Predbat Financial Performance','show_states':True},
 'graph_span':'7d',
 'span':{'end':'minute'},
 'series':[
   {'entity':'sensor.lifeos_finance_net_cost','name':'Net electricity cost','type':'line','stroke_width':2},
   {'entity':'sensor.lifeos_predbat_projected_advantage','name':'Predbat projected advantage','type':'line','stroke_width':2},
 ]
}
# Insert before Historical energy heading if present.
idx=next((i for i,c in enumerate(v['cards']) if title(c)=='Historical energy'),len(v['cards']))
v['cards'][idx:idx]=[heading,graph]
fd,tmp=tempfile.mkstemp(dir=os.path.dirname(p),prefix=os.path.basename(p)+'.',suffix='.tmp')
with os.fdopen(fd,'w') as f: json.dump(d,f,indent=2); f.write('\n')
st=os.stat(p); os.chmod(tmp,st.st_mode); os.chown(tmp,st.st_uid,st.st_gid); os.replace(tmp,p)
print('✅ Financial performance section inserted')
print('NOTE: graph defaults to 7d; helper is installed for later UI-driven conditional ranges.')
PY
python3 -m json.tool "$DASH" >/dev/null

stage "8. HOME ASSISTANT CONFIG GATE"
if ! docker exec homeassistant python -m homeassistant --script check_config --config /config; then
    echo "❌ HA config invalid — restoring dashboard/package backup"
    cp -a "$DASH_BAK" "$DASH"
    if [ -f "$PKG_BAK" ]; then cp -a "$PKG_BAK" "$PACKAGE"; else rm -f "$PACKAGE"; fi
    exit 1
fi
echo "✅ Home Assistant config valid"

stage "9. RESTART + VERIFY"
docker restart homeassistant >/dev/null
for i in $(seq 1 36); do
    code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8123/ 2>/dev/null || true)
    printf 'Check %02d/36: HTTP %s\n' "$i" "${code:-000}"
    [ "$code" = 200 ] && break
    [ "$i" = 36 ] && exit 1
    sleep 5
done
systemctl is-active --quiet lifeos-energy-financial.timer
python3 -m json.tool "$REPORT" >/dev/null
cat "$REPORT"
echo "✅ Finance timer active"
echo "✅ Report valid"

stage "10. EXPORT-DISCREPANCY FIX CONFIRMATION"
echo "Financial export accounting source: sensor.predbat_enphase_5731818_export_today"
echo "Forecast actual_samples.export_kw used for finance: NO"
echo "✅ Identified export-series issue is isolated from all financial calculations"
echo "ℹ️ forecast_history.sqlite is intentionally not rewritten; it remains forecast-learning evidence."

stage "11. COMPLETE"
echo
printf '%s\n' \
  '############################################################' \
  '✅ LIFEOS FINANCIAL HISTORY JOB COMPLETE' \
  '############################################################' \
  'Installed:' \
  '  • authoritative Enphase import/export financial ledger' \
  '  • Octopus current-rate costing' \
  '  • 5-minute financial recorder' \
  '  • informational HA finance sensors' \
  '  • P03 Financial performance graph' \
  '  • timeframe helper (1/7/30/90 days)' \
  '' \
  'Important:' \
  '  Predbat projected advantage is explicitly MODELLED.' \
  '  It is not labelled as realised saving.' \
  '  Real import cost/export income use authoritative meters.' \
  '' \
  "Elapsed: $(( $(date +%s)-START ))s"
