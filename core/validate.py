"""규칙 기반 검증. 단정할 수 없는 항목은 '확인 필요'로 구분한다."""
from __future__ import annotations

import calendar
import copy
import re
from dataclasses import asdict, dataclass

from openpyxl.utils import get_column_letter, range_boundaries

from .calc import PENSION_EXEMPT, PENSION_MISSING, PENSION_OK, PENSION_UNKNOWN, calc_cleaning, expected_pension, floor10, pension_status
from .data import PAY_FIRST, PAY_LAST, load_births, load_contracts, load_employees, open_book, rate_values, standards
from .guide import cite

ERROR, CHECK, INFO = "오류", "확인 필요", "참고"


@dataclass
class Finding:
    severity: str
    category: str
    source: str
    cell: str
    target: str
    title: str
    evidence: str
    basis: str
    action: str
    amount: float = 0


def is_formula(v) -> bool:
    return isinstance(v, str) and v.startswith("=")


def weekdays(year: int, month: int) -> int:
    return sum(1 for d in range(1, calendar.monthrange(year, month)[1] + 1) if calendar.weekday(year, month, d) < 5)


def inject_demo_errors(f, v):
    """시연용 오류를 메모리 사본에만 넣는다. 원본 파일은 건드리지 않는다."""
    f, v = _clone(f), _clone(v)
    f["AD9"].value = 3022660; v["AD9"].value = 3022660            # 실수령액 수식을 값으로 덮어씀
    f["U10"].value = "=SUM(V10:AA10)"; v["U10"].value = 238370 - 6990  # 지방소득세 미차감
    v["AD10"].value = v["J10"].value - v["U10"].value
    f["Y13"].value = None; v["Y13"].value = None                    # 고용보험 공란
    return f, v


def _clone(ws):
    wb = ws.parent
    return copy.deepcopy(wb).worksheets[0]


def pension_summary(births: dict | None = None, values=None) -> dict:
    """사원별 국민연금 대상 판정과 건수."""
    births = load_births() if births is None else births
    today = load_contracts()["demo_today"]
    rows = []
    for e in load_employees(values):
        status, age = pension_status(e.enrolled, births.get(e.name), today)
        rows.append({"성명": e.name, "나이": age, "9월 공제액": e.pension, "판정": status})
    count = lambda s: sum(x["판정"] == s for x in rows)
    return {"rows": rows, "정상": count(PENSION_OK), "누락": count(PENSION_MISSING),
            "제외": sum(x["판정"] == PENSION_EXEMPT and not x["9월 공제액"] for x in rows),
            "연령 확인": sum(x["판정"] == PENSION_EXEMPT and bool(x["9월 공제액"]) for x in rows), "미입력": count(PENSION_UNKNOWN)}


