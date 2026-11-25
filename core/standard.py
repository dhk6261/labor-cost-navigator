"""공단 표준 산출서 양식과 상태 판정.

칸: 구분 | 항목 | 업체 금액 | 공단 산정 금액 | 차이 | 산식 | 산정기준·근거 | 상태 | 오류 정정 필요
상태: 누락(주황) · 미달(빨강) · 과지급(보라) · 확인 필요(노랑) · 정상. 판정 기준값은 data/판정기준.json(가정).
금액은 core/calc.py 결과(공단 산정) 또는 업체 금액을 그대로 쓰고, 이 모듈은 배치·판정만 한다.
"""
from __future__ import annotations

import json
import math

from .calc import DEFAULT_AWARD_RATE, STANDARD_DEFAULTS, STANDARD_JOB, calc_standard, standard_inputs, standard_rates
from .data import DATA, load_rates, standards
from .guide import cite

OK, MISSING, LOW, OVER, CHECK = "정상", "누락", "미달", "과지급", "확인 필요"
STATUS_ORDER = {MISSING: 0, LOW: 1, OVER: 2, CHECK: 3, OK: 4}
FLAGGED = (MISSING, LOW, OVER)   # 오류 정정 필요(☑)가 자동으로 붙는 상태
JUDGE = DATA / "판정기준.json"
LABOR, LEGAL, EXPENSE = "인건비", "법정부담금", "경비"
TOTAL = "계약 기준금액(천원 미만 절사)"

WAGE_ITEMS = ["기본급", "연장근로수당", "휴일근로수당", "연차수당", "상여금"]
INSURANCE = {"산재보험": "industrial", "국민연금": "pension", "건강보험": "health", "고용보험": "employment_employer", "임금채권보장": "wage_claim"}
LEGAL_ITEMS = ["산재보험", "국민연금", "건강보험", "장기요양", "고용보험", "임금채권보장"]
EXPENSE_ITEMS = ["피복비", "작업화", "일반관리비(9%)", "이윤(10%)", "부가가치세"]
BASE_ITEMS = WAGE_ITEMS + ["퇴직충당금"] + LEGAL_ITEMS + EXPENSE_ITEMS  # 업체가 제출하는 17개 항목
REQUIRED = WAGE_ITEMS + ["퇴직충당금"] + LEGAL_ITEMS                    # 필수 12개
DICT_TO_STD = {"일반관리비": "일반관리비(9%)", "이윤": "이윤(10%)"}       # 사전 표기 → 표준 항목명


def layout(headcount: int) -> list[tuple[str, str, bool]]:
    """(구분, 항목, 소계 여부) 순서."""
    return ([(LABOR, k, False) for k in WAGE_ITEMS] + [(LABOR, "임금 소계", True), (LABOR, "퇴직충당금", False), (LABOR, "인건비 계", True)]
            + [(LEGAL, k, False) for k in LEGAL_ITEMS] + [(LEGAL, "법정부담금 계", True)]
            + [(EXPENSE, "피복비", False), (EXPENSE, "작업화", False), (EXPENSE, "합계(원가)", True), (EXPENSE, "일반관리비(9%)", False),
               (EXPENSE, "이윤(10%)", False), (EXPENSE, "공급가액", True), (EXPENSE, "부가가치세", False), (EXPENSE, "1인 연간 총계", True),
               (EXPENSE, f"{headcount}인 연간 총계", True), (EXPENSE, TOTAL, True)])


def pct(v: float) -> str:
    """요율 표기: 최소 소수 둘째 자리(13.90%), 필요하면 셋째 자리(3.595%)."""
    text = f"{v * 100:.3f}"
    return (text[:-1] if text.endswith("0") else text) + "%"


