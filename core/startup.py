"""기업의 착수계 등록과 관리자 관리. 저장: data/runtime/startups.json + 이력 로그.

상태: 임시저장 → 등록됨 → 보완 요청 / 승인. 보완 요청 건은 새 버전으로 다시 등록하고, 승인 버전은 잠겨 수정할 수 없다.
권한: 기업은 자기 기업 등록물만, 관리자는 전체. 권한 밖 요청은 PermissionError + '권한 거부' 이력.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import datetime

from . import audit, auth
from .calc import DEFAULT_AWARD_RATE, STANDARD_DEFAULTS, STANDARD_JOB, calc_standard, standard_rates
from .case import evaluate
from .data import DATA, RUNTIME, active_year, load_contracts, rate_values
from .standard import base_amounts

STORE = RUNTIME / "startups.json"
DEMO_DIR = DATA / "demo_vendors"
DRAFT, REGISTERED, FIX, APPROVED = "임시저장", "등록됨", "보완 요청", "승인"


class StartupError(ValueError):
    """등록·승인 규칙 위반(권한 문제가 아닌 것)."""


def _load() -> list[dict]:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))["startups"]
    except (OSError, ValueError, KeyError):
        return []


def _save(items: list[dict]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=RUNTIME, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"startups": items}, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, STORE)


def _put(case: dict) -> None:
    items = [x for x in _load() if x["id"] != case["id"]] + [case]
    _save(sorted(items, key=lambda x: x["id"]))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(feature: str, text: str, user, case: dict) -> None:
    audit.log(feature, text, user=user, company=case["company_name"], round_=case["round"])


def _check(user, case: dict, action: str) -> None:
    if not auth.can_access(user, case["company"]):
        raise auth.deny(user, f"{action} 거부: {case['company_name']} {case['round']}")


def default_form(company_id: str) -> dict:
    co = auth.company(company_id)
    c = next((x for x in load_contracts()["contracts"] if x["id"] == co.get("contract")), {})
    return {"contract": {"name": c.get("name", co.get("contract_name", "")), "no": f"WJ-2027-{c.get('id', company_id)}(가상)",
                         "start": str(c.get("start", "2027-01-01")), "end": str(c.get("end", "2027-12-31")), "start_date": str(c.get("start", "2027-01-01")),
                         "manager": "현장소장"},
            "groups": [{"직종": STANDARD_JOB, "인원": int(c.get("headcount", co.get("headcount", 3))), "근무형태": "전일", "월 근무시간": 209.0,
                        "근무일수": STANDARD_DEFAULTS["work_days"]}],
            "wage": {"daily": int(rate_values(active_year())["market_daily"]), "ot_hours": STANDARD_DEFAULTS["ot_hours"],
                     "hol_hours": STANDARD_DEFAULTS["hol_hours"], "hol_over_hours": STANDARD_DEFAULTS["hol_over_hours"], "leave_days": STANDARD_DEFAULTS["leave_days"]},
            "expense": {"uniform": STANDARD_DEFAULTS["uniform"], "shoes": STANDARD_DEFAULTS["shoes"]},
            "attachment": None, "award_rate": c.get("award_rate", DEFAULT_AWARD_RATE)}


def groups_from_form(form: dict, r: dict | None = None) -> list[dict]:
    """양식 → 산출 입력 그룹. 업체 금액은 업체가 적은 조건으로 계산 엔진이 만든다(등록 시점 기준으로 고정)."""
    r = r or rate_values(active_year())
    w, e = form["wage"], form["expense"]
    out = []
    for i, g in enumerate(form["groups"]):
        inputs = {"job": g["직종"], "headcount": int(g["인원"]), "monthly_hours": float(g["월 근무시간"]), "work_days": int(g["근무일수"]),
                  "daily": float(w["daily"]), "ot_hours": float(w["ot_hours"]), "hol_hours": float(w["hol_hours"]),
                  "hol_over_hours": float(w["hol_over_hours"]), "leave_days": float(w["leave_days"]), "uniform": float(e["uniform"]), "shoes": float(e["shoes"])}
        out.append({"label": f"{i + 1}. {g['직종']} {int(g['인원'])}명({g['근무형태']})", "inputs": inputs,
                    "company_amounts": base_amounts(calc_standard(inputs, standard_rates(r))), "conf": {}, "unmapped": [], "duplicates": {}})
    return out


def preview(company_id: str, form: dict) -> dict:
    """저장 전 미리보기(입력 즉시 검증용)."""
    co = auth.company(company_id)
    case = {"kind": "startup", "id": "preview", "company": company_id, "company_name": co["name"], "round": "미리보기",
            "groups": groups_from_form(form), "corrections": {}, "award_rate": form.get("award_rate", DEFAULT_AWARD_RATE)}
    return evaluate(case)


def save_draft(user: dict, company_id: str, form: dict, sid: str | None = None) -> dict:
    auth.require_role(user, auth.COMPANY)
    if not auth.can_access(user, company_id):
        raise auth.deny(user, f"작성 거부: {company_id}")
    items = _load()
    if sid:
        case = next(x for x in items if x["id"] == sid)
        _check(user, case, "수정")
        if case["status"] != DRAFT:
            raise StartupError(f"{case['status']} 상태인 {case['round']}은(는) 고칠 수 없습니다. 새 버전을 만드세요.")
    else:
        version = 1 + max((x["version"] for x in items if x["company"] == company_id), default=0)
        case = {"kind": "startup", "id": f"ST-{len(items) + 1:04d}", "company": company_id, "company_name": auth.company(company_id)["name"],
                "version": version, "round": f"v{version}", "status": DRAFT, "created": _now(), "corrections": {}, "review": None, "recheck": False}
    case.update(form=copy.deepcopy(form), contract=form["contract"], groups=groups_from_form(form), award_rate=form.get("award_rate", DEFAULT_AWARD_RATE),
                attachment=form.get("attachment"), corrections={}, review=None)
    ev = evaluate(case)
    case.update(counts=ev["counts"], blocking=ev["blocking"], office_total=ev["office_total"])
    _put(case)
    _log("착수계 임시저장", f"{case['contract']['name']}, {_counts(ev)}", user, case)
    return copy.deepcopy(case)


def _counts(ev: dict) -> str:
    c = ev["counts"]
    return f"누락 {c['누락']}·미달 {c['미달']}·과지급 {c['과지급']}·확인 필요 {c['확인 필요']}"


def register(user: dict, sid: str, reason: str = "") -> dict:
    case = get(user, sid)
    auth.require_role(user, auth.COMPANY)
    if case["status"] != DRAFT:
        raise StartupError(f"{case['status']} 상태라 등록할 수 없습니다.")
    ev = evaluate(case)
    if ev["blocking"]:
        raise StartupError("최저임금 미달이 있어 등록할 수 없습니다: " + ev["blocking"][0])
    if any(ev["counts"].values()) and not reason.strip():
        raise StartupError("미달·누락·과지급·확인 필요가 있어 사유를 적어야 등록할 수 있습니다.")
    case.update(status=REGISTERED, registered_at=_now(), registrant=user["name"], reason=reason.strip(), counts=ev["counts"], office_total=ev["office_total"])
    _put(case)
    _log("착수계 등록", f"{case['round']} 등록, {_counts(ev)}" + (" · 사유 기재" if reason.strip() else ""), user, case)
    return copy.deepcopy(case)


def list_for(user: dict) -> list[dict]:
    if not user:
        raise auth.deny(user, "착수계 목록 조회 거부")
    return [copy.deepcopy(x) for x in _load() if auth.can_access(user, x["company"])]


def get(user: dict, sid: str) -> dict:
    case = next((x for x in _load() if x["id"] == sid), None)
    if case is None:
        raise KeyError(sid)
    _check(user, case, "조회")
    return copy.deepcopy(case)


def admin_edit(user: dict, sid: str, form: dict) -> dict:
    """관리자가 값을 직접 수정한다. 수정 전후를 이력에 남기고 검수는 자동으로 풀린다."""
    auth.require_role(user, auth.ADMIN)
    case = get(user, sid)
    if case.get("locked"):
        raise StartupError("승인된 버전은 수정할 수 없습니다.")
    old = case["form"]
    changes = []
    for sec in ("contract", "wage", "expense"):
        for k, v in form[sec].items():
            if old[sec].get(k) != v:
                changes.append(f"{sec}.{k}: {old[sec].get(k)}→{v}")
    if form["groups"] != old["groups"]:
        changes.append(f"투입 인력: {old['groups']}→{form['groups']}")
    if not changes:
        return case
    case.update(form=copy.deepcopy(form), contract=form["contract"], groups=groups_from_form(form))
    ev = evaluate(case)
    case.update(counts=ev["counts"], office_total=ev["office_total"])
    _put(case)
    _log("관리자 수정", "; ".join(changes), user, case)
    return copy.deepcopy(case)


def request_fix(user: dict, sid: str, reason: str) -> dict:
    auth.require_role(user, auth.ADMIN)
    if not reason.strip():
        raise StartupError("보완 요청 사유를 적어야 합니다.")
    case = get(user, sid)
    if case["status"] != REGISTERED:
        raise StartupError(f"{case['status']} 상태라 보완 요청할 수 없습니다.")
    case.update(status=FIX, fix_at=_now(), reviewer=user["name"], fix_reason=reason.strip())
    _put(case)
    _log("보완 요청", reason.strip(), user, case)
    return copy.deepcopy(case)


def approve(user: dict, sid: str) -> dict:
    """승인: 검수 완료 + 누락·미달·과지급 정정 대기 0건일 때만."""
    from . import review
    auth.require_role(user, auth.ADMIN)
    case = get(user, sid)
    if case["status"] != REGISTERED:
        raise StartupError(f"{case['status']} 상태라 승인할 수 없습니다.")
    ev = evaluate(case)
    if ev["pending"]:
        raise StartupError(f"오류 정정 대기 {len(ev['pending'])}건이 남아 있어 승인할 수 없습니다.")
    if not review.is_valid(case, ev):
        raise StartupError("검수 완료 후에만 승인할 수 있습니다.")
    case.update(status=APPROVED, approved_at=_now(), approver=user["name"], locked=True)
    _put(case)
    _log("승인", f"{case['round']} 승인(버전 잠김)", user, case)
    return copy.deepcopy(case)


def new_version(user: dict, sid: str) -> dict:
    """보완 요청·승인 버전을 바탕으로 새 임시저장 버전을 만든다. 원래 버전은 그대로 남는다."""
    auth.require_role(user, auth.COMPANY)
    base = get(user, sid)
    if base["status"] not in (FIX, APPROVED):
        raise StartupError("보완 요청 또는 승인된 버전에서만 새 버전을 만들 수 있습니다.")
    if any(x["company"] == base["company"] and x["status"] in (DRAFT, REGISTERED) for x in _load()):
        raise StartupError("이미 임시저장이거나 등록된 버전이 있습니다.")
    new = save_draft(user, base["company"], base["form"])
    _log("새 버전", f"{base['round']}({base['status']})에서 {new['round']} 작성 시작", user, new)
    return new


def all_cases() -> list[dict]:
    """시스템 내부용(대시보드 집계·기준 변경 영향)."""
    return [copy.deepcopy(x) for x in _load()]


def seed_demo() -> None:
    """가상기업B v1(등록됨, 첨부 엑셀 포함)만 남긴다. 기업A는 시연 중에 직접 등록한다."""
    from .extract import extract
    path = DEMO_DIR / "가상업체B_산출내역.xlsx"
    if not path.exists():
        import runpy
        runpy.run_path(str(DATA.parent / "scripts" / "make_demo_vendors.py"), run_name="make")["main"]()
    form = default_form("CO-B")
    form["wage"]["daily"] = 90085   # 옛 일급(시연용)
    form["attachment"] = {**extract(path.read_bytes(), path.name), "filename": path.name}
    case = {"kind": "startup", "id": "ST-0001", "company": "CO-B", "company_name": auth.company("CO-B")["name"], "version": 1, "round": "v1",
            "status": REGISTERED, "created": _now(), "registered_at": _now(), "registrant": auth.company("CO-B")["name"],
            "reason": "기존 계약 단가로 산출했습니다(시연용 예시 사유).", "form": form, "contract": form["contract"], "groups": groups_from_form(form),
            "award_rate": form["award_rate"], "attachment": form["attachment"], "corrections": {}, "review": None, "recheck": False}
    ev = evaluate(case)
    case.update(counts=ev["counts"], office_total=ev["office_total"])
    _save([case])


def ensure() -> None:
    if not STORE.exists():
        seed_demo()
