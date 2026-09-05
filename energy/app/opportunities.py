from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RateSlot:
    start: datetime
    end: datetime
    price_p_per_kwh: float


@dataclass(frozen=True)
class EnergyOpportunity:
    opportunity_id: str
    type: str
    severity: str
    start: str
    end: str
    local_date: str
    duration_minutes: int
    minimum_price_p_per_kwh: float
    slots: tuple[dict[str, object], ...]
    detected_at: str
    source: str


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError('timezone-aware datetime required')
    return dt.isoformat()


def group_negative_import_slots(
    slots: Iterable[RateSlot], *, detected_at: datetime, source: str
) -> list[EnergyOpportunity]:
    ordered=sorted((s for s in slots if s.price_p_per_kwh < 0), key=lambda s:s.start)
    groups: list[list[RateSlot]]=[]
    for slot in ordered:
        if groups and groups[-1][-1].end == slot.start:
            groups[-1].append(slot)
        else:
            groups.append([slot])
    out=[]
    for group in groups:
        start,end=group[0].start,group[-1].end
        material='|'.join(f'{_iso(x.start)}|{_iso(x.end)}|{x.price_p_per_kwh:.6f}' for x in group)
        oid='negative-import-'+hashlib.sha256(material.encode()).hexdigest()[:20]
        out.append(EnergyOpportunity(
            opportunity_id=oid,
            type='negative_import_price',
            severity='opportunity',
            start=_iso(start), end=_iso(end), local_date=start.date().isoformat(),
            duration_minutes=int((end-start).total_seconds()//60),
            minimum_price_p_per_kwh=min(x.price_p_per_kwh for x in group),
            slots=tuple({'start':_iso(x.start),'end':_iso(x.end),'price_p_per_kwh':x.price_p_per_kwh} for x in group),
            detected_at=_iso(detected_at), source=source,
        ))
    return out


class OpportunityLedger:
    """Local persistent deduplication. Runtime state is deliberately outside Git."""
    def __init__(self, path: str | Path): self.path=Path(path)
    def _load(self) -> dict[str, dict[str, object]]:
        try: return json.loads(self.path.read_text())
        except FileNotFoundError: return {}
    def unseen(self, opportunities: Iterable[EnergyOpportunity]) -> list[EnergyOpportunity]:
        seen=self._load(); return [x for x in opportunities if x.opportunity_id not in seen]
    def mark_notified(self, opportunity: EnergyOpportunity, channels: Iterable[str]) -> None:
        data=self._load(); self.path.parent.mkdir(parents=True,exist_ok=True)
        record=asdict(opportunity); record['notification_status']={x:'sent' for x in channels}
        data[opportunity.opportunity_id]=record
        tmp=self.path.with_suffix(self.path.suffix+'.tmp')
        tmp.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n'); tmp.replace(self.path)