def complete(amounts: dict, headcount: int) -> dict:
    """업체 17개 항목에서 소계를 만든다. 계산 엔진 결과처럼 소계가 이미 있으면 그대로 둔다."""
    a = {k: (amounts.get(k) or 0) for k in BASE_ITEMS}
    out = dict(amounts)
    if "임금 소계" not in out:
        out["임금 소계"] = sum(a[k] for k in WAGE_ITEMS)
        out["인건비 계"] = out["임금 소계"] + a["퇴직충당금"]
    out.setdefault("법정부담금 계", sum(a[k] for k in LEGAL_ITEMS))
    if "합계(원가)" not in out:
        out["합계(원가)"] = out["인건비 계"] + out["법정부담금 계"] + a["피복비"] + a["작업화"]
        out["공급가액"] = out["합계(원가)"] + a["일반관리비(9%)"] + a["이윤(10%)"]
        out["1인 연간 총계"] = out["공급가액"] + a["부가가치세"]
    out.setdefault(f"{headcount}인 연간 총계", out["1인 연간 총계"] * headcount)
    out.setdefault(TOTAL, math.trunc(out[f"{headcount}인 연간 총계"] / 1000) * 1000)
    return out


def formulas(r: dict, inputs: dict, headcount: int) -> dict[str, str]:
    """산식 칸. 값은 단가 파일과 입력에서 읽어 만든다."""
    p = standard_inputs(**inputs)
    daily = p["daily"] or r["market_daily"]
    label = "시중노임단가" if not p["daily"] or p["daily"] == r["market_daily"] else "일급(입력)"
    h, m = p["monthly_hours"], p["months"]
    return {
        "기본급": f"{label} {daily:,.0f}원 ÷ 8 × {h:g}시간 × {m}월",
        "연장근로수당": f"시급 {daily / 8:,.3f}원 × 150% × 월 {p['ot_hours']:.2f}시간 × {m}월",
        "휴일근로수당": f"시급 × 150% × 월 {p['hol_hours']:.2f}시간 × {m}월 + 시급 × 200% × 월 {p['hol_over_hours']:.2f}시간 × {m}월",
        "연차수당": f"일급 {daily:,.0f}원 × {p['leave_days']:g}일",
        "상여금": "기본급 × 100% ÷ 12 (연 1개월분, 50%씩 2회)",
        "임금 소계": "기본급 + 제수당 + 상여금",
        "퇴직충당금": "임금 소계 ÷ 12월",
        "인건비 계": "임금 소계 + 퇴직충당금",
        "산재보험": f"임금 소계 × {pct(r['industrial'])}",
        "국민연금": f"임금 소계 × {pct(r['pension'])}",
        "건강보험": f"임금 소계 × {pct(r['health'])}",
        "장기요양": f"건강보험료 × {pct(r['cleaning_ltc'])}",
        "고용보험": f"임금 소계 × {pct(r['employment_employer'])}",
        "임금채권보장": f"임금 소계 × {pct(r['wage_claim'])}",
        "법정부담금 계": "법정부담금 6개 합계",
        "피복비": f"월 {p['uniform']:,}원 × {m}월 (1년 2착)",
        "작업화": f"월 {p['shoes']:,}원 × {m}월 (1년 2회)",
        "합계(원가)": "인건비 계 + 법정부담금 계 + 피복비 + 작업화",
        "일반관리비(9%)": "합계(원가) × 9%",
        "이윤(10%)": "(합계(원가) + 일반관리비) × 10%",
        "공급가액": "합계(원가) + 일반관리비 + 이윤",
        "부가가치세": "공급가액 × 10%",
        "1인 연간 총계": "공급가액 + 부가가치세",
        f"{headcount}인 연간 총계": f"1인 연간 총계 × {headcount}명",
        TOTAL: "N인 연간 총계, 천원 미만 절사",
    }


