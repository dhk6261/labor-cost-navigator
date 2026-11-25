"""시연용 로그인·역할·기업 목록. 계정은 data/accounts.yaml(솔트 해시), 기업은 data/companies.yaml + 관리자가 추가한 기업.

[실제 도입 시 연결 지점] login()을 공단 인증(SSO 등)으로 교체한다. 회원가입 기능은 없다.
권한 판단은 화면이 아니라 이 모듈과 core/startup.py·core/calculator.py에서 한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import yaml

from . import audit
from .data import DATA, RUNTIME

ACCOUNTS = DATA / "accounts.yaml"
COMPANIES = DATA / "companies.yaml"
EXTRA = RUNTIME / "companies.json"
COMPANY, ADMIN = "company", "admin"
ROLE_LABEL = {COMPANY: "기업", ADMIN: "공단 관리자"}
DEMO_PASSWORD = "demo1234"  # 로그인 화면 안내용(시연 계정)
SESSION_KEY = "user"


def _accounts() -> dict:
    return yaml.safe_load(ACCOUNTS.read_text(encoding="utf-8"))


def demo_accounts() -> list[dict]:
    """로그인 화면 안내용 목록(해시는 내보내지 않는다)."""
    names = {c["id"]: c["name"] for c in companies()}
    return [{"아이디": k, "표시명": v["name"], "역할": ROLE_LABEL[v["role"]], "담당": "전체" if v["company"] == "*" else names.get(v["company"], v["company"])}
            for k, v in _accounts()["accounts"].items()]


# ───────────── 기업 ─────────────
def companies() -> list[dict]:
    base = yaml.safe_load(COMPANIES.read_text(encoding="utf-8"))["companies"]
    try:
        extra = json.loads(EXTRA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        extra = []
    return [{**c, "account": True} for c in base] + [{**c, "account": False} for c in extra]


def company(cid: str) -> dict:
    return next(c for c in companies() if c["id"] == cid)


def add_company(user: dict, name: str, contract_name: str, headcount: int = 3) -> dict:
    """관리자가 계정 없는 기업을 직접 추가한다(기업명·계약명만)."""
    require_role(user, ADMIN)
    name, contract_name = name.strip(), contract_name.strip()
    if not name or not contract_name:
        raise ValueError("기업명과 계약명을 적어야 합니다.")
    extra = [c for c in companies() if not c["account"]]
    if any(c["name"] == name for c in companies()):
        raise ValueError("이미 있는 기업명입니다.")
    item = {"id": f"CO-{len(companies()) + 1:02d}", "name": name, "contract_name": contract_name, "headcount": int(headcount)}
    RUNTIME.mkdir(parents=True, exist_ok=True)
    EXTRA.write_text(json.dumps([{k: v for k, v in c.items() if k != "account"} for c in extra] + [item], ensure_ascii=False, indent=1), encoding="utf-8")
    audit.log("기업 추가", f"{name}({item['id']}), 계약명 {contract_name}, 계정 없음", user=user, company=name)
    return {**item, "account": False}


def clear_companies() -> None:
    EXTRA.unlink(missing_ok=True)


# ───────────── 로그인 ─────────────
def _public(uid: str, acc: dict) -> dict:
    return {"id": uid, "name": acc["name"], "role": acc["role"], "company": acc["company"]}


def login(uid: str, pw: str) -> dict | None:
    """성공하면 사용자 정보, 실패하면 None. 비밀번호는 어디에도 기록하지 않는다."""
    doc = _accounts()
    acc = doc["accounts"].get(str(uid).strip())
    if acc:
        digest = hashlib.pbkdf2_hmac("sha256", str(pw).encode(), bytes.fromhex(acc["salt"]), int(doc["iterations"])).hex()
        if hmac.compare_digest(digest, acc["hash"]):
            user = _public(str(uid).strip(), acc)
            audit.log("로그인", f"{ROLE_LABEL[user['role']]} 로그인", user=user)
            return user
    audit.log("로그인 실패", "아이디 또는 비밀번호 불일치", user="미인증")
    return None


def sign_in(session, uid: str, pw: str) -> dict | None:
    user = login(uid, pw)
    if user:
        session[SESSION_KEY] = user
    return user


def current_user(session) -> dict | None:
    return session.get(SESSION_KEY)


def logout(session) -> None:
    user = session.pop(SESSION_KEY, None)
    if user:
        audit.log("로그아웃", f"{ROLE_LABEL[user['role']]} 로그아웃", user=user)


def switch(session, uid: str, pw: str = DEMO_PASSWORD) -> dict:
    """계정 전환(시연 편의). 로그아웃·로그인을 정상적으로 기록한다."""
    current = current_user(session)
    if current and current["id"] == uid:
        return current
    logout(session)
    user = sign_in(session, uid, pw)
    if not user:
        raise PermissionError("계정 전환 실패")
    return user


def deny(user: dict | None, what: str) -> PermissionError:
    audit.log("권한 거부", what, user=user or "미인증")
    return PermissionError(what)


def require_role(user: dict | None, role: str) -> dict:
    if not user or user.get("role") != role:
        raise deny(user, f"{ROLE_LABEL.get(role, role)} 권한 필요")
    return user


def can_access(user: dict | None, company_id: str) -> bool:
    if not user:
        return False
    return user["role"] == ADMIN or user["company"] == company_id
