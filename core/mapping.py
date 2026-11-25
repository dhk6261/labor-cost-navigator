"""항목명 → 공단 표준 항목 연결. 외부 AI 없이 동의어 사전(1단계)과 문자열 유사도(difflib, 2단계)만 쓴다.

0.85 이상 자동, 0.6~0.85 확인 필요, 0.6 미만 미분류. 관리자가 고친 연결은 사전 파일이 아니라
data/runtime/mapping_overrides.json에 저장하고 다음 추출 때 보조값으로 쓴다. 파일 읽기는 core/extract.py가 한다.
"""
from __future__ import annotations

import difflib
import json
import re

from .data import RUNTIME, read_json
from .standard import DICT_TO_STD

OVERRIDES = RUNTIME / "mapping_overrides.json"
AUTO, REVIEW = 0.85, 0.60
SUBTOTAL = re.compile(r"(소계|합계|총계|^계$|공급가액|^계\(|총액|기준금액)")
GROUP_ONLY = {"인건비", "노무비", "법정부담금", "복리후생비", "경비", "제경비", "4대보험"}

def norm(text) -> str:
    """괄호 속 설명·공백·기호를 지운 비교용 표기."""
    s = re.sub(r"\(.*?\)|\[.*?\]", "", str(text or ""))
    return re.sub(r"[\s·ㆍ.,:/\-_0-9%‰]", "", s)


def dictionary() -> dict:
    return read_json("항목명_사전.json")


def overrides() -> dict:
    try:
        return json.loads(OVERRIDES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_override(raw: str, item: str | None) -> None:
    data = overrides()
    data[norm(raw)] = item
    RUNTIME.mkdir(parents=True, exist_ok=True)
    OVERRIDES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_overrides() -> None:
    OVERRIDES.unlink(missing_ok=True)


def _std(name: str) -> str:
    return DICT_TO_STD.get(name, name)


def match(raw: str) -> dict:
    """{항목, 확신도, 방식}. 방식: 수정(staff), 사전, 유사도, 미분류, 소계."""
    key = norm(raw)
    if not key or key in GROUP_ONLY or SUBTOTAL.search(key):
        return {"항목": None, "확신도": 1.0, "방식": "소계"}
    fixed = overrides()
    if key in fixed:
        return {"항목": fixed[key], "확신도": 1.0, "방식": "수정"} if fixed[key] else {"항목": None, "확신도": 1.0, "방식": "제외(수정)"}
    d = dictionary()
    for item, words in d["synonyms"].items():
        if key in {norm(w) for w in words}:
            return {"항목": _std(item), "확신도": 1.0, "방식": "사전"}
    best, score = None, 0.0
    aliases = {k: v for k, v in d.get("aliases", {}).items() if not k.startswith("_")}
    for item, words in d["synonyms"].items():
        for w in list(words) + aliases.get(item, []):
            s = difflib.SequenceMatcher(None, key, norm(w)).ratio()
            if s > score:
                best, score = item, s
    if score >= REVIEW:
        return {"항목": _std(best), "확신도": round(score, 3), "방식": "유사도"}
    return {"항목": None, "확신도": round(score, 3), "방식": "미분류"}
