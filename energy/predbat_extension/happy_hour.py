"""Predbat Happy Hour recommendation helper; no booking or live rate mutation."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations
from math import isfinite

@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime

def recommend(slots, tokens, now, evaluate, confirmed=()):
    """Evaluate complete hypothetical plans, returning (slots, savings_pence).

    evaluate(tuple[Slot, ...]) must return the same-horizon total Predbat
    plan cost in pence, including terminal battery value. Confirmed slots
    are included in every scenario. Inputs must be account-eligible offers.
    tokens is the verified remaining booking allowance, not earned credits.
    """
    if now.utcoffset() is None or type(tokens) is not int or not 0 <= tokens <= 2:
        raise ValueError("invalid time or booking allowance")
    def valid(s):
        return (s.start.utcoffset() is not None and s.end.utcoffset() is not None
                and s.end - s.start == timedelta(hours=1))
    def overlap(a, b):
        return a.start < b.end and b.start < a.end
    confirmed = tuple(confirmed)
    if any(not valid(s) for s in confirmed):
        raise ValueError("invalid confirmed slot")
    candidates = sorted(set(slots), key=lambda s: s.start)
    if any(not valid(s) for s in candidates):
        raise ValueError("invalid offered slot")
    candidates = [s for s in candidates if s.start > now and
                  not any(overlap(s, c) for c in confirmed)]
    baseline = evaluate(confirmed)
    if not isfinite(baseline):
        raise ValueError("invalid baseline")
    best, savings = (), 0.0
    for n in range(1, min(tokens, len(candidates)) + 1):
        for group in combinations(candidates, n):
            if any(overlap(a, b) for a, b in combinations(group, 2)):
                continue
            cost = evaluate(confirmed + group)
            if not isfinite(cost):
                raise ValueError("invalid scenario cost")
            if baseline - cost > savings:
                best, savings = group, baseline - cost
    return best, savings
