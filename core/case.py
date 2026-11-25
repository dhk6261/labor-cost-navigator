"""착수계 등록물과 계산기 회차를 같은 방식으로 평가한다(표준표·판정·정정·검수 서명).

case = {kind: startup|calc, id, company, company_name, round, contract{...}, groups[{label, inputs, company_amounts, conf, unmapped, duplicates}],
        corrections{"g0:항목": {처리, 값, 사유, by, at}}, review, recheck, office_total, fields(계산기), confirmed(계산기)}
"""
from __future__ import annotations

import hashlib
import json

from .calc import DEFAULT_AWARD_RATE, standard_inputs
from .data import active_year, rate_values
from .standard import CHECK, FLAGGED, LOW, MISSING, OVER, TOTAL, check_standard, complete, judge, office_amounts, rows

STATUSES = (MISSING, LOW, OVER, CHECK)


def corrected(case: dict, gi: int) -> dict:
    """정정 완료 값이 반영된 업체 금액."""
    out = dict(case["groups"][gi].get("company_amounts") or {})
    for key, c in (case.get("corrections") or {}).items():
        g, item = key.split(":", 1)
        if g == f"g{gi}" and c["처리"] == "정정 완료":
            out[item] = c["값"]
    return out


def evaluate(case: dict, r: dict | None = None, year: int | None = None) -> dict:
    year = year or active_year()
    r = r or rate_values(year)
    corr = case.get("corrections") or {}
    groups, counts, pending, blocking = [], {s: 0 for s in STATUSES}, [], []
    office_total = company_total = 0.0
    sig = []
    for gi, g in enumerate(case["groups"]):
        inputs = standard_inputs(**g["inputs"])
        comp = corrected(case, gi)
        off = office_amounts(inputs, r)
        chk = check_standard(comp, off, r, inputs, {k: tuple(v) for k, v in (g.get("conf") or {}).items()}, g.get("unmapped"), g.get("duplicates"),
                             case.get("award_rate", DEFAULT_AWARD_RATE), g.get("company_amounts") or {})
        gcorr = {k.split(":", 1)[1]: v for k, v in corr.items() if k.startswith(f"g{gi}:")}
        for s in STATUSES:
            counts[s] += chk["counts"][s]
        pending += [f"g{gi}:{k}" for k, v in chk["items"].items() if v["상태"] in FLAGGED and k not in gcorr]
        blocking += chk["blocking"]
        n = int(inputs["headcount"])
        office_total += complete(off, n)[TOTAL]
        company_total += complete({k: v or 0 for k, v in comp.items()}, n)[TOTAL] if comp else 0
        groups.append({"label": g.get("label", f"{gi + 1}"), "inputs": inputs, "company": comp, "office": off, "check": chk,
                       "rows": rows(comp, off, r, year, inputs, chk, gcorr)})
        sig.append({"c": {k: round(v or 0) for k, v in comp.items()}, "o": {k: round(off[k]) for k in sorted(off)}, "i": g["inputs"]})
    low = judge()["low_confidence"]["value"]
    unconfirmed = [f for f in case.get("fields") or [] if f["확신도"] < low and f["key"] not in (case.get("confirmed") or [])]
    signature = hashlib.sha256(json.dumps({"g": sig, "corr": {k: [v["처리"], v.get("값"), v.get("사유")] for k, v in sorted(corr.items())}},
                                          ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {"groups": groups, "counts": counts, "pending": pending, "blocking": blocking, "unconfirmed": unconfirmed,
            "office_total": office_total, "company_total": company_total, "signature": signature, "year": year}


def save(case: dict) -> None:
    """종류에 맞는 저장소에 쓴다."""
    if case["kind"] == "startup":
        from . import startup
        startup._put(case)
    else:
        from . import calculator
        calculator._put(case)


def label(case: dict) -> str:
    return f"{case['company_name']} · {case['round']}"