def basis(year: int, job: str | None = None) -> dict[str, str]:
    """적용 기준·근거 칸. 단가 파일의 출처와 원본 산출내역 비고, 지침 원문 인용만 쓴다."""
    items = load_rates(year)
    src = lambda k: f"{items[k]['name']} {items[k].get('source', '')}"
    market = f"시중노임단가: {src('market_daily')} · {cite('5-2-a')}"
    if job and job != STANDARD_JOB:
        market = "업체 입력값, 확인 필요(단순노무 외 직종은 시중노임단가 자료 없음)"
    return {
        "기본급": f"{market} · 최저임금: {src('min_wage')} · 근로기준법 제43조(주휴수당 포함)",
        "연장근로수당": "근로기준법 제56조(연장근로 가산 50%)",
        "휴일근로수당": "근로기준법 제56조(휴일근로 8시간 이내 50%, 초과 100% 가산)",
        "연차수당": "근로기준법 제60조",
        "상여금": "지방자치단체 원가계산에 의한 예정가격 작성준칙 제9조(400% 이하)",
        "퇴직충당금": "근로기준법 제34조",
        "인건비 계": cite("5-5-3"),
        "산재보험": f"{src('industrial')} · 고용노동부 고시(시설관리 및 사업지원 서비스업)",
        "국민연금": f"{src('pension')} · 국민연금법 제88조",
        "건강보험": f"{src('health')} · 국민건강보험법 제69·73조",
        "장기요양": f"{src('ltc')} · 노인장기요양보험법 제9조 · {cite('붙임4-요양')}",
        "고용보험": f"{src('employment_employer')} · 고용보험법 제6조",
        "임금채권보장": f"{src('wage_claim')} · 임금채권보장법 제3조",
        "피복비": "(사)한국건물위생관리협회(원본 산출내역 비고)",
        "작업화": "(사)한국건물위생관리협회(원본 산출내역 비고)",
        "일반관리비(9%)": f"지방계약법 시행규칙 제8조({judge()['overhead_cap']['value']:.0%} 이하)",
        "이윤(10%)": f"지방계약법 시행규칙 제8조({judge()['profit_cap']['value']:.0%} 이하) · {cite('붙임4-이윤')}",
        "부가가치세": "부가가치세법",
    }


def judge() -> dict:
    """판정 기준(가정): 1% 허용 범위, 일반관리비·이윤 상한, 요율 오차, 낮은 확신도 기준."""
    return json.loads(JUDGE.read_text(encoding="utf-8"))


def _old_rates(key: str, current: float) -> set[float]:
    """다른 연도·산출내역 기재값 중 현재 법정 요율과 다른 값(옛 요율 의심 판정용)."""
    keys = ("ltc", "cleaning_ltc") if key == "ltc" else (key,)
    out = {y["items"][k]["value"] for y in standards()["years"].values() for k in keys}
    if key == "pension":
        out |= {v for k, v in standards()["pension_schedule"].items() if k.isdigit()}
    return {v for v in out if abs(v - current) > 1e-9}


def office_inputs(inputs: dict | None, r: dict) -> dict:
    """공단 산정 입력: 업체 입력 구조(인원·시간)는 두고, 단순노무 일급은 시중노임단가 이상, 피복비·작업화는 표준 단가."""
    p = standard_inputs(**(inputs or {}))
    if p.get("job", STANDARD_JOB) == STANDARD_JOB:
        p["daily"] = max(p["daily"] or 0, r["market_daily"])
    p["uniform"], p["shoes"] = STANDARD_DEFAULTS["uniform"], STANDARD_DEFAULTS["shoes"]
    return p


def office_amounts(inputs: dict | None, r: dict) -> dict:
    """공단 산정 금액(계산 엔진, 장기요양 법정 요율)."""
    return calc_standard(office_inputs(inputs, r), standard_rates(r))


