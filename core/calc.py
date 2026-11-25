"""재산출 엔진. 원본 엑셀의 수식 구조를 그대로 옮겼다."""
from __future__ import annotations

import math

from .data import Employee, load_employees, rate_values

HEADCOUNT = 3
DEFAULT_AWARD_RATE = 0.89995  # 지침 5-3 시설분야 단순노무용역 낙찰하한율


def floor10(x: float) -> int:
    """ROUNDDOWN(x,-1). 부동소수 오차로 10원 내려가는 것을 막는다."""
    return math.floor(round(x, 4) / 10) * 10


def calc_cleaning(r: dict, headcount: int = HEADCOUNT) -> dict[str, float]:
    daily = r["market_daily"]
    hourly = daily / 8
    x: dict[str, float] = {}
    x["기본급"] = hourly * 209 * 12
    x["연장근로수당"] = hourly * 2 * 1.5 * 142 / 3
    x["휴일근로수당"] = ((hourly * 8 * 6 * 1.5) + (hourly * 2 * 3 * 2)) / 3
    x["연차수당"] = daily * 11
    x["상여금"] = x["기본급"] / 12
    wage = sum(x.values())
    x["임금 소계"] = wage
    x["퇴직충당금"] = wage / 12
    x["인건비 계"] = wage + x["퇴직충당금"]
    x["산재보험"] = math.floor(wage * r["industrial"])
    x["국민연금"] = math.floor(wage * r["pension"])
    x["건강보험"] = math.floor(wage * r["health"])
    x["장기요양"] = math.floor(x["건강보험"] * r["cleaning_ltc"])
    x["고용보험"] = math.floor(wage * r["employment_employer"])
    x["임금채권보장"] = math.floor(wage * r["wage_claim"])
    x["피복비"] = 9500 * 12
    x["작업화"] = 4200 * 12
    x["복리후생비 계"] = sum(x[k] for k in ("산재보험", "국민연금", "건강보험", "장기요양", "고용보험", "임금채권보장", "피복비", "작업화"))
    x["합계(원가)"] = x["인건비 계"] + x["복리후생비 계"]
    x["일반관리비(9%)"] = x["합계(원가)"] * 0.09
    subtotal = x["합계(원가)"] + x["일반관리비(9%)"]
    x["이윤(10%)"] = subtotal * 0.10
    supply = subtotal + x["이윤(10%)"]
    x["공급가액"] = supply
    x["부가가치세"] = supply * 0.10
    x["1인 연간 총계"] = supply * 1.10
    x[f"{headcount}인 연간 총계"] = x["1인 연간 총계"] * headcount
    x["계약 기준금액(천원 미만 절사)"] = math.trunc(x[f"{headcount}인 연간 총계"] / 1000) * 1000
    return x


def cleaning_total(year: int) -> int:
    return calc_cleaning(rate_values(year))["계약 기준금액(천원 미만 절사)"]


def apply_award(total: float, labor: float, r: dict, award_rate: float = DEFAULT_AWARD_RATE) -> dict:
    """낙찰률 적용. 예정가격=기초금액(원가계산가격)으로 단순화한다."""
    hourly = r["market_daily"] / 8
    awarded_hourly = hourly * award_rate
    return {
        "낙찰률": award_rate,
        "낙찰 예상금액": math.trunc(total * award_rate / 1000) * 1000,
        "감액": total - math.trunc(total * award_rate / 1000) * 1000,
        "1인 최소 지급 노무비(연)": labor * award_rate,
        "낙찰률 적용 시급": awarded_hourly,
        "최저임금": r["min_wage"],
        "최저임금 충족": awarded_hourly >= r["min_wage"],
    }


def new_hourly(e: Employee, r: dict) -> float:
    return max(e.hourly, r["min_wage"])


def standard_income(e: Employee) -> int:
    """9월 공제액을 2026년 요율로 역산한 보수월액(천원 단위). 오차가 작은 보험부터 사용한다."""
    r0 = rate_values(2026)
    for amount, rate in ((e.pension, r0["pension"]), (e.health, r0["health"]), (e.employment, r0["employment_worker"])):
        if amount:
            return int(round(amount / rate, -3))
    return int(round(e.file_gross, -3))


