"""시연용 가상 데이터. 실제 근태 자료가 아니며 화면에 반드시 그렇게 표시한다."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .data import DATA

ATT = DATA / "virtual_attendance.csv"
PAYSLIP = DATA / "virtual_payslip.csv"
DEPTS = ["시설관리팀", "환경미화팀", "복지운영팀", "주차관리팀"]
HOLIDAYS = {date(2026, 8, 17), date(2026, 9, 24), date(2026, 9, 25)}
START, END = date(2026, 7, 1), date(2026, 9, 30)
HEAVY = {"가상사원07": 0.68, "가상사원15": 0.42}
DUPLICATES = [("가상사원03", date(2026, 8, 12)), ("가상사원11", date(2026, 9, 3)), ("가상사원20", date(2026, 9, 16))]
JOINERS = {"가상사원25", "가상사원26"}
SHORT_PAID = {"가상사원09": 0.97, "가상사원22": 0.985}

def _at(day: date, hour: float) -> datetime:
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=round(hour * 60))


def generate_attendance(seed: int = 2026) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    staff = []
    for i in range(1, 27):
        name = f"가상사원{i:02d}"
        dept = "환경미화팀" if name in JOINERS else DEPTS[(i - 1) % 4]
        staff.append((name, dept, int(rng.integers(115, 156)) * 100))
    rows = []
    day = START
    while day <= END:
        weekday = day.weekday() < 5 and day not in HOLIDAYS
        for name, dept, wage in staff:
            if name in JOINERS and day < date(2026, 9, 1):
                continue
            hourly = round(wage * 1.03) if dept == "환경미화팀" and day.month == 9 else wage
            if not weekday:
                if day.weekday() == 5 and dept == "시설관리팀" and rng.random() < 0.12:
                    rows.append((name, dept, day, _at(day, 9), _at(day, 15 + rng.integers(0, 5)), hourly))
                continue
            if rng.random() < 0.012:
                continue
            start = 8.67 + rng.random() * 0.33
            end = 18 + rng.random() * 0.33
            if rng.random() < 0.04:
                start = 9.17 + rng.random() * 0.5
            if rng.random() < 0.02:
                end = 16.5 + rng.random()
            heavy = HEAVY.get(name, 0)
            surge = 0.42 if dept == "환경미화팀" and day.month == 9 else 0.10
            if rng.random() < heavy:
                end = 20.5 + rng.random() * 2.5
            elif rng.random() < surge:
                end = 19 + rng.random() * 1.2
            rows.append((name, dept, day, _at(day, start), _at(day, end), hourly))
        day += timedelta(days=1)
    df = pd.DataFrame(rows, columns=["직원", "부서", "날짜", "출근", "퇴근", "시급"])
    extra = [df[(df["직원"] == n) & (df["날짜"] == d)].head(1) for n, d in DUPLICATES]
    df = pd.concat([df, *extra], ignore_index=True).sort_values(["날짜", "직원"], ignore_index=True)
    return df


def ensure(seed: int = 2026, force: bool = False) -> None:
    if force or not ATT.exists():
        generate_attendance(seed).to_csv(ATT, index=False, encoding="utf-8-sig")
        PAYSLIP.unlink(missing_ok=True)


def load_attendance() -> pd.DataFrame:
    ensure()
    df = pd.read_csv(ATT, encoding="utf-8-sig", parse_dates=["출근", "퇴근"])
    df["날짜"] = pd.to_datetime(df["날짜"]).dt.date
    return df