def check_payroll(f, v, year: int, births: dict | None = None) -> list[Finding]:
    out: list[Finding] = []
    src = "기간제 급여"
    rates = rate_values(year)
    births = load_births() if births is None else births
    today = load_contracts()["demo_today"]
    r26 = rate_values(2026)
    staff = load_employees(v)
    enrolled = [e.name for e in staff if e.enrolled]

    for i, r in enumerate(range(PAY_FIRST, PAY_LAST + 1)):
        name = f"사원{i + 1}"
        # 1) 실수령액 수식
        if not is_formula(f[f"AD{r}"].value):
            out.append(Finding(ERROR, "실수령액 수식 누락", src, f"AD{r}", name, "실수령액이 수식이 아닌 고정값입니다",
                               f"AD{r}={f[f'AD{r}'].value:,}. 같은 열의 다른 행은 =J-U 수식입니다.",
                               "급여대장 머리글 '실수령액(A-B)' 산식", f"AD{r}에 =J{r}-U{r} 복원"))
        elif f[f"AD{r}"].value.replace("$", "") != f"=J{r}-U{r}":
            out.append(Finding(ERROR, "실수령액 수식 누락", src, f"AD{r}", name, "실수령액 수식이 표준과 다릅니다",
                               f"현재 {f[f'AD{r}'].value}", "급여대장 머리글 '실수령액(A-B)' 산식", f"=J{r}-U{r}로 수정"))
        gross, deducted, net = (v[f"{c}{r}"].value or 0 for c in ("J", "U", "AD"))
        if v[f"AD{r}"].value is None or abs(net - (gross - deducted)) >= 1:
            out.append(Finding(ERROR, "실수령액 값 불일치", src, f"AD{r}", name, "실수령액이 지급액-공제액과 다릅니다",
                               f"지급 {gross:,}원 - 공제 {deducted:,}원 = {gross - deducted:,}원인데 실수령액은 {net:,}원입니다.",
                               "급여대장 머리글 '실수령액(A-B)' 산식", "수식 복원 후 재계산", abs(net - (gross - deducted))))
        # 2) 공제 합계
        if f[f"U{r}"].value != f"=SUM(V{r}:AB{r})":
            parts = sum(v[f"{c}{r}"].value or 0 for c in ("V", "W", "X", "Y", "Z", "AA", "AB"))
            gap = parts - (v[f"U{r}"].value or 0)
            out.append(Finding(ERROR, "공제 미차감", src, f"U{r}", name, "공제 합계에 빠진 항목이 있습니다",
                               f"현재 {f[f'U{r}'].value}. 항목 합 {parts:,}원, 공제계 {v[f'U{r}'].value:,}원, 차이 {gap:,}원.",
                               "급여대장 공제액 계(B)=건강~지방소득세", f"=SUM(V{r}:AB{r})로 수정", gap))
        # 3) 국민연금
        expected = expected_pension(staff[i], r26)
        status, age = pension_status(staff[i].enrolled, births.get(name), today)
        law = "국민연금법상 사업장가입자는 18세 이상 60세 미만. " + cite("6-2-2")
        if status == PENSION_UNKNOWN and not staff[i].enrolled:
            out.append(Finding(CHECK, "보험 대상자 누락", src, f"X{r}", name, "국민연금 공제가 공란입니다",
                               f"같은 보수의 {', '.join(enrolled)}은(는) {expected:,}원을 공제합니다. 생년월일이 없어 대상 여부를 확정할 수 없습니다.",
                               law, f"생년월일 확인. 60세 미만이면 월 {expected:,}원 공제 및 소급 검토", expected))
        elif status == PENSION_MISSING:
            out.append(Finding(ERROR, "보험 대상자 누락", src, f"X{r}", name, f"만 {age}세(가상 생년월일)인데 국민연금 공제가 없습니다",
                               f"기준일 {today} 기준 대상 연령이지만 공란입니다. 예상 공제 {expected:,}원.", law, "취득신고 및 소급 공제 검토", expected))
        elif status == PENSION_EXEMPT and not staff[i].enrolled:
            out.append(Finding(INFO, "국민연금 연령 제외", src, f"X{r}", name, f"만 {age}세(가상 생년월일)라 의무가입 대상이 아닙니다",
                               f"기준일 {today} 기준 공란이 정상입니다.", law, "조치 없음"))
        elif status == PENSION_EXEMPT:
            out.append(Finding(CHECK, "국민연금 연령 확인", src, f"X{r}", name, f"만 {age}세(가상 생년월일)인데 국민연금을 공제하고 있습니다",
                               f"의무가입 연령이 아니므로 공제액 {staff[i].pension:,.0f}원의 근거를 확인해야 합니다.", law, "임의계속가입 여부 확인"))
        # 4) 법정 공제 공란 (산재보험 Z열은 사업주 전액 부담이라 공란이 정상)
        for col, label in (("V", "건강보험"), ("W", "장기요양보험"), ("Y", "고용보험")):
            if not v[f"{col}{r}"].value:
                out.append(Finding(ERROR, "법정 항목 공란", src, f"{col}{r}", name, f"{label} 공제가 공란입니다",
                                   "같은 열의 다른 직원은 모두 공제액이 있습니다.", "4대 사회보험 관계 법령. " + cite("6-2-2"), f"{label} 공제액 입력"))

        # 지방소득세 = 소득세 × 10%, 10원 미만 버림
        tax, local = v[f"AA{r}"].value or 0, v[f"AB{r}"].value or 0
        due = floor10(tax * standards()["local_income_tax_rate"])
        if tax and local != due:
            out.append(Finding(CHECK, "지방소득세 불일치", src, f"AB{r}", name, "지방소득세가 소득세의 10%와 다릅니다",
                               f"소득세 {tax:,}원의 10%(10원 미만 버림)는 {due:,}원인데 입력값은 {local:,}원으로 {local - due:+,}원 차이입니다.",
                               "지방세법상 개인지방소득세(근로소득 특별징수)는 소득세의 10%", "간이세액표·원천징수 내역과 대조", abs(local - due)))

    # 5) 월 평일수 초과
    for i in range(9):
        for col, year_m, label in (("V", 7, "7월"), ("W", 8, "8월")):
            ref = f"{col}{19 + i}"
            wage = v[f"H{PAY_FIRST + i}"].value
            days = (v[ref].value or 0) / (wage * 8)
            limit = weekdays(2026, year_m)
            if days > limit:
                months = [v[f"{c}{19 + i}"].value or 0 for c in ("V", "W", "X")]
                capped = [limit * wage * 8 if c == col else m for c, m in zip(("V", "W", "X"), months)]
                effect = floor10(sum(months) / 3 / 2) - floor10(sum(capped) / 3 / 2)
                out.append(Finding(CHECK, "근무일수 이상", src, ref, f"사원{i + 1}", f"{label} 기본급이 평일수를 초과합니다",
                                   f"{v[ref].value:,}원은 {days:.0f}일분이지만 2026년 {label} 평일은 {limit}일입니다. 3개월 평균 상여금이 {effect:,}원 늘어납니다.",
                                   "산출근거 '상여금: 3개월 간 기본급 평균*0.5'", "해당 월 근무 실적과 대조", effect))

    # 6) 산출근거 공란
    if not any(v[f"Y{r}"].value for r in range(30, 39)):
        out.append(Finding(CHECK, "법정 항목 공란", src, "V30:Y38", "전원", "연가보상비 산출표가 비어 있습니다",
                           "연차·사용연차·잔여연차가 모두 공란이라 연가보상비가 0원으로 계산됩니다.", "근로기준법 제60조(연차 유급휴가)", "연차 사용 내역 입력 또는 해당 없음 기재"))
    if not any(v[f"W{r}"].value for r in range(41, 50)):
        out.append(Finding(CHECK, "법정 항목 공란", src, "W41:X49", "전원", "유급휴일 내역이 비어 있습니다",
                           f"D열 유급휴일은 2~4.5일이 입력되어 있으나 날짜·사유 표가 공란입니다.", "급여대장 '유급휴일' 산출근거", "휴일 날짜와 사유 기재"))
    if not any(v[f"Q{r}"].value for r in range(PAY_FIRST, PAY_LAST + 1)):
        out.append(Finding(CHECK, "법정 항목 공란", src, "Q6:Q14", "전원", "추석이 있는 9월인데 명절휴가비가 공란입니다",
                           "2026년 추석은 9월 25일입니다. 지급 대상이 아니면 정상입니다.", "내부 보수규정 확인 사항(법정 의무 항목 아님)", "지급 규정 확인"))
    # 7) 옛 단가
    if year >= 2027:
        low = [f"사원{i + 1}" for i, r in enumerate(range(PAY_FIRST, PAY_LAST + 1)) if (v[f"H{r}"].value or 0) < rates["min_wage"]]
        if low:
            current = min(e.hourly for e in staff)
            gap = rates["min_wage"] - current
            out.append(Finding(ERROR, "옛 단가 잔존", src, "H6:H14", f"{len(low)}명", "시급이 2027년 최저임금보다 낮습니다",
                               f"현재 {current:,}원, 2027년 최저임금 {rates['min_wage']:,}원, 시간당 {gap:,}원 부족합니다.", "최저임금법. " + cite("5-2-c"), f"시급을 {rates['min_wage']:,}원 이상으로 변경"))
    return out


