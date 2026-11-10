"""Local-first personal budgeting event model for Finance F1."""
from __future__ import annotations
import json, sqlite3, uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

EVENTS={"allocation","category_spend","transfer","loan","repayment","refund","correction"}
def minor(value)->int:
    return int((Decimal(str(value))*100).quantize(Decimal("1"),rounding=ROUND_HALF_UP))

@dataclass(frozen=True)
class Event:
    kind:str; amount_minor:int; occurred_on:str; pot:str|None=None
    counterparty_pot:str|None=None; period:str|None=None; category:str|None=None
    external_key:str|None=None; reverses:str|None=None; note:str=""

class PersonalFinance:
    """Append-only virtual-pot ledger. No bank credentials or cloud dependency."""
    def __init__(self, path=":memory:"):
        self.db=sqlite3.connect(path); self.db.row_factory=sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS pf_pots(
          name TEXT PRIMARY KEY,target_minor INTEGER,monthly_allocation_minor INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS pf_category_map(
          category TEXT PRIMARY KEY,pot TEXT NOT NULL REFERENCES pf_pots(name));
        CREATE TABLE IF NOT EXISTS pf_events(
          id TEXT PRIMARY KEY,kind TEXT NOT NULL,amount_minor INTEGER NOT NULL CHECK(amount_minor>=0),
          occurred_on TEXT NOT NULL,pot TEXT,counterparty_pot TEXT,period TEXT,category TEXT,
          external_key TEXT UNIQUE,reverses TEXT UNIQUE,note TEXT NOT NULL DEFAULT '',
          FOREIGN KEY(pot) REFERENCES pf_pots(name),FOREIGN KEY(counterparty_pot) REFERENCES pf_pots(name),
          FOREIGN KEY(reverses) REFERENCES pf_events(id));
        """); self.db.commit()
    def add_pot(self,name,target_minor=None,monthly_allocation_minor=0):
        self.db.execute("insert into pf_pots(name,target_minor,monthly_allocation_minor) values(?,?,?) on conflict(name) do update set target_minor=excluded.target_minor,monthly_allocation_minor=excluded.monthly_allocation_minor",(name,target_minor,monthly_allocation_minor));self.db.commit()
    def map_category(self,category,pot):
        self._pot(pot);self.db.execute("insert into pf_category_map values(?,?) on conflict(category) do update set pot=excluded.pot",(category,pot));self.db.commit()
    def _pot(self,name):
        if not name or not self.db.execute("select 1 from pf_pots where name=?",(name,)).fetchone(): raise ValueError("unknown pot")
    def post(self,e:Event)->str:
        if e.kind not in EVENTS or e.amount_minor<0: raise ValueError("invalid event")
        if e.kind in {"allocation","category_spend","refund"}: self._pot(e.pot)
        if e.kind in {"transfer","loan","repayment"}:
            self._pot(e.pot);self._pot(e.counterparty_pot)
            if e.pot==e.counterparty_pot: raise ValueError("pots must differ")
        if e.kind=="repayment":
            debt=self.debt(e.pot,e.counterparty_pot)
            if e.amount_minor>debt: raise ValueError("repayment exceeds debt")
        if e.kind=="correction":
            if not e.reverses: raise ValueError("correction requires reverses")
            old=self.db.execute("select * from pf_events where id=?",(e.reverses,)).fetchone()
            if not old: raise ValueError("unknown reversed event")
        eid=str(uuid.uuid4())
        try:self.db.execute("insert into pf_events values(?,?,?,?,?,?,?,?,?,?,?)",(eid,e.kind,e.amount_minor,e.occurred_on,e.pot,e.counterparty_pot,e.period,e.category,e.external_key,e.reverses,e.note));self.db.commit()
        except sqlite3.IntegrityError as x: raise ValueError("duplicate or invalid event") from x
        return eid
    def submit_category_totals(self,period,totals,occurred_on=None):
        occurred_on=occurred_on or date.today().isoformat();review=[];posted=[]
        for category,amount in totals.items():
            row=self.db.execute("select pot from pf_category_map where category=?",(category,)).fetchone()
            if not row: review.append(category);continue
            cents=minor(amount)
            if cents==0: continue
            key=f"category:{period}:{category}"
            posted.append(self.post(Event("category_spend",cents,occurred_on,pot=row["pot"],period=period,category=category,external_key=key)))
        return {"posted":posted,"needs_review":review}
    def _active(self):
        rows=self.db.execute("select * from pf_events order by occurred_on,id").fetchall()
        reversed_ids={r["reverses"] for r in rows if r["kind"]=="correction"}
        return [r for r in rows if r["id"] not in reversed_ids and r["kind"]!="correction"]
    def balances(self):
        out={r["name"]:0 for r in self.db.execute("select name from pf_pots")}
        for e in self._active():
            a=e["amount_minor"];k=e["kind"];p=e["pot"];q=e["counterparty_pot"]
            if k=="allocation":out[p]+=a
            elif k=="category_spend":out[p]-=a
            elif k=="refund":out[p]+=a
            elif k in {"transfer","loan","repayment"}:out[p]-=a;out[q]+=a
        return out
    def debt(self,borrower,lender):
        total=0
        for e in self._active():
            if e["kind"]=="loan" and e["pot"]==lender and e["counterparty_pot"]==borrower:total+=e["amount_minor"]
            elif e["kind"]=="repayment" and e["pot"]==borrower and e["counterparty_pot"]==lender:total-=e["amount_minor"]
        return total
    def dashboard(self):
        bal=self.balances();pots=[]
        for p in self.db.execute("select * from pf_pots order by name"):
            owed=sum(self.debt(b,p["name"]) for b in bal if b!=p["name"])
            owes=sum(self.debt(p["name"],l) for l in bal if l!=p["name"])
            target=p["target_minor"];progress=None if not target else max(0,min(1,(bal[p["name"]]+owed)/target))
            pots.append({"name":p["name"],"balance_minor":bal[p["name"]],"owed_to_pot_minor":owed,"owes_minor":owes,"net_position_minor":bal[p["name"]]+owed-owes,"target_minor":target,"progress":progress,"monthly_allocation_minor":p["monthly_allocation_minor"]})
        return {"privacy":"local-only","pots":pots,"event_count":len(self._active())}