def expected_pension(e: Employee, r: dict) -> int:
    """국민연금 대상일 때의 월 공제액. 보수월액은 시급 인상률만큼 변동한다."""
    income = math.floor(standard_income(e) * new_hourly(e, r) / e.hourly / 1000) * 1000
    return floor10(income * r["pension"])


def calc_employee(e: Employee, r: dict, enroll_pension: bool | None = None) -> dict:
    h = new_hourly(e, r)
    ratio = h / e.hourly
    ordinary = e.ordinary * ratio  # 가정: 통상임금은 노임단가와 같은 비율로 변동
    base = h * 8 * (e.work_days + e.paid_days)
    weekly = h * 8 * e.weekly_days
    family = 40000 * e.spouse + 30000 * e.child + 20000 * e.other
    ot = floor10(floor10(ordinary * 1.5 * e.overtime))
    hol = floor10(floor10(ordinary * 1.5 * e.holiday_8) + floor10(ordinary * 2 * e.holiday_over))
    avg = (e.jul_base * ratio + e.aug_base * ratio + base) / 3
    bonus = floor10(floor10(avg / 2))
    gross = base + weekly + family + e.meal + ot + hol + bonus

    income = math.floor(standard_income(e) * ratio / 1000) * 1000
    health = floor10(income * r["health"])
    ltc = floor10(health * r["ltc"])
    enrolled = e.enrolled if enroll_pension is None else enroll_pension
    pension = floor10(income * r["pension"]) if enrolled else 0
    employment = floor10(income * r["employment_worker"])
    deduct = health + ltc + pension + employment + e.income_tax + e.local_tax  # 세액은 9월 값 유지
    return {
        "성명": e.name, "시급": h, "통상시급": ordinary, "기본급": base, "주휴수당": weekly,
        "가족수당": family, "급식비": e.meal, "시간외": ot, "휴일근무": hol, "상여금": bonus,
        "지급계": gross, "건강보험": health, "장기요양": ltc, "국민연금": pension, "고용보험": employment,
        "소득세": e.income_tax, "지방소득세": e.local_tax, "공제계": deduct, "실수령액": gross - deduct,
    }


def calc_payroll(r: dict, staff: list[Employee] | None = None) -> list[dict]:
    return [calc_employee(e, r) for e in (staff or load_employees())]


def payroll_total(rows: list[dict], key: str = "지급계") -> float:
    return sum(x[key] for x in rows)


def age_on(birth, on) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def employer_insurance_rate(r: dict) -> float:
    """연도에 따라 바뀌는 사업주 부담 요율: 국민연금 + 건강보험 + 장기요양."""
    return r["pension"] + r["health"] * (1 + r["ltc"])


PENSION_OK, PENSION_MISSING, PENSION_EXEMPT, PENSION_UNKNOWN = "대상·공제 정상", "대상·공제 누락", "연령상 의무가입 제외", "생년월일 없음"


def pension_status(enrolled: bool, birth, on) -> tuple[str, int | None]:
    """기준일에 만 18세 이상 60세 미만이면 사업장가입 대상이다. (판정, 나이)를 돌려준다."""
    if birth is None:
        return PENSION_UNKNOWN, None
    age = age_on(birth, on)
    if not 18 <= age < 60:
        return PENSION_EXEMPT, age
    return (PENSION_OK if enrolled else PENSION_MISSING), age


