"""Dependency-free local HTTP UI/API for personal Finance F1."""
from __future__ import annotations
import json, os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse
from governor.personal_finance import PersonalFinance,Event,minor

DB=os.environ.get("LIFEOS_FINANCE_DB","/data/personal-finance.sqlite3")
APP=PersonalFinance(DB)

def money(v): return f"£{v/100:,.2f}"

HTML="""<!doctype html><html><meta name=viewport content="width=device-width,initial-scale=1"><title>LifeOS Finance</title>
<style>body{font:16px system-ui;margin:auto;max-width:900px;padding:18px;background:#111;color:#eee}section,.pot{background:#1c1c1c;padding:16px;margin:12px 0;border-radius:12px}input,select,button{font:inherit;padding:10px;margin:4px;max-width:100%;box-sizing:border-box}button{cursor:pointer}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}.bar{height:8px;background:#444;border-radius:9px}.fill{height:100%;background:#8ab4f8;border-radius:9px}small{color:#bbb}.err{color:#ff9b9b}</style>
<h1>Finance</h1><div id=summary></div>
<section><h2>Monzo category spending</h2><form id=spend><input name=period type=month required><input name=category placeholder="Monzo category" required><input name=amount type=number min=0 step=.01 placeholder="Amount spent" required><button>Post spending</button></form><div id=msg aria-live=polite></div></section>
<section><h2>Money movement</h2><form id=move><select name=kind><option value=allocation>Add to pot</option><option value=transfer>Transfer</option><option value=loan>Loan</option><option value=repayment>Repay loan</option><option value=refund>Refund</option></select><input name=pot placeholder="From / pot" required><input name=other placeholder="To pot (transfer/loan/repay)"><input name=amount type=number min=.01 step=.01 placeholder=Amount required><button>Post</button></form></section>
<section><h2>Pots</h2><form id=pot><input name=name placeholder="Pot name" required><input name=target type=number min=0 step=.01 placeholder="Goal (optional)"><input name=monthly type=number min=0 step=.01 placeholder="Monthly budget"><button>Save pot</button></form><div id=pots class=grid></div></section>
<section><h2>Category mapping</h2><form id=map><input name=category placeholder="Monzo category" required><input name=pot placeholder="Pot name" required><button>Map category</button></form></section>
<script>
const q=s=>document.querySelector(s), fmt=n=>'£'+(n/100).toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2});
async function api(path,body){let r=await fetch(path,{method:body?'POST':'GET',headers:{'content-type':'application/json'},body:body?JSON.stringify(body):null});let j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j}
async function load(){let d=await api('/api/dashboard');q('#summary').textContent=d.event_count+' posted events';q('#pots').innerHTML=d.pots.map(p=>'<div class=pot><b>'+esc(p.name)+'</b><div>'+fmt(p.balance_minor)+' usable</div><small>'+fmt(p.owed_to_pot_minor)+' owed back · '+fmt(p.owes_minor)+' owed</small>'+(p.target_minor?'<div>'+fmt(p.balance_minor+p.owed_to_pot_minor)+' / '+fmt(p.target_minor)+'</div><div class=bar><div class=fill style="width:'+Math.round((p.progress||0)*100)+'%"></div></div><small>'+Math.round((p.progress||0)*100)+'% goal · '+fmt(p.monthly_allocation_minor)+'/month</small>':'')+'</div>').join('')}
function esc(x){return String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function bind(id,path,fn){q(id).addEventListener('submit',async e=>{e.preventDefault();q('#msg').textContent='';try{let f=Object.fromEntries(new FormData(e.target));let r=await api(path,fn(f));if(r.needs_review?.length)q('#msg').textContent='Needs mapping: '+r.needs_review.join(', ');else q('#msg').textContent='Saved';await load()}catch(x){q('#msg').textContent=x.message}})}
bind('#pot','/api/pot',f=>({name:f.name,target:f.target||null,monthly:f.monthly||0}));bind('#map','/api/map',f=>f);
bind('#spend','/api/category-spend',f=>({period:f.period,totals:{[f.category]:f.amount}}));
bind('#move','/api/event',f=>({kind:f.kind,pot:f.pot,counterparty_pot:f.other||null,amount:f.amount}));
load();
</script></html>"""

class Handler(BaseHTTPRequestHandler):
    def _send(self,status,obj,ctype="application/json"):
        raw=obj.encode() if isinstance(obj,str) else json.dumps(obj).encode();self.send_response(status);self.send_header("content-type",ctype);self.send_header("content-length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if urlparse(self.path).path=="/":return self._send(200,HTML,"text/html; charset=utf-8")
        if urlparse(self.path).path=="/api/dashboard":return self._send(200,APP.dashboard())
        self._send(404,{"error":"not found"})
    def do_POST(self):
        try:
            n=int(self.headers.get("content-length","0"));d=json.loads(self.rfile.read(n) or b"{}");p=urlparse(self.path).path
            if p=="/api/pot":APP.add_pot(d["name"],minor(d["target"]) if d.get("target") else None,minor(d.get("monthly",0)));out={"ok":True}
            elif p=="/api/map":APP.map_category(d["category"],d["pot"]);out={"ok":True}
            elif p=="/api/category-spend":out=APP.submit_category_totals(d["period"],d["totals"])
            elif p=="/api/event":
                out={"id":APP.post(Event(d["kind"],minor(d["amount"]),__import__("datetime").date.today().isoformat(),pot=d.get("pot"),counterparty_pot=d.get("counterparty_pot")))}
            else:return self._send(404,{"error":"not found"})
            self._send(200,out)
        except Exception as e:self._send(400,{"error":str(e)})
    def log_message(self,*a):pass

if __name__=="__main__":
    ThreadingHTTPServer(("0.0.0.0",int(os.environ.get("PORT","8080"))),Handler).serve_forever()