def check_cleaning(f, v, year: int) -> list[Finding]:
    out: list[Finding] = []
    src = "청소용역"
    r26, r27 = rate_values(2026), rate_values(2027)
    c = calc_cleaning(r26)

    daily = v["K3"].value
    written = re.search(r"([0-9]{2,3},[0-9]{3})원", str(v["F7"].value))
    if written and int(written.group(1).replace(",", "")) != daily:
        old_daily = written.group(1)
        out.append(Finding(ERROR, "옛 단가 잔존", src, "F7", "연차수당", f"산출근거에 옛 일급 {old_daily}원이 남아 있습니다",
                           f"수식은 {daily:,}원×11일={v['D7'].value:,.0f}원인데 설명은 {old_daily}원입니다.", cite("붙임4-유의"), f"산출근거를 {daily:,}원으로 수정"))
    if "2024" in str(v["J3"].value):
        out.append(Finding(ERROR, "옛 날짜 잔존", src, "J3:J4", "노임단가 표기", "단가 출처가 2024년으로 적혀 있습니다",
                           f"{daily:,}원은 2026년 상반기 조사 단가인데 '2024년 6월, 24년 10월 적용'으로 표기되어 있습니다.", f"지침 5-2: “2026년 상반기 조사 : {r26['market_daily']:,}원(일급) → 2026년 하반기 적용”", "출처와 적용 시기 수정"))
    if "2020" in str(v["G14"].value):
        out.append(Finding(CHECK, "옛 날짜 잔존", src, "G14", "산재보험", "2020년 고시를 근거로 적었습니다",
                           "'고용노동부고시 제2020-145호'가 2027년 산출내역에 남아 있습니다.", "붙임 4: “2026년도 사업종류별 산재보험요율”", "최신 고시의 요율 확인"))
    if "12.95" in str(v["B17"].value):
        target = r27["cleaning_ltc"]
        gap = (target - r26["cleaning_ltc"]) * c["건강보험"]
        total_gap = gap * 1.09 * 1.1 * 1.1 * 3
        out.append(Finding(ERROR, "옛 단가 잔존", src, "B17·D17", "장기요양", f"장기요양 요율이 옛 값 {r26['cleaning_ltc']:.2%}입니다",
                           f"2026년 요율은 {r26['ltc']:.2%}, 2027년 요율은 {target:.2%}입니다. 2027년 기준으로 1인 연 {gap:,.0f}원, 3인 총액 약 {total_gap:,.0f}원 과소 계상됩니다.",
                           cite("붙임4-요양"), f"요율을 {target:.2%}로 수정", total_gap))
    if f["D31"].value == "=SUM(D27:D30)":
        out.append(Finding(ERROR, "수식 범위 오류", src, "D31", "경비 소계", "경비 소계가 사업소세(D26)를 빠뜨립니다",
                           "수식이 =SUM(D27:D30)입니다. 지금은 D26이 0원이라 금액 영향이 없지만 값이 입력되면 누락됩니다.", cite("5-5-3"), "=SUM(D26:D30)으로 수정"))
    if "일반관리비" not in str(v["F35"].value):
        out.append(Finding(INFO, "산출근거 불일치", src, "F35", "이윤", "이윤 산출근거 설명에 일반관리비가 빠져 있습니다",
                           "실제 수식은 (원가+일반관리비)×10%로 지침과 맞지만 설명은 '(인+복후+경)*10%'입니다.", cite("붙임4-이윤"), "설명 문구 수정"))
    if "*11일" in str(v["F7"].value):
        extra = 4 * r26["market_daily"]
        out.append(Finding(CHECK, "법정 항목 확인", src, "D7", "연차수당", "연차를 11일로 계상했습니다",
                           f"지침 예시는 15일입니다. 15일 기준이면 1인 연 {extra:,}원(원가 기준)이 늘어납니다. 근속 1년 미만 전제라면 11일이 맞습니다.", cite("붙임4-연차"), "근속 구성 확인 후 일수 결정", extra))
    if "시행령 제36조" in str(v["G16"].value):
        out.append(Finding(INFO, "옛 근거 잔존", src, "G16", "건강보험", "시행령 조문이 지침 예시와 다릅니다",
                           "산출내역은 '시행령 제36조', 지침 붙임 4는 '같은법 시행령 제44조'입니다.", "붙임 4 건강보험료 관련규정", "조문 확인 후 수정"))
    if year >= 2027:
        out.append(Finding(ERROR, "옛 단가 잔존", src, "K3", "시중노임단가", "2027년 기준이 아닌 단가가 입력되어 있습니다",
                           f"K3={v['K3'].value:,}원, 2027년 적용값 {r27['market_daily']:,}원(시연용 가정값).", cite("5-2-b"), "재산출 결과 반영"))
        out.append(Finding(ERROR, "옛 단가 잔존", src, "B15·D15", "국민연금", f"국민연금 요율이 {r26['pension']:.2%}로 남아 있습니다",
                           f"2027년 사용자 부담률은 {r27['pension']:.2%}입니다.", f"국민연금법 단계 인상(2027년 합계 {r27['pension'] * 2:.1%})", f"요율을 {r27['pension']:.2%}로 수정"))
    return out


