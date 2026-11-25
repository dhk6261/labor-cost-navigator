"""공표 단가 변경 감지와 입력값 검증.

시연에서는 data/공표단가.json 변경을 '새 공표'로 본다.
[실제 도입 시 API 연결 지점] fetch_published()를 중소기업중앙회·고용노동부 등 공표 자료 수집 코드로 교체한다.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile

from .data import DATA, baseline

PUBLISHED = DATA / "공표단가.json"
APPLIED = DATA / "적용단가.json"
PREVIOUS = DATA / "이전단가.json"
BASE = DATA / "기준단가_2026.json"
SCENARIO = DATA / "시연_2027단가.json"

# 필수 키와 값 종류: money는 0보다 큰 금액, rate는 0~1 사이 요율
REQUIRED = {
    "market_daily": "money", "min_wage": "money", "pension": "rate", "health": "rate", "ltc": "rate", "cleaning_ltc": "rate",
    "employment_employer": "rate", "employment_worker": "rate", "industrial": "rate", "wage_claim": "rate",
}
LABELS = {
    "market_daily": "시중노임단가", "min_wage": "최저임금", "pension": "국민연금", "health": "건강보험", "ltc": "장기요양",
    "cleaning_ltc": "장기요양(청소)", "employment_employer": "고용보험(사업주)", "employment_worker": "고용보험(근로자)",
    "industrial": "산재보험", "wage_claim": "임금채권보장",
}
NUMBER = re.compile(r"[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?")


class RateError(ValueError):
    """단가 파일 문제. errors에 키별 안내 문구를 담는다."""

    def __init__(self, errors: list[str]):
        super().__init__(" / ".join(errors))
        self.errors = errors


def parse_number(value) -> float:
    """숫자 또는 '99,310', '99,310원', '13.9%' 형태를 숫자로 바꾼다. 불가능하면 ValueError."""
    if isinstance(value, bool) or value is None:
        raise ValueError("숫자가 아닙니다")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        percent = text.endswith("%")
        text = text[:-1].strip() if percent else text.removesuffix("원").strip()
        if not NUMBER.fullmatch(text):
            raise ValueError("숫자로 바꿀 수 없습니다")
        number = float(text.replace(",", ""))
        number = round(number / 100, 10) if percent else number
    else:
        raise ValueError("숫자가 아닙니다")
    if not math.isfinite(number):
        raise ValueError("유한한 숫자가 아닙니다")
    return number


def validate_doc(doc) -> tuple[dict, list[str]]:
    """필수 키·숫자·범위를 검사해 (정리된 문서, 오류 목록)을 돌려준다."""
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
        return {}, ["파일 구조: 최상위에 items 항목이 있어야 합니다"]
    items, errors = {}, []
    for key, kind in REQUIRED.items():
        label = f"{key}({LABELS[key]})"
        if key not in doc["items"]:
            errors.append(f"{label}: 필수 키가 없습니다")
            continue
        raw = doc["items"][key]
        item = dict(raw) if isinstance(raw, dict) else {"value": raw}
        if "value" not in item:
            errors.append(f"{label}: value 값이 없습니다")
            continue
        try:
            number = parse_number(item["value"])
        except ValueError as e:
            errors.append(f"{label}: '{item['value']}' {e}")
            continue
        if kind == "money" and number <= 0:
            errors.append(f"{label}: {number:g}은(는) 0보다 커야 합니다")
            continue
        if kind == "rate" and not 0 <= number <= 1:
            errors.append(f"{label}: {number:g}은(는) 0~1 사이여야 합니다(예: 5%는 0.05)")
            continue
        item["value"] = int(number) if kind == "money" and number.is_integer() else number
        items[key] = item
    extra = {k: v for k, v in doc["items"].items() if k not in REQUIRED}
    return {**doc, "items": {**items, **extra}}, errors


def _read(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path, doc: dict) -> None:
    """읽는 쪽이 반쪽 파일을 보지 않도록 임시 파일에 쓴 뒤 교체한다."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def fetch_published() -> dict:
    return _read(PUBLISHED)  # ← 실제 API 연결 지점


