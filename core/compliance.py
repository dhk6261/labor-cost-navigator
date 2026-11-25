"""공공부문 도급 노동자 보호지침 준수 점검. 조항 문구는 core/guide.py의 원문만 인용한다."""
from __future__ import annotations

import re
from datetime import date, timedelta

from . import rates
from .anomaly import enrich, payslip_check
from .data import active_year, load_contracts, open_book, rate_values
from .guide import cite

OK, VIOLATION, CHECK, NONE = "충족", "위반", "확인 필요", "해당 없음"
AWARD_FLOOR = 0.89995  # 지침 5-3 시설분야 단순노무용역 낙찰하한율


def _published() -> tuple[dict, bool]:
    """(적용 시점 단가, 2027년 공표 여부). 공표 파일이 잘못되면 현재 적용값을 쓴다."""
    try:
        doc = rates.checked_published()
    except rates.RateError:
        return rate_values(active_year()), active_year() == 2027
    if doc.get("year") == 2027:
        return {k: v["value"] for k, v in doc["items"].items()}, True
    return rate_values(active_year()), active_year() == 2027


def _row(clause: str, check: str, evidence: str, status: str, quote: str, action: str = "-") -> dict:
    return {"조항": clause, "점검 내용": check, "근거값": evidence, "결과": status, "조치": action if status in (VIOLATION, CHECK) else "-", "지침 원문": quote}


def _labor_parts() -> dict[str, float]:
    ws = open_book("청소용역")[1]
    parts = {"기본급": 0.0, "제수당": 0.0, "상여금": 0.0, "퇴직충당금": 0.0}
    for r in range(1, ws.max_row + 1):
        label = re.sub(r"\s+", "", str(ws[f"C{r}"].value or ws[f"B{r}"].value or ""))
        amount = ws[f"D{r}"].value
        if not isinstance(amount, (int, float)):
            continue
        if label.startswith("기본급"):
            parts["기본급"] += amount
        elif label.endswith("수당"):
            parts["제수당"] += amount
        elif label.startswith("상여금"):
            parts["상여금"] += amount
        elif label.startswith("퇴직충당금"):
            parts["퇴직충당금"] += amount
    return parts


def _term_ok(start: date, end: date) -> bool:
    try:
        two_years = start.replace(year=start.year + 2)
    except ValueError:  # 2월 29일 시작
        two_years = start.replace(year=start.year + 2, month=3, day=1)
    return end + timedelta(days=1) >= two_years


def check_contract(contract: dict) -> list[dict]:
    values, published = _published()
    forward = values if published else rate_values(2027)
    k3 = open_book("청소용역")[1]["K3"].value
    award = contract["award_rate"]
    method = contract["method"]
    rows = []

    required = values["market_daily"]
    note = "2027 공표값" if published else "현재 적용값"
    rows.append(_row("5-2", "산출내역 기본급 단가가 적용 시점 시중노임단가 이상인가", f"K3 {k3:,}원, {note} {required:,}원",
                     OK if k3 >= required else VIOLATION, cite("5-2-b"), "계약 변경으로 노무비 조정"))

    hourly = forward["market_daily"] * award / 8
    rows.append(_row("5-2-c·5-6-1", "시중노임단가 × 낙찰률 ÷ 8이 최저임금 이상인가",
                     f"{forward['market_daily']:,}원 × {award:.3%} ÷ 8 = {hourly:,.0f}원, 최저임금 {forward['min_wage']:,}원",
                     OK if hourly >= forward["min_wage"] else VIOLATION, f"{cite('5-2-c')} {cite('5-6-1')}", "최저임금 이상 지급되도록 노무비 조정"))

    if "적격" in method:
        rows.append(_row("5-3", "적격심사 입찰 계약의 낙찰률이 89.995% 이상인가", f"설정 낙찰률 {award:.3%}(가정값)",
                         OK if award >= AWARD_FLOOR else VIOLATION, cite("5-3"), "낙찰률 재확인 후 계약 조건 시정"))
    else:
        rows.append(_row("5-3", "적격심사 입찰 계약의 낙찰률이 89.995% 이상인가", f"계약 방식 {method}", NONE, cite("5-3")))

    if "수의" in method:
        rows.append(_row("5-5-2", "수의계약인데 낙찰률을 적용했는가", f"설정 낙찰률 {award:.3%}", OK if award >= 1 else VIOLATION, cite("5-5-2"), "낙찰률 없이 예정가격으로 계약"))
    else:
        rows.append(_row("5-5-2", "수의계약인데 낙찰률을 적용했는가", f"계약 방식 {method}", NONE, cite("5-5-2")))

    parts = _labor_parts()
    missing = [k for k, v in parts.items() if v <= 0]
    rows.append(_row("5-5-3", "노무비가 기본급·제수당·상여금·퇴직충당금으로 구분되어 있는가",
                     ", ".join(f"{k} {v:,.0f}원" for k, v in parts.items()), VIOLATION if missing else OK, cite("5-5-3"), "산출내역서 노무비 항목 구분"))

    start, end = contract["start"], contract["end"]
    term = round((end - start).days / 365.25, 1)
    rows.append(_row("4-1", "도급계약 기간이 2년 이상인가", f"{start} ~ {end}, 약 {term:g}년(가정값)",
                     OK if _term_ok(start, end) else VIOLATION, f"{cite('4-1')} {cite('7-1')}", "다음 계약부터 2년 이상. 지침 시행 전 체결 계약은 적용 범위 확인"))

    slips = payslip_check(enrich())
    short = slips[slips["확인 결과"] == "미달"]
    evidence = f"미달 {len(short)}명, 부족액 {abs(short['차액'].sum()):,.0f}원(가상 데이터)" if len(short) else f"{len(slips)}명 모두 산정액 이상(가상 데이터)"
    rows.append(_row("6-2-2", "분기 임금명세서 제출액이 산정액 이상인가", evidence, VIOLATION if len(short) else OK, cite("6-2-2"), "미달분 지급 확인 및 시정 요구"))
    return rows


def run_compliance() -> list[dict]:
    """원본 산출내역이 있는 계약만 점검한다(가상 계약 C-002 제외)."""
    return [{"contract": c, "rows": check_contract(c)} for c in load_contracts()["contracts"] if not c.get("demo_vendor")]


def violations(results: list[dict] | None = None) -> list[dict]:
    results = run_compliance() if results is None else results
    return [{"계약": r["contract"]["name"], **x} for r in results for x in r["rows"] if x["결과"] == VIOLATION]
