from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.services.history import read_history
from app.services.octopus import account_tariffs, tariff_prices


def _sample_value(point: dict[str, Any], key: str) -> float:\n    grid_import=max(0.0,float(point.get("grid_import_w") or 0.0))\n    battery_charge=max(0.0,-float(point.get("battery_power_w") or 0.0))\n    if key=="battery_charge_import_w": return min(grid_import,battery_charge)\n    if key=="domestic_import_w": return max(0.0,grid_import-battery_charge)\n    return max(0.0,float(point.get(key) or 0.0))\n\n\ndef _integrate(points: list[dict[str, Any]], start: float, end: float, key: str) -> float:
    relevant=[p for p in points if start <= float(p["reading_time"]) <= end]
    if not relevant:
        return 0.0
    before=[p for p in points if float(p["reading_time"]) < start]
    after=[p for p in points if float(p["reading_time"]) > end]
    if before: relevant.insert(0,before[-1])
    if after: relevant.append(after[0])
    if len(relevant) < 2:
        return 0.0
    wh=0.0
    for a,b in zip(relevant,relevant[1:]):
        left=max(float(a["reading_time"]),start); right=min(float(b["reading_time"]),end)
        dt=max(0.0,right-left)
        av=(_sample_value(a,key)+_sample_value(b,key))/2.0
        wh += av*dt/3600.0
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
    totals={"import_kwh":0.0,"domestic_import_kwh":0.0,"battery_charge_import_kwh":0.0,"export_kwh":0.0,"import_cost_gbp":0.0,"domestic_import_cost_gbp":0.0,"battery_charge_import_cost_gbp":0.0,"export_earnings_gbp":0.0}
    for imp,_ in days:
        for s in imp["slots"]:
            a=datetime.fromisoformat(s["valid_from"]).timestamp(); b=datetime.fromisoformat(s["valid_to"]).timestamp()
            if b <= start.timestamp() or a >= now.timestamp(): continue
            ik=_integrate(points,a,b,"grid_import_w"); dk=_integrate(points,a,b,"domestic_import_w"); bk=_integrate(points,a,b,"battery_charge_import_w"); ek=_integrate(points,a,b,"grid_export_w")
            ir=s.get("rate_p_per_kwh")
            es=export_by_start.get(s["valid_from"]); er=es.get("rate_p_per_kwh") if es else (0.0 if not tariffs["export"] else None)
            ic=(ik*ir/100.0) if ir is not None else None\n            dc=(dk*ir/100.0) if ir is not None else None\n            bc=(bk*ir/100.0) if ir is not None else None
            ee=(ek*er/100.0) if er is not None else None
            rows.append({"valid_from":s["valid_from"],"valid_to":s["valid_to"],"import_kwh":round(ik,6),"domestic_import_kwh":round(dk,6),"battery_charge_import_kwh":round(bk,6),"export_kwh":round(ek,6),"import_p_per_kwh":ir,"export_p_per_kwh":er,"import_cost_gbp":None if ic is None else round(ic,6),"domestic_import_cost_gbp":None if dc is None else round(dc,6),"battery_charge_import_cost_gbp":None if bc is None else round(bc,6),"export_earnings_gbp":None if ee is None else round(ee,6)})
            totals["import_kwh"]+=ik; totals["domestic_import_kwh"]+=dk; totals["battery_charge_import_kwh"]+=bk; totals["export_kwh"]+=ek
            if ic is not None: totals["import_cost_gbp"]+=ic\n            if dc is not None: totals["domestic_import_cost_gbp"]+=dc\n            if bc is not None: totals["battery_charge_import_cost_gbp"]+=bc
            if ee is not None: totals["export_earnings_gbp"]+=ee
    for k in totals: totals[k]=round(totals[k],6)
    totals["net_electricity_cost_gbp"]=round(totals["import_cost_gbp"]-totals["export_earnings_gbp"],6)\n    totals["net_domestic_electricity_cost_gbp"]=round(totals["domestic_import_cost_gbp"]-totals["export_earnings_gbp"],6)
    totals["average_import_p_per_kwh"]=round(totals["import_cost_gbp"]*100/totals["import_kwh"],3) if totals["import_kwh"] else None
    totals["average_export_p_per_kwh"]=round(totals["export_earnings_gbp"]*100/totals["export_kwh"],3) if totals["export_kwh"] else None
    return {"hours":hours,"timezone":timezone_name,"interval_minutes":30,"method":"integrated 1-minute telemetry against tariff-native half-hour slots","totals":totals,"intervals":rows}