def check_standard(company: dict, office: dict, r: dict, inputs: dict | None = None, conf: dict | None = None,
                   unmapped: list | None = None, duplicates: dict | None = None, award_rate: float = DEFAULT_AWARD_RATE,
                   original: dict | None = None) -> dict:
    """항목별 상태와 사유. company=업체 금액(17개 항목), office=공단 산정, conf={항목: (확신도, 원문)}, duplicates={항목: 원문 행 수}.
    original=정정 전 업체 금액(일반관리비·이윤 상한은 업체 자신의 산출 구조로 판단해, 한 항목 정정이 다른 항목 오판으로 번지지 않게 한다)."""
    j = judge()
    tol, rate_tol, low_conf = j["tolerance"]["value"], j["rate_tolerance"]["value"], j["low_confidence"]["value"]
    p = standard_inputs(**(inputs or {}))
    legal = standard_rates(r)
    reasons: dict[str, list[tuple[str, str, bool]]] = {k: [] for k in BASE_ITEMS}  # (상태, 내용, 등록 차단)
    a = {k: company.get(k) for k in BASE_ITEMS}

    def add(k, s, text, block=False):
        reasons[k].append((s, text, block))

    for k in REQUIRED:
        if not a[k]:
            add(k, MISSING, "필수 항목이 없거나 0원입니다.")
    for k in BASE_ITEMS:
        v, f = a[k], office.get(k)
        if v and f:
            if v < f * (1 - tol):
                add(k, LOW, f"공단 산정 {f:,.0f}원보다 {1 - v / f:.1%} 적습니다({tol:.0%} 초과).")
            elif v > f * (1 + tol):
                add(k, OVER, f"공단 산정 {f:,.0f}원보다 {v / f - 1:.1%} 많습니다({tol:.0%} 초과).")
    for k, n in (duplicates or {}).items():
        if k in reasons and n > 1:
            add(k, OVER, f"같은 항목이 {n}번 들어갔습니다(중복 계상).")

    wage = sum(a[k] or 0 for k in WAGE_ITEMS)
    hours, months = p["monthly_hours"], p["months"]
    if a["기본급"]:
        daily = a["기본급"] / (hours * months) * 8
        hourly = daily / 8
        if p.get("job", STANDARD_JOB) != STANDARD_JOB:
            add("기본급", CHECK, f"{p['job']}: 시중노임단가(단순노무) 자료가 없어 일급 {daily:,.0f}원은 업체 입력값입니다. 확인 필요.")
        elif daily < r["market_daily"] - 0.5:
            add("기본급", LOW, f"시중노임단가({r['market_daily']:,}원) 미달, 보호지침 5-2: 기본급 환산 일급 {daily:,.0f}원.")
        if hourly < r["min_wage"]:
            add("기본급", LOW, f"최저임금 미달: 환산 시급 {hourly:,.0f}원 < 최저임금 {r['min_wage']:,}원(최저임금법).", True)
        elif hourly * award_rate < r["min_wage"]:
            add("기본급", LOW, f"낙찰률 {award_rate:.3%} 적용 시급 {hourly * award_rate:,.0f}원이 최저임금 {r['min_wage']:,}원 미만, 보호지침 5-2-c.")

    def insurance(k: str, base: float, rate: float, key: str) -> None:
        if not a[k] or not base:
            return
        expected = math.floor(base * rate)
        ratio = a[k] / base
        old = next((o for o in _old_rates(key, rate) if abs(ratio - o) / o < rate_tol), None)
        if old is not None:
            add(k, CHECK, f"옛 요율 사용 의심: 적용 요율 약 {pct(old)}, 현행 {pct(rate)}.")
        elif ratio > rate * (1 + rate_tol):
            add(k, OVER, f"요율이 고시 요율보다 높습니다: 약 {pct(ratio)} > {pct(rate)}.")
        elif a[k] < expected * (1 - 0.001):
            add(k, LOW, f"보험료가 요율 × 기준액({pct(rate)} × {base:,.0f}원 = {expected:,}원)보다 적습니다.")

    for k, key in INSURANCE.items():
        insurance(k, wage, legal[key], key)
    insurance("장기요양", a["건강보험"] or 0, legal["ltc"], "ltc")

    o = {k: (original or company).get(k) for k in BASE_ITEMS}
    full = complete({k: v or 0 for k, v in o.items()}, int(p["headcount"]))
    if a["일반관리비(9%)"] and full["합계(원가)"]:
        rate = a["일반관리비(9%)"] / full["합계(원가)"]
        if rate > j["overhead_cap"]["value"] * (1 + rate_tol):
            add("일반관리비(9%)", OVER, f"일반관리비율 {rate:.2%}가 상한 {j['overhead_cap']['value']:.0%}를 넘습니다.")
    if a["이윤(10%)"]:
        base = full["합계(원가)"] + (o["일반관리비(9%)"] or 0)
        rate = a["이윤(10%)"] / base if base else 0
        if rate > j["profit_cap"]["value"] * (1 + rate_tol):
            add("이윤(10%)", OVER, f"이윤율 {rate:.2%}가 상한 {j['profit_cap']['value']:.0%}를 넘습니다.")
    for k in ("피복비", "작업화"):
        if not a[k]:
            add(k, CHECK, "항목이 없습니다(필수 아님). 지급 여부를 확인하세요.")

    for k, (score, raw) in (conf or {}).items():
        if k in reasons and score < low_conf:
            add(k, CHECK, f"항목명 연결 확신 낮음: 원문 '{raw}' → '{k}' (확신도 {score:.2f}).")

    items = {}
    for k in BASE_ITEMS:
        found = reasons[k]
        status = min((s for s, _, _ in found), key=STATUS_ORDER.get, default=OK)
        items[k] = {"상태": status, "사유": [t for _, t, _ in found], "차단": any(b for _, _, b in found)}
    extra = [{"항목": f"미분류: {x['원문']}", "상태": CHECK, "사유": [f"공단 표준 항목에 연결되지 않았습니다({x['금액']:,.0f}원). 연결을 지정하세요."]}
             for x in (unmapped or [])]
    counts = {s: sum(v["상태"] == s for v in items.values()) for s in (MISSING, LOW, OVER, CHECK)}
    counts[CHECK] += len(extra)
    blocking = [t for v in items.values() if v["차단"] for t in v["사유"] if "최저임금 미달" in t]
    return {"items": items, "extra": extra, "counts": counts, "blocking": blocking}


