from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.services.history import read_history
from app.services.octopus import account_tariffs, tariff_prices


def _integrate(points: list[dict[str, Any]], start: float, end: float, key: str) -> float:
    relevant=[p for p in points if start <= float(p["reading_time"]) < end]
    if len(relevant) < 2:
        return 0.0
    wh=0.0
    for a,b in zip(relevant,relevant[1:]):
        dt=max(0.0,min(float(b["reading_time"]),end)-max(float(a["reading_time"]),start))
        wh += max(0.0,float(a.get(key) or 0.0))*dt/3600.0
    return wh/1000.0


def interval_report(hours: int, timezone_name: str) -> dict[str, Any]:
    tz=ZoneInfo(timezone_name)
    now=datetime.now(tz)
    start=now-timedelta(hours=hours)
    points=read_history(hours+2)
    tariffs=account_tariffs()
    days=[]
    cursor=start.date()
    while cursor <= now.date():
        imp=tariff_prices(tariffs["import"]["tariff_code"],cursor,timezone_name)
        exp=tariff_prices(tariffs["export"]["tariff_code"],cursor,timezone_name) if tariffs["export"] else None
        days.append((imp,exp))
        cursor += timedelta(days=1)
    export_by_start={}
    if tariffs["export"]:
        for _,exp in days:
            for s in exp["slots"]:
                export_by_start[s["valid_from"]]=s
    rows=[]
    totals={"import_kwh":0.0,"export_kwh":0.0,"import_cost_gbp":0.0,"export_earnings_gbp":0.0}
    for imp,_ in days:
        for s in imp["slots"]:
            a=datetime.fromisoformat(s["valid_from"]).timestamp(); b=datetime.fromisoformat(s["valid_to"]).timestamp()
            if b <= start.timestamp() or a >= now.timestamp(): continue
            ik=_integrate(points,a,b,"grid_import_w"); ek=_integrate(points,a,b,"grid_export_w")
            ir=s.get("rate_p_per_kwh")
            es=export_by_start.get(s["valid_from"]); er=es.get("rate_p_per_kwh") if es else (0.0 if not tariffs["export"] else None)
            ic=(ik*ir/100.0) if ir is not None else None
            ee=(ek*er/100.0) if er is not None else None
            rows.append({"valid_from":s["valid_from"],"valid_to":s["valid_to"],"import_kwh":round(ik,6),"export_kwh":round(ek,6),"import_p_per_kwh":ir,"export_p_per_kwh":er,"import_cost_gbp":None if ic is None else round(ic,6),"export_earnings_gbp":None if ee is None else round(ee,6)})
            totals["import_kwh"]+=ik; totals["export_kwh"]+=ek
            if ic is not None: totals["import_cost_gbp"]+=ic
            if ee is not None: totals["export_earnings_gbp"]+=ee
    for k in totals: totals[k]=round(totals[k],6)
    totals["net_electricity_cost_gbp"]=round(totals["import_cost_gbp"]-totals["export_earnings_gbp"],6)
    totals["average_import_p_per_kwh"]=round(totals["import_cost_gbp"]*100/totals["import_kwh"],3) if totals["import_kwh"] else None
    totals["average_export_p_per_kwh"]=round(totals["export_earnings_gbp"]*100/totals["export_kwh"],3) if totals["export_kwh"] else None
    return {"hours":hours,"timezone":timezone_name,"interval_minutes":30,"method":"integrated 1-minute telemetry against tariff-native half-hour slots","totals":totals,"intervals":rows}