# ───────────── 6차: 입력형 표준 산출, 근로 유형(프리랜서·아르바이트), 근로자 공제 ─────────────
STANDARD_DEFAULTS = {
    "job": "청소원(단순노무)",
    "headcount": HEADCOUNT,
    "monthly_hours": 209,          # 주 40시간 + 주휴 8시간을 월로 환산
    "work_days": 22,               # 월 근무일수(표시·임금지급 계획용)
    "ot_hours": 2 * 142 / 3 / 12,  # 월 연장근로시간: 원본 '2시간×142일÷3명'을 월로 환산
    "hol_hours": 8 * 6 / 3 / 12,   # 월 휴일근로시간(8시간 이내, 150%): 원본 '8시간×6일÷3명'
    "hol_over_hours": 2 * 3 / 3 / 12,  # 월 휴일 8시간 초과(200%): 원본 '2시간×3일÷3명'
    "leave_days": 11,              # 연차수당 일수(원본 11일)
    "daily": None,                 # None이면 적용 시점 시중노임단가
    "months": 12,
    "uniform": 9500,               # 피복비 월액(원본, 한국건물위생관리협회)
    "shoes": 4200,                 # 작업화 월액(원본)
}
STANDARD_JOB = "청소원(단순노무)"


def standard_inputs(**kw) -> dict:
    return {**STANDARD_DEFAULTS, **{k: v for k, v in kw.items() if v is not None}}


def calc_standard(inputs: dict, r: dict) -> dict[str, float]:
    """입력형 표준 산출. 기본 입력이면 calc_cleaning()과 1원 단위까지 같다(산식 순서도 같게 둔다)."""
    p = standard_inputs(**inputs)
    daily = p["daily"] or r["market_daily"]
    hourly = daily / 8
    months, n = p["months"], int(p["headcount"])
    x: dict[str, float] = {}
    x["기본급"] = hourly * p["monthly_hours"] * months
    x["연장근로수당"] = hourly * 2 * 1.5 * (p["ot_hours"] * months / 2)
    x["휴일근로수당"] = ((hourly * 8 * 1.5 * (p["hol_hours"] * months / 8)) + (hourly * 2 * 2 * (p["hol_over_hours"] * months / 2)))
    x["연차수당"] = daily * p["leave_days"]
    x["상여금"] = x["기본급"] / 12
    wage = sum(x.values())
    x["임금 소계"] = wage
    x["퇴직충당금"] = wage / 12
    x["인건비 계"] = wage + x["퇴직충당금"]
    x["산재보험"] = math.floor(wage * r["industrial"])
    x["국민연금"] = math.floor(wage * r["pension"])
    x["건강보험"] = math.floor(wage * r["health"])
    x["장기요양"] = math.floor(x["건강보험"] * r["cleaning_ltc"])
    x["고용보험"] = math.floor(wage * r["employment_employer"])
    x["임금채권보장"] = math.floor(wage * r["wage_claim"])
    x["피복비"] = p["uniform"] * months
    x["작업화"] = p["shoes"] * months
    x["복리후생비 계"] = sum(x[k] for k in ("산재보험", "국민연금", "건강보험", "장기요양", "고용보험", "임금채권보장", "피복비", "작업화"))
    x["합계(원가)"] = x["인건비 계"] + x["복리후생비 계"]
    x["일반관리비(9%)"] = x["합계(원가)"] * 0.09
    subtotal = x["합계(원가)"] + x["일반관리비(9%)"]
    x["이윤(10%)"] = subtotal * 0.10
    supply = subtotal + x["이윤(10%)"]
    x["공급가액"] = supply
    x["부가가치세"] = supply * 0.10
    x["1인 연간 총계"] = supply * 1.10
    x[f"{n}인 연간 총계"] = x["1인 연간 총계"] * n
    x["계약 기준금액(천원 미만 절사)"] = math.trunc(x[f"{n}인 연간 총계"] / 1000) * 1000
    return x


def standard_rates(r: dict) -> dict:
    """공단 산정용 요율: 장기요양은 산출내역 기재값이 아니라 법정 요율을 쓴다."""
    return {**r, "cleaning_ltc": r["ltc"]}


def calc_freelancer(fee: float) -> dict:
    """프리랜서(사업소득): 소득세 3%, 지방소득세 0.3%(소득세의 10%), 각각 10원 미만 절사. 4대보험 없음."""
    income_tax = floor10(fee * 0.03)
    local_tax = floor10(income_tax * 0.1)
    return {"지급액": fee, "소득세(3%)": income_tax, "지방소득세(0.3%)": local_tax, "원천징수 계": income_tax + local_tax,
            "실지급액": fee - income_tax - local_tax, "4대보험": 0}