REF = {"기본급": "기준②③⑧", "연장근로수당": "기준②⑧", "휴일근로수당": "기준②⑧", "연차수당": "기준②", "상여금": "기준②", "퇴직충당금": "기준①",
       "산재보험": "기준⑦", "국민연금": "기준④", "건강보험": "기준⑤", "장기요양": "기준⑥", "고용보험": "기준⑦", "임금채권보장": "기준⑦",
       "인건비 계": "기준⑫", "일반관리비(9%)": "기준⑨", "이윤(10%)": "기준⑨"}  # core/basis.py 패널 번호


def mark(status: str, correction: dict | None) -> str:
    """오류 정정 필요 칸: 누락·미달·과지급이면 ☑, 처리하면 '처리됨'."""
    if correction:
        return f"처리됨({correction['처리']})"
    return "☑ 정정 필요" if status in FLAGGED else ""


def rows(company: dict, office: dict, r: dict, year: int, inputs: dict | None = None, check: dict | None = None,
         corrections: dict | None = None) -> list[dict]:
    """표준 양식 행. company=업체 금액(없으면 공단 산정만), office=공단 산정 금액(계산 엔진 결과)."""
    p = standard_inputs(**(inputs or {}))
    n = int(p["headcount"])
    full_o = complete(office, n)
    full_c = complete({k: v or 0 for k, v in company.items()}, n) if company else {}
    f, b = formulas(standard_rates(r), office_inputs(p, r), n), basis(year, p.get("job"))
    corrections = corrections or {}
    out = []
    for group, item, sub in layout(n):
        o = full_o.get(item)
        c = (None if not sub and item in BASE_ITEMS and not company.get(item) else full_c.get(item)) if company else None
        state = (check or {}).get("items", {}).get(item, {"상태": OK, "사유": []}) if not sub else {"상태": "", "사유": []}
        out.append({"구분": group, "항목": item, "업체 금액": c, "공단 산정 금액": o, "차이": None if c is None or o is None else c - o,
                    "산식": f.get(item, ""), "산정기준·근거": (f"[{REF[item]}] " if item in REF else "") + b.get(item, ""), "상태": state["상태"], "사유": " / ".join(state["사유"]),
                    "오류 정정 필요": "" if sub else mark(state["상태"], corrections.get(item)), "소계": sub})
    for x in (check or {}).get("extra", []):
        out.append({"구분": "미분류", "항목": x["항목"], "업체 금액": None, "공단 산정 금액": None, "차이": None, "산식": "", "산정기준·근거": "",
                    "상태": x["상태"], "사유": " / ".join(x["사유"]), "오류 정정 필요": "", "소계": False})
    return out


def base_amounts(x: dict) -> dict:
    """계산 엔진 결과에서 업체 금액 형식(17개 항목)만 뽑는다."""
    return {k: x[k] for k in BASE_ITEMS}