def resolve(doc: dict) -> dict:
    """2026 값에서 하나라도 바뀌면 2027년 모드로 보고, 바꾸지 않은 항목에는 2027년 기준값을 채운다.

    값을 바꾸면서 출처를 그대로 둔 항목은 '확정'으로 남기지 않고 담당자 입력 가정값으로 표시한다.
    """
    base, next_year = baseline(2026)["items"], baseline(2027)["items"]
    is_2027 = int(doc.get("year", 2026)) >= 2027 or any(doc["items"][k]["value"] != base[k]["value"] for k in REQUIRED)
    if not is_2027:
        return {**doc, "year": 2026, "items": {k: {**base[k], **doc["items"][k]} for k in REQUIRED}}
    items = {}
    from_2026 = int(doc.get("year", 2026)) < 2027
    for key in REQUIRED:
        item, ref, old = doc["items"][key], next_year[key], base[key]
        known_sources = (None, "", old.get("source"), ref.get("source"))
        if from_2026 and item["value"] == old["value"]:
            items[key] = dict(ref)
        elif item["value"] == ref["value"]:
            items[key] = dict(ref) if item.get("source") in known_sources else {**ref, **item, "period": ref.get("period")}
        elif item.get("source") in known_sources:
            items[key] = {**ref, "value": item["value"], "status": "가정", "status_note": "가정값(담당자 입력)", "source": "담당자 입력", "announced": ""}
        else:
            items[key] = {**ref, **item, "period": ref.get("period")}
    return {**doc, "year": 2027, "label": baseline(2027)["label"], "items": items}


def checked_published() -> dict:
    """검증을 통과하고 적용 연도 기준값이 채워진 공표값. 문제가 있으면 RateError."""
    try:
        doc = fetch_published()
    except json.JSONDecodeError as e:
        raise RateError([f"공표단가.json 형식 오류: {e.lineno}행 {e.colno}열"]) from e
    except OSError as e:
        raise RateError([f"공표단가.json을 읽을 수 없습니다: {type(e).__name__}"]) from e
    clean, errors = validate_doc(doc)
    if errors:
        raise RateError(errors)
    return resolve(clean)


def sync_derived() -> None:
    """단일 원본에서 연도별 파일을 다시 만든다. 내용이 같으면 쓰지 않는다."""
    for path, year in ((BASE, 2026), (SCENARIO, 2027)):
        doc = baseline(year)
        if not path.exists() or _read(path) != doc:
            _write(path, doc)


def detect_changes() -> list[dict]:
    """공표값과 적용값의 차이. 공표값이 잘못되면 RateError."""
    new, cur = checked_published()["items"], _read(APPLIED)["items"]
    return [{"key": k, "항목": v.get("name", LABELS[k]), "unit": v.get("unit") or cur[k]["unit"], "적용 중": cur[k]["value"], "새 공표": v["value"],
             "상태": v.get("status", "미지정"), "표시": status_label(v), "고시일": v.get("announced", ""), "출처": v.get("source", "")}
            for k, v in new.items() if k in REQUIRED and cur[k]["value"] != v["value"]]


def status_label(item: dict) -> str:
    """화면 표시용 상태: '확정, 2027', '가정값(11.30 공표 후 갱신)' 등."""
    status = item.get("status", "미지정")
    if status == "가정":
        return item.get("status_note") or "가정값"
    if status == "원본":
        return "원본 기재값"
    period = item.get("period")
    return f"{status}, {period}" if period else status


def form_value(key: str, text: str):
    """편집 폼 입력을 저장값으로 바꾼다. 요율은 % 단위로 입력받는다. 변환 실패 시 원문을 두어 검증에서 안내한다."""
    text = str(text).strip()
    if REQUIRED[key] == "rate" and text and not text.endswith("%"):
        text += "%"
    try:
        return parse_number(text)
    except ValueError:
        return text


def edited_doc(doc: dict, inputs: dict[str, dict]) -> dict:
    """폼 입력을 문서에 합친다. 값·상태·출처·고시일만 바꾼다."""
    out = json.loads(json.dumps(doc, ensure_ascii=False))
    for key, row in inputs.items():
        item = out["items"][key]
        new_value = form_value(key, row["value"])
        changed = item["value"] != new_value
        same_claim = row["status"] == item.get("status") and row["source"].strip() == item.get("source", "")
        item["value"] = new_value
        item["status"], item["source"], item["announced"] = row["status"], row["source"].strip(), row["announced"].strip()
        if row["status"] != "가정":
            item.pop("status_note", None)
        if changed and same_claim:  # 값만 바꾸고 근거를 그대로 두면 확정으로 남기지 않는다
            item.update(status="가정", status_note="가정값(담당자 입력)", source="담당자 입력", announced="")
    return out


def save_published(doc: dict) -> None:
    """검증을 통과한 문서만 적용 연도 기준값을 채워 공표단가.json에 저장한다."""
    clean, errors = validate_doc(doc)
    if errors:
        raise RateError(errors)
    _write(PUBLISHED, resolve(clean))


def simulate_publication() -> None:
    """시연 버튼: 공표단가.json을 2027년 기준값으로 바꾼다."""
    _write(PUBLISHED, baseline(2027))


def apply_published() -> None:
    clean = checked_published()
    shutil.copyfile(APPLIED, PREVIOUS)
    _write(APPLIED, clean)


def reset() -> None:
    doc = baseline(2026)
    for target in (PUBLISHED, APPLIED):
        _write(target, doc)
    PREVIOUS.unlink(missing_ok=True)