def run_validation(year: int, demo: bool = False, births: dict | None = None) -> list[Finding]:
    cf, cv = open_book("청소용역")
    pf, pv = open_book("기간제")
    if demo:
        pf, pv = inject_demo_errors(pf, pv)
    order = {ERROR: 0, CHECK: 1, INFO: 2}
    return sorted(check_payroll(pf, pv, year, births) + check_cleaning(cf, cv, year), key=lambda x: order[x.severity])


def as_rows(findings: list[Finding]) -> list[dict]:
    return [asdict(x) for x in findings]


def payroll_values(demo: bool = False):
    f, v = open_book("기간제")
    return inject_demo_errors(f, v)[1] if demo else v


def cell_marks(findings: list[Finding], source: str) -> dict[str, str]:
    """셀 주소 → 심각도. 범위(H6:H14)는 펼치고 오류가 확인 필요보다 우선한다."""
    marks: dict[str, str] = {}
    for x in sorted((f for f in findings if f.source == source and f.severity != INFO), key=lambda f: f.severity != CHECK):
        for token in re.split(r"[·,]", x.cell):
            for row in ws_range(token):
                marks[row] = x.severity
    return marks


def ws_range(token: str) -> list[str]:
    if ":" not in token:
        return [token]
    c1, r1, c2, r2 = range_boundaries(token)
    return [f"{get_column_letter(c)}{r}" for c in range(c1, c2 + 1) for r in range(r1, r2 + 1)]
