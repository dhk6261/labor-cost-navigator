"""관리자용 금액 산출 계산기. 업체별 회차를 data/runtime/calc/<업체ID>/run_<n>.json에 따로 보관한다.

업로드 → AI 문서 인식(core/extract.py) → 추출값 확인·수정 → 계산 엔진 산출(core/case.py) → 정정·검수(core/review.py) → 산출물.
개인정보 최소화: 올린 파일 원본은 저장하지 않고 파일명·크기·해시와 추출 결과만 보관한다.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import datetime

from . import audit, auth, extract, mapping
from .case import evaluate
from .data import RUNTIME, load_contracts

DIR = RUNTIME / "calc"
HINTS = RUNTIME / "extract_hints.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _dir(company_id: str):
    return DIR / company_id


def _put(case: dict) -> None:
    _dir(case["company"]).mkdir(parents=True, exist_ok=True)
    (_dir(case["company"]) / f"run_{case['n']}.json").write_text(json.dumps(case, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def _log(feature: str, text: str, user, case: dict) -> None:
    audit.log(feature, text, user=user, company=case["company_name"], round_=case["round"])


def _hints() -> dict:
    try:
        return json.loads(HINTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def derive(case: dict) -> dict:
    """추출 필드(+관리자 수정·보조값) → 산출 그룹."""
    fields = case["fields"]
    co = auth.company(case["company"])
    default_n = co.get("headcount") or next((c["headcount"] for c in load_contracts()["contracts"] if c["id"] == co.get("contract")), 3)
    s = extract.summarize(fields, default_n)
    for k, v in _hints().get(case["company"], {}).items():  # 관리자가 전에 고친 값을 보조값으로(파일에 없을 때만)
        key = {"인원": "headcount", "월 근무시간": "monthly_hours", "근무일수": "work_days", "일급": "daily"}.get(k)
        if key and k not in s["meta"]:
            s["inputs"][key] = v
    case["groups"] = [{"label": f"{case['company_name']} 산출내역", "inputs": s["inputs"], "company_amounts": s["amounts"],
                       "conf": {k: list(v) for k, v in s["conf"].items()}, "unmapped": s["unmapped"], "duplicates": s["duplicates"]}]
    case["meta"] = s["meta"]
    return case


def _new(user: dict, company_id: str, fields: dict, file: dict, source: str) -> dict:
    co = auth.company(company_id)
    n = 1 + max((int(p.stem.split("_")[1]) for p in _dir(company_id).glob("run_*.json")), default=0) if _dir(company_id).exists() else 1
    case = {"kind": "calc", "id": f"{company_id}-R{n}", "company": company_id, "company_name": co["name"], "n": n, "round": f"R{n}", "created": _now(),
            "status": "산출", "source": source, "file": file, "fields": fields["fields"], "pii_dropped": fields.get("pii_dropped", 0),
            "warnings": fields.get("warnings", []), "confirmed": [], "corrections": {}, "review": None, "recheck": False,
            "contract": {"name": co.get("contract_name") or next((f["값"] for f in fields["fields"] if f["이름"] == "계약명"), co["name"]),
                         "no": f"WJ-2027-{company_id}(가상)", "start": "2027-01-01", "end": "2027-12-31", "start_date": "2027-01-01", "manager": "업체 지정"}}
    derive(case)
    case["office_total"] = evaluate(case)["office_total"]
    _put(case)
    return case


def upload(user: dict, company_id: str, raw: bytes, filename: str, extractor: str = "rule") -> dict:
    """파일을 올리면 새 회차를 만든다(같은 업체는 회차가 쌓임)."""
    auth.require_role(user, auth.ADMIN)
    result = extract.extract(raw, filename, extractor)
    file = {"name": filename, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()[:16], "원본 보관": "안 함(개인정보 최소화)"}
    case = _new(user, company_id, result, file, f"파일 업로드({result['source']})")
    _log("파일 업로드", f"{filename}({len(raw):,}바이트)", user, case)
    ev = evaluate(case)
    items = sum(f["종류"] == extract.ITEM for f in case["fields"])
    _log("AI 추출", f"{extractor} 추출기: 항목 {items}개, 정보 {len(case['fields']) - items}개, 개인정보 열 {case['pii_dropped']}개 버림, "
         f"누락 {ev['counts']['누락']}·미달 {ev['counts']['미달']}·과지급 {ev['counts']['과지급']}·확인 필요 {ev['counts']['확인 필요']}", user, case)
    return copy.deepcopy(case)


def from_startup(user: dict, st: dict) -> dict:
    """착수계 등록물을 계산기로 보낸다. 첨부 파일 추출 결과가 있으면 그것으로, 없으면 등록 양식 값으로 산출한다."""
    auth.require_role(user, auth.ADMIN)
    if st.get("attachment"):
        att = st["attachment"]
        case = _new(user, st["company"], att, {"name": att.get("filename", "첨부"), "원본 보관": "안 함(개인정보 최소화)"}, f"착수계 {st['round']} 첨부")
    else:
        case = _new(user, st["company"], {"fields": []}, {"name": "(첨부 없음)"}, f"착수계 {st['round']} 양식")
        case["groups"] = copy.deepcopy(st["groups"])
        _put(case)
    case["from_startup"] = st["id"]
    _put(case)
    _log("계산기로 보내기", f"착수계 {st['round']} → 계산기 {case['round']}", user, case)
    return copy.deepcopy(case)


def get(user: dict, company_id: str, n: int) -> dict:
    auth.require_role(user, auth.ADMIN)
    return json.loads((_dir(company_id) / f"run_{n}.json").read_text(encoding="utf-8"))


def runs(user: dict, company_id: str | None = None) -> list[dict]:
    auth.require_role(user, auth.ADMIN)
    if not DIR.exists():
        return []
    out = []
    for d in sorted(DIR.iterdir()):
        if d.is_dir() and (company_id is None or d.name == company_id):
            out += [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("run_*.json"), key=lambda p: int(p.stem.split("_")[1]))]
    return out


def latest(user: dict) -> list[dict]:
    best: dict[str, dict] = {}
    for c in runs(user):
        if c["company"] not in best or c["n"] > best[c["company"]]["n"]:
            best[c["company"]] = c
    return list(best.values())


def edit_field(user: dict, case: dict, key: str, value) -> dict:
    """추출값을 고친다. 정보 값은 다음 추출 때 보조값으로 쓴다(사전 파일은 바꾸지 않음)."""
    auth.require_role(user, auth.ADMIN)
    f = next(x for x in case["fields"] if x["key"] == key)
    before = f["값"]
    f["값"], f["확신도"], f["방식"] = value, 1.0, "관리자 수정"
    if f["종류"] == extract.INFO:
        hints = _hints()
        hints.setdefault(case["company"], {})[f["이름"]] = value
        RUNTIME.mkdir(parents=True, exist_ok=True)
        HINTS.write_text(json.dumps(hints, ensure_ascii=False, indent=1), encoding="utf-8")
    derive(case)
    _put(case)
    _log("추출값 수정", f"{f['이름']}({f['위치']}): {before}→{value}", user, case)
    return case


def relink(user: dict, case: dict, key: str, item: str | None) -> dict:
    """항목 연결을 고친다. 연결 수정은 data/runtime/에 저장해 다음 추출 때 쓴다."""
    auth.require_role(user, auth.ADMIN)
    f = next(x for x in case["fields"] if x["key"] == key)
    before = f["이름"]
    mapping.set_override(f["원문"], item)
    f["이름"], f["확신도"], f["방식"] = (item or f"제외:{f['원문']}"), 1.0, "관리자 연결"
    derive(case)
    _put(case)
    _log("연결 수정", f"'{f['원문']}': {before}→{item or '제외'}", user, case)
    return case


def clear() -> None:
    shutil.rmtree(DIR, ignore_errors=True)
    HINTS.unlink(missing_ok=True)