WEEKS_PER_MONTH = 365 / 7 / 12  # 월 평균 주 수(약 4.345주)


def calc_parttime(hourly: float, weekly_hours: float, weeks: int, r: dict, months_continuous: int = 1) -> dict:
    """아르바이트(단시간). 주 15시간 이상이면 주휴수당, 월 소정근로 60시간 미만이면 국민연금·건강·고용 제외(예외는 확인 필요)."""
    base = hourly * weekly_hours * weeks
    weekly_ok = weekly_hours >= 15
    juhyu_hours = min(weekly_hours, 40) / 40 * 8 if weekly_ok else 0.0
    juhyu = juhyu_hours * hourly * weeks
    gross = base + juhyu
    monthly_hours = weekly_hours * WEEKS_PER_MONTH
    small = monthly_hours < 60
    flags = []
    if hourly < r["min_wage"]:
        flags.append({"상태": "미달", "내용": f"시급 {hourly:,.0f}원이 최저임금 {r['min_wage']:,}원보다 낮습니다."})
    if not weekly_ok:
        flags.append({"상태": "정상", "내용": "주 소정근로 15시간 미만: 주휴수당·연차·퇴직금 제외(근로기준법 제18조 제3항)."})
    retire = gross / 12 if weekly_ok and weeks >= 52 else 0.0
    if weekly_ok and weeks < 52:
        flags.append({"상태": "정상", "내용": "1년 미만 근로: 퇴직금 없음. 연차는 1개월 개근 시 1일 발생(근로기준법 제60조), 별도 확인."})
    months = weeks / (365 / 7 / 12)
    month_gross = gross / months if months else 0.0
    ins = {"산재보험": math.floor(gross * r["industrial"])}
    if small:
        ins.update({"국민연금": 0, "건강보험": 0, "장기요양": 0, "고용보험": 0})
        if months_continuous >= 3:
            flags.append({"상태": "확인 필요", "내용": "월 60시간 미만이지만 3개월 이상 계속 근로: 국민연금·고용보험 적용 예외 여부 확인 필요(가정)."})
    else:
        health = math.floor(gross * r["health"])
        ins.update({"국민연금": math.floor(gross * r["pension"]), "건강보험": health, "장기요양": math.floor(health * r["ltc"]),
                    "고용보험": math.floor(gross * r["employment_employer"])})
    return {"시급": hourly, "주 소정시간": weekly_hours, "주 수": weeks, "월 소정시간": monthly_hours, "기본급": base, "주휴수당": juhyu,
            "주휴시간(주)": juhyu_hours, "지급 계": gross, "월평균 지급": month_gross, "퇴직충당금": retire, "사업주 보험": ins,
            "보험 계": sum(ins.values()), "주15시간 이상": weekly_ok, "월60시간 미만": small, "flags": flags}


def worker_monthly(x: dict, r: dict, months: int = 12) -> dict:
    """근로자 1인 월 기준 받는 돈과 근로자 부담 공제(소득세는 간이세액표라 산출하지 않음)."""
    pay = {"기본급": x["기본급"] / months, "연장근로수당": x["연장근로수당"] / months, "휴일근로수당": x["휴일근로수당"] / months,
           "연차수당(월 환산)": x["연차수당"] / months, "상여금(월 환산)": x["상여금"] / months}
    wage = sum(pay.values())
    health = floor10(wage * r["health"])
    deduct = {"국민연금": floor10(wage * r["pension"]), "건강보험": health, "장기요양": floor10(health * r["ltc"]),
              "고용보험": floor10(wage * r["employment_worker"])}
    return {"pay": pay, "월 임금": wage, "deduct": deduct, "공제 계(세금 제외)": sum(deduct.values()),
            "퇴직충당금(월 적립)": x["퇴직충당금"] / months}
