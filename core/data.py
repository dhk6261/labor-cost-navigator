"""원본 자료·설정 로더. 원본은 메모리로만 읽고 절대 저장하지 않는다."""
from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE = DATA / "source"
RUNTIME = DATA / "runtime"

PAY_FIRST, PAY_LAST = 6, 14


def source_file(keyword: str) -> Path:
    return next(p for p in SOURCE.iterdir() if keyword in p.name)


def open_book(keyword: str):
    """(수식 통합문서, 값 통합문서)의 첫 시트를 반환."""
    raw = source_file(keyword).read_bytes()
    formula = openpyxl.load_workbook(io.BytesIO(raw), data_only=False).worksheets[0]
    values = openpyxl.load_workbook(io.BytesIO(raw), data_only=True).worksheets[0]
    return formula, values


def read_json(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def standards() -> dict:
    """연도별 기준값의 단일 원본."""
    return read_json("연도별_기준값.json")


def baseline(year: int) -> dict:
    """해당 연도의 기준값 문서(year, label, items)."""
    return standards()["years"][str(year)]


def pension_rate(year: int) -> float:
    """사용자·근로자 각 부담률. 일정 이후 연도는 마지막 값을 유지한다."""
    schedule = {int(k): v for k, v in standards()["pension_schedule"].items() if k.isdigit()}
    return schedule[min(max(year, min(schedule)), max(schedule))]


def monthly_min_wage(year: int) -> int:
    """월 환산 최저임금(시급 × 월 소정근로시간)."""
    return round(rate_values(year)["min_wage"] * standards()["monthly_hours"])


def load_rates(year: int) -> dict:
    """2026=기준값. 2027=적용된 2027년 단가가 있으면 그 값, 없으면 2027년 기준값."""
    if year == 2026:
        return baseline(2026)["items"]
    applied = read_json("적용단가.json")
    return applied["items"] if applied.get("year") == 2027 else baseline(2027)["items"]


def rate_values(year: int) -> dict[str, float]:
    return {k: v["value"] for k, v in load_rates(year).items()}


def active_year() -> int:
    return int(read_json("적용단가.json").get("year", 2026))


def load_contracts() -> dict:
    return yaml.safe_load((DATA / "contracts.yaml").read_text(encoding="utf-8"))


def load_births() -> dict:
    """사원N → 시연용 가상 생년월일(없으면 None)."""
    return {k: v.get("birth") for k, v in load_contracts()["temp_staff"].items()}


def default_births() -> dict:
    return dict(load_contracts()["default_births"])


def save_births(births: dict) -> None:
    """주석과 나머지 값을 유지한 채 temp_staff의 birth만 바꾼다."""
    path = DATA / "contracts.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(  (사원[0-9]+): \{.*birth: )[^}]*(\})\s*$", line)
        if m and m.group(2) in births:
            value = births[m.group(2)]
            lines[i] = f"{m.group(1)}{value.isoformat() if value else 'null'}{m.group(3)}"
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class Employee:
    name: str          # 항상 행 순서로 만든 익명 이름
    row: int
    work_days: float
    weekly_days: float
    paid_days: float
    overtime: float
    holiday_8: float
    holiday_over: float
    hourly: float
    ordinary: float
    meal: float
    jul_base: float
    aug_base: float
    spouse: int
    child: int
    other: int
    health: float
    ltc: float
    pension: float
    employment: float
    income_tax: float
    local_tax: float
    file_gross: float
    file_deduct: float
    file_net: float

    @property
    def enrolled(self) -> bool:
        return self.pension > 0


def load_employees(values=None) -> list[Employee]:
    ws = values if values is not None else open_book("기간제")[1]
    n = lambda ref: ws[ref].value or 0
    staff = []
    for i, r in enumerate(range(PAY_FIRST, PAY_LAST + 1)):
        staff.append(Employee(
            name=f"사원{i + 1}", row=r,
            work_days=n(f"B{r}"), weekly_days=n(f"C{r}"), paid_days=n(f"D{r}"),
            overtime=n(f"E{r}"), holiday_8=n(f"F{r}"), holiday_over=n(f"G{r}"),
            hourly=n(f"H{r}"), ordinary=n(f"I{r}"), meal=n(f"N{r}"),
            jul_base=n(f"V{19 + i}"), aug_base=n(f"W{19 + i}"),
            spouse=n(f"W{52 + i}"), child=n(f"Y{52 + i}"), other=n(f"AA{52 + i}"),
            health=n(f"V{r}"), ltc=n(f"W{r}"), pension=n(f"X{r}"), employment=n(f"Y{r}"),
            income_tax=n(f"AA{r}"), local_tax=n(f"AB{r}"),
            file_gross=n(f"J{r}"), file_deduct=n(f"U{r}"), file_net=n(f"AD{r}"),
        ))
    return staff
