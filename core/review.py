"""사람(관리자) 검수와 최종 산출물 문지기.

- 오류 정정: 누락·미달·과지급 행은 '정정 완료(값 수정)' 또는 '정정 불필요(사유)'로 처리해야 한다.
- 검수: 체크리스트 5개를 모두 확인하고, 정정 대기 0건·확신도 낮은 추출값 모두 확인일 때만 완료된다.
- 검수 기록에는 그때의 값 서명을 남기고, 값이 바뀌면 검수는 자동으로 풀린다(서명 불일치).
- 최종 산출물(착수계 4종, 산출내역서, 근로자 설명서, 공문)은 require()를 통과해야 만들 수 있다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from . import audit, auth, basis
from .case import evaluate, save
from .data import RUNTIME

CHECKLIST = ["산정기준 버전 확인", "추출값 확인(확신도 낮은 값 모두 확인)", "오류 정정 필요 항목 모두 처리(정정 완료 또는 사유)",
             "업체 비교 확인", "개인정보 열 제거 확인"]
DONE, WAIT, RECHECK = "검수 완료", "검수 대기", "재검수 필요"
DRAFT_MARK = "검수 전 초안"
DOC_REVIEWS = RUNTIME / "doc_reviews.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(feature: str, text: str, user, case: dict) -> None:
    audit.log(feature, text, user=user, company=case["company_name"], round_=case["round"])


def correct(user: dict, case: dict, key: str, mode: str, value: float | None = None, reason: str = "") -> dict:
    """오류 정정 처리. mode='정정 완료'(값 필수) 또는 '정정 불필요'(사유 필수). 승인된 착수계는 값 수정 불가."""
    auth.require_role(user, auth.ADMIN)
    if mode == "정정 완료":
        if value is None:
            raise ValueError("정정 완료는 고친 값을 적어야 합니다.")
        if case.get("locked"):
            raise ValueError("승인된 착수계는 값을 고칠 수 없습니다. '정정 불필요(사유)'로 처리하고 재제출을 요청하세요.")
    elif mode == "정정 불필요":
        if not reason.strip():
            raise ValueError("정정 불필요는 사유를 적어야 합니다.")
    else:
        raise ValueError(mode)
    before = evaluate(case)["groups"][int(key.split(":")[0][1:])]["company"].get(key.split(":", 1)[1])
    case.setdefault("corrections", {})[key] = {"처리": mode, "값": value, "사유": reason.strip(), "by": user["name"], "at": _now()}
    save(case)
    item = key.split(":", 1)[1]
    _log("오류 정정", f"{item}: {mode}" + (f" {before or 0:,.0f}→{value:,.0f}원" if mode == "정정 완료" else f" (사유: {reason.strip()})"), user, case)
    return case


def confirm_fields(user: dict, case: dict, keys: list[str]) -> dict:
    auth.require_role(user, auth.ADMIN)
    case["confirmed"] = sorted(set(case.get("confirmed") or []) | set(keys))
    save(case)
    _log("추출값 확인", f"확신도 낮은 값 {len(keys)}개 확인", user, case)
    return case


def is_valid(case: dict, ev: dict | None = None) -> bool:
    rv = case.get("review")
    return bool(rv) and rv["signature"] == (ev or evaluate(case))["signature"]


def state(case: dict, ev: dict | None = None) -> str:
    if is_valid(case, ev):
        return DONE
    return RECHECK if case.get("recheck") or case.get("review") else WAIT


def complete(user: dict, case: dict, checks: dict[str, bool]) -> dict:
    """검수 완료. 체크리스트 5개 + 정정 대기 0 + 확신도 낮은 값 확인 완료."""
    auth.require_role(user, auth.ADMIN)
    missing = [c for c in CHECKLIST if not checks.get(c)]
    if missing:
        raise ValueError("체크리스트를 모두 확인해야 합니다: " + ", ".join(missing))
    ev = evaluate(case)
    if ev["pending"]:
        raise ValueError(f"오류 정정 대기 {len(ev['pending'])}건을 먼저 처리해야 합니다.")
    if ev["unconfirmed"]:
        raise ValueError(f"확신도 낮은 추출값 {len(ev['unconfirmed'])}개를 먼저 확인해야 합니다.")
    corr = case.get("corrections") or {}
    summary = f"정정 완료 {sum(c['처리'] == '정정 완료' for c in corr.values())}건, 정정 불필요 {sum(c['처리'] == '정정 불필요' for c in corr.values())}건"
    case["review"] = {"by": user["name"], "at": _now(), "basis": basis.label(), "basis_version": basis.current()["version"],
                      "signature": ev["signature"], "summary": summary, "checks": CHECKLIST}
    case["recheck"] = False
    case["office_total"] = ev["office_total"]
    save(case)
    _log("검수 완료", f"{summary}, 기준 {basis.label()}", user, case)
    return case


def require(user: dict, case: dict, what: str = "최종 산출물") -> dict:
    """검수 완료 전에는 최종 산출물을 만들 수 없다(함수 단계에서 거부)."""
    auth.require_role(user, auth.ADMIN)
    if not is_valid(case):
        audit.log("산출물 거부", f"{what}: 검수 완료 전", user=user, company=case["company_name"], round_=case["round"])
        raise PermissionError(f"검수 완료 전에는 {what}을(를) 만들 수 없습니다. 화면 미리보기만 가능합니다({DRAFT_MARK}).")
    return case["review"]


def stamp(case: dict) -> str:
    rv = case["review"]
    return f"검수 완료: {rv['by']}, {rv['at']}, 기준 {rv['basis']}"


# ───────────── 문서 초안(공문·품의서 등) 검수 ─────────────
def _doc_sig(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _docs() -> dict:
    try:
        return json.loads(DOC_REVIEWS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def review_doc(user: dict, kind: str, content: str) -> dict:
    auth.require_role(user, auth.ADMIN)
    data = _docs()
    data[kind] = {"signature": _doc_sig(content), "by": user["name"], "at": _now(), "basis": basis.label()}
    RUNTIME.mkdir(parents=True, exist_ok=True)
    DOC_REVIEWS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    audit.log("검수 완료", f"문서 초안 '{kind}' 검수", user=user)
    return data[kind]


def doc_review(kind: str, content: str) -> dict | None:
    rv = _docs().get(kind)
    return rv if rv and rv["signature"] == _doc_sig(content) else None


def require_doc(user: dict, kind: str, content: str) -> dict:
    auth.require_role(user, auth.ADMIN)
    rv = doc_review(kind, content)
    if not rv:
        audit.log("산출물 거부", f"문서 '{kind}': 검수 완료 전", user=user)
        raise PermissionError(f"검수 완료 전에는 '{kind}'을(를) 내려받을 수 없습니다({DRAFT_MARK}).")
    return rv


def clear_docs() -> None:
    DOC_REVIEWS.unlink(missing_ok=True)