# ───────────── 근로 유형(프리랜서·아르바이트)을 표준 양식으로 ─────────────
def _row(group, item, amount, formula, basis_text, status=OK, why="", sub=False) -> dict:
    return {"구분": group, "항목": item, "금액": amount, "산식": formula, "적용 기준·근거": basis_text, "상태": status if not sub else "", "사유": why, "소계": sub}


def freelancer_rows(x: dict) -> list[dict]:
    fee = x["지급액"]
    return [
        _row("지급", "지급액(사업소득)", fee, "계약 금액", "업체 입력값", why="일을 맡긴 대가로 주기로 한 금액입니다."),
        _row("원천징수", "소득세(3%)", x["소득세(3%)"], f"{fee:,.0f}원 × 3%, 10원 미만 절사", "소득세법 제129조(사업소득 원천징수 3%)",
             why=f"지급액의 3%인 {x['소득세(3%)']:,}원을 미리 떼어 대신 냅니다."),
        _row("원천징수", "지방소득세(0.3%)", x["지방소득세(0.3%)"], "소득세 × 10%, 10원 미만 절사", "지방세법(소득세의 10%)",
             why=f"소득세의 10%인 {x['지방소득세(0.3%)']:,}원입니다. 합쳐서 3.3%입니다."),
        _row("원천징수", "4대보험", 0, "-", "근로자가 아니므로 4대보험 없음", status=CHECK,
             why="산재보험은 노무제공자 특례 적용 여부 확인 필요."),
        _row("지급", "실지급액", x["실지급액"], "지급액 − 원천징수 계", "", sub=True),
    ]


def parttime_rows(x: dict, r: dict) -> list[dict]:
    h, wk, n = x["시급"], x["주 소정시간"], x["주 수"]
    status = LOW if h < r["min_wage"] else OK
    out = [
        _row(LABOR, "기본급", x["기본급"], f"시급 {h:,.0f}원 × 주 {wk:g}시간 × {n}주", f"최저임금 {r['min_wage']:,}원(최저임금법)", status,
             f"일한 시간만큼 받는 기본 임금입니다." + (f" 최저임금 {r['min_wage']:,}원보다 낮습니다." if status == LOW else "")),
        _row(LABOR, "주휴수당", x["주휴수당"], f"주 {wk:g}시간 ÷ 40 × 8 × 시급 × {n}주" if x["주15시간 이상"] else "주 15시간 미만: 제외",
             "근로기준법 제55조·제18조 제3항", why=(f"주 15시간 이상이라 한 주에 {x['주휴시간(주)']:g}시간분을 더 받습니다." if x["주15시간 이상"] else "주 15시간 미만이라 주휴수당이 없습니다.")),
        _row(LABOR, "퇴직충당금", x["퇴직충당금"], "지급 계 ÷ 12 (1년 이상·주 15시간 이상)", "근로자퇴직급여 보장법 제4조",
             why="1년 이상, 주 15시간 이상 일해야 퇴직금이 생깁니다." if not x["퇴직충당금"] else "1년치 임금의 1/12을 모아 둡니다."),
        _row(LABOR, "지급 계", x["지급 계"], "기본급 + 주휴수당", "", sub=True),
    ]
    note = "월 소정근로 60시간 미만: 제외(예외 확인 필요, 가정)" if x["월60시간 미만"] else "월 60시간 이상: 적용"
    for k, key in (("산재보험", "industrial"), ("국민연금", "pension"), ("건강보험", "health"), ("장기요양", "ltc"), ("고용보험", "employment_employer")):
        v = x["사업주 보험"][k]
        formula = "건강보험료 × " + pct(r["ltc"]) if k == "장기요양" else f"지급 계 × {pct(r[key])}"
        flag = any(f["상태"] == CHECK for f in x["flags"]) and k in ("국민연금", "고용보험")
        out.append(_row(LEGAL, k, v, formula if v or k == "산재보험" else "-", "산재는 항상 적용" if k == "산재보험" else note, CHECK if flag else OK,
                        why="회사가 내는 보험료입니다." if v else "적용 제외(월 60시간 미만)."))
    out.append(_row(LEGAL, "법정부담금 계", x["보험 계"], "합계", "", sub=True))
    return out
