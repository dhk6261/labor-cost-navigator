"""이력 로그(data/history.csv)와 시연 진행 상태."""
from __future__ import annotations

import csv
import json
from datetime import datetime

from .data import DATA, RUNTIME

HISTORY = DATA / "history.csv"
STATE = RUNTIME / "state.json"
FIELDS = ["시각", "기능", "사용자", "역할", "업체", "회차", "내용"]
ROLE_NAME = {"company": "기업", "admin": "공단 관리자"}
DEFAULT = {"recalculated": False}
_actor: dict | None = None  # 화면 실행마다 app.py가 로그인 사용자로 설정한다


def set_actor(user: dict | None) -> None:
    global _actor
    _actor = user


def get_state() -> dict:
    try:
        return {**DEFAULT, **json.loads(STATE.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULT)


def set_state(**kw) -> dict:
    state = {**get_state(), **kw}
    RUNTIME.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return state


def _who(user) -> tuple[str, str]:
    user = _actor if user is None else user
    if isinstance(user, dict):
        return user.get("name", "?"), ROLE_NAME.get(user.get("role"), "")
    return (user or "시스템"), ""


def log(feature: str, content: str, user=None, company: str = "", round_: str = "") -> None:
    """user는 로그인 사용자 dict 또는 표시명. 없으면 현재 화면의 로그인 사용자."""
    name, role = _who(user)
    new = not HISTORY.exists()
    with HISTORY.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        w.writerow({"시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "기능": feature, "사용자": name, "역할": role,
                    "업체": company, "회차": round_, "내용": content})


def read_log() -> list[dict]:
    if not HISTORY.exists():
        return []
    with HISTORY.open(encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "") for k, v in row.items() if k in FIELDS} for row in csv.DictReader(f)][::-1]


def clear_log() -> None:
    HISTORY.unlink(missing_ok=True)
