"""가상 근태 기반 수당 계산, 중복 입력 탐지, 분기 임금명세서 미달 확인(지침 6-2-2)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from .virtual import HOLIDAYS, SHORT_PAID, load_attendance

FORMULA = ("연장수당 = 시급 × 1.5 × 1일 8시간 초과시간 / 야간가산 = 시급 × 0.5 × 22~06시 근로시간 / "
           "휴일수당 = 시급 × 1.5 × 8시간 이내 + 시급 × 2.0 × 8시간 초과 (근로기준법 제56조)")


def _night_minutes(start: datetime, end: datetime) -> float:
    total = 0.0
    day = start.date() - timedelta(days=1)
    while day <= end.date():
        a = datetime.combine(day, datetime.min.time()) + timedelta(hours=22)
        b = a + timedelta(hours=8)
        total += max(0, (min(end, b) - max(start, a)).total_seconds() / 60)
        day += timedelta(days=1)
    return total


def day_pay(start: datetime, end: datetime, hourly: float, day: date) -> dict:
    span = (end - start).total_seconds() / 60
    rest = 60 if span >= 480 else 30 if span >= 240 else 0
    work = max(span - rest, 0)
    night = _night_minutes(start, end)
    is_holiday = day.weekday() >= 5 or day in HOLIDAYS
    if is_holiday:
        ot, hol = 0.0, work
        hol_pay = hourly * (min(work, 480) * 1.5 + max(work - 480, 0) * 2.0) / 60
        ot_pay = 0.0
    else:
        ot, hol, hol_pay = max(work - 480, 0), 0.0, 0.0
        ot_pay = hourly * 1.5 * ot / 60
    return {"근로분": work, "연장분": ot, "야간분": night, "휴일분": hol, "연장수당": ot_pay,
            "야간가산": hourly * 0.5 * night / 60, "휴일수당": hol_pay}


def enrich(df: pd.DataFrame | None = None) -> pd.DataFrame:
    df = load_attendance() if df is None else df
    pays = [day_pay(s.to_pydatetime(), e.to_pydatetime(), h, d) for s, e, h, d in zip(df["출근"], df["퇴근"], df["시급"], df["날짜"])]
    out = pd.concat([df.reset_index(drop=True), pd.DataFrame(pays)], axis=1)
    out["월"] = pd.to_datetime(out["날짜"]).dt.strftime("%Y-%m")
    out["수당"] = out["연장수당"] + out["야간가산"] + out["휴일수당"]
    weekday = pd.to_datetime(out["날짜"]).dt.weekday < 5
    non_holiday = ~out["날짜"].isin(HOLIDAYS)
    out["지각"] = weekday & non_holiday & (out["출근"].dt.hour * 60 + out["출근"].dt.minute > 540)
    out["조퇴"] = weekday & non_holiday & (out["퇴근"].dt.hour * 60 + out["퇴근"].dt.minute < 1080)
    return out


def duplicates(e: pd.DataFrame) -> pd.DataFrame:
    keys = ["직원", "날짜", "출근", "퇴근"]
    dup = e[e.duplicated(keys, keep="first")].copy()
    dup["과지급 위험"] = dup["수당"] + dup["시급"] * 8
    return dup[["직원", "부서", "날짜", "출근", "퇴근", "과지급 위험"]]


def clean(e: pd.DataFrame) -> pd.DataFrame:
    return e.drop_duplicates(["직원", "날짜", "출근", "퇴근"]).copy()


def attendance_summary(e: pd.DataFrame) -> pd.DataFrame:
    c = clean(e)
    workdays = sorted(d for d in c["날짜"].unique() if d.weekday() < 5 and d not in HOLIDAYS)
    rows = []
    for (name, dept), g in c.groupby(["직원", "부서"]):
        first = g["날짜"].min()
        expected = sum(d >= first for d in workdays)
        attended = g[g["날짜"].isin(workdays)]["날짜"].nunique()
        rows.append({"직원": name, "부서": dept, "지각": int(g["지각"].sum()), "조퇴": int(g["조퇴"].sum()), "결근": expected - attended,
                     "초과근무(시간)": round(g["연장분"].sum() / 60, 1), "야간(시간)": round(g["야간분"].sum() / 60, 1), "휴일(시간)": round(g["휴일분"].sum() / 60, 1),
                     "수당 합계": round(g["수당"].sum())})
    return pd.DataFrame(rows)


def payslip_check(e: pd.DataFrame) -> pd.DataFrame:
    """분기 개인 임금명세서 확인 목록(지침 6-2-2). 제출액은 가상 값이며 2명을 미달로 심어 두었다."""
    c = clean(e)
    person = c.groupby(["직원", "부서", "월"], as_index=False).agg(시급=("시급", "max"), 수당=("수당", "sum"))
    person["산정액"] = person["시급"] * 209 + person["수당"]
    q = person.groupby(["직원", "부서"], as_index=False)["산정액"].sum()
    q["제출액"] = [round(v * SHORT_PAID.get(n, 1), -1) if n in SHORT_PAID else round(v) for n, v in zip(q["직원"], q["산정액"])]
    q["산정액"] = q["산정액"].round()
    q["차액"] = q["제출액"] - q["산정액"]
    q["확인 결과"] = ["미달" if d < -1000 else "적정" for d in q["차액"]]
    return q.sort_values("차액", ignore_index=True)
