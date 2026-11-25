"""기준 적용·재산출·재검수 흐름, 기준 변경 영향, 시연 시나리오 세 개. 화면과 테스트가 함께 사용한다."""
from __future__ import annotations

import math

from . import audit, auth, basis, rates, review, standard, startup, startup_docs
from .calc import DEFAULT_AWARD_RATE, apply_award, calc_cleaning, calc_payroll, calc_standard, payroll_total, standard_rates
from .case import evaluate, save
from .compliance import violations
from .data import DATA, active_year, load_contracts, load_employees, pension_rate, rate_values, standards

TOTAL = "계약 기준금액(천원 미만 절사)"


def fmt(value, unit: str) -> str:
    return f"{value * 100:.3f}".rstrip("0").rstrip(".") + "%" if unit == "%" else f"{value:,}원"


def award_check(r: dict) -> dict:
    """낙찰하한율 적용 시급과 최저임금을 맞춰 보는 데 필요한 최소 일급까지 계산한다."""
    c = calc_cleaning(r)
    award = apply_award(c[TOTAL], c["인건비 계"], r)
    award["필요 최소 일급"] = math.ceil(r["min_wage"] * 8 / DEFAULT_AWARD_RATE)
    return award


def impact(values: dict) -> dict:
    """적용 전후 영향: 계약, 인원, 추가 금액, 낙찰 경고."""
    r0 = rate_values(2026)
    c0, c1 = calc_cleaning(r0), calc_cleaning(values)
    p0, p1 = calc_payroll(r0), calc_payroll(values)
    staff = load_employees()
    pay_diff = payroll_total(p1) - payroll_total(p0)
    return {
        "contracts": load_contracts()["contracts"], "low": [e for e in staff if e.hourly < values["min_wage"]], "min_wage": values["min_wage"],
        "c0": c0, "c1": c1, "p0": p0, "p1": p1, "clean_diff": c1[TOTAL] - c0[TOTAL], "clean_rate": c1[TOTAL] / c0[TOTAL] - 1,
        "pay_diff": pay_diff, "annual": c1[TOTAL] - c0[TOTAL] + pay_diff * 12, "award": award_check(values),
    }


def alerts(values: dict) -> list[dict]:
    """재산출 직후 보여 줄 오류 경고: 최저임금, 옛 요율, 지침 5-2."""
    r0 = rate_values(2026)
    out = []
    low = [e for e in load_employees() if e.hourly < values["min_wage"]]
    if low:
        out.append({"수준": "오류", "항목": "최저임금 미달", "내용": f"기간제 {len(low)}명의 시급 {min(e.hourly for e in low):,}원이 {values['min_wage']:,}원보다 낮습니다.", "조치": "시급 인상"})
    if values["pension"] != r0["pension"]:
        out.append({"수준": "오류", "항목": "국민연금 옛 요율", "내용": f"청소용역 산출내역이 {r0['pension']:.2%}이며 적용값은 {values['pension']:.2%}입니다.", "조치": "산출내역 요율 수정"})
    if values["cleaning_ltc"] != r0["cleaning_ltc"]:
        out.append({"수준": "오류", "항목": "장기요양 옛 요율", "내용": f"청소용역 산출내역이 {r0['cleaning_ltc']:.2%}이며 적용값은 {values['cleaning_ltc']:.2%}입니다.", "조치": "산출내역 요율 수정"})
    for x in violations():
        if x["조항"] == "5-2":
            out.append({"수준": "위반", "항목": "지침 5-2 위반", "내용": x["근거값"], "조치": x["조치"]})
    return out


def log_alerts(values: dict | None = None) -> None:
    found = alerts(values or rate_values(2027))
    audit.log("오류 경고", "; ".join(f"{x['항목']}" for x in found) or "경고 없음")


# ───────────── 기준 변경 → 재산출·재검수(7절) ─────────────
def all_cases(user: dict | None = None) -> list[dict]:
    """영향 점검 대상: 임시저장이 아닌 착수계 + 업체별 최신 계산기 회차."""
    from . import calculator
    admin = user or {"role": auth.ADMIN, "name": "시스템", "company": "*"}
    return [c for c in startup.all_cases() if c["status"] != startup.DRAFT] + calculator.latest(admin)


def recheck_all(user=None) -> list[dict]:
    """새 기준으로 다시 계산해 공단 산정 금액이 바뀐 건에 '기준 변경으로 재검수 필요'를 단다(검수는 서명 불일치로 자동 해제)."""
    changed = []
    for c in all_cases():
        ev = evaluate(c)
        if abs(ev["office_total"] - (c.get("office_total") or 0)) > 0.5:
            c["recheck"] = True
            c["office_total_before"] = c.get("office_total")
            c["office_total"] = ev["office_total"]
            save(c)
            changed.append(c)
    if changed:
        audit.log("재산출", f"기준 변경으로 재검수 필요 {len(changed)}건: " + ", ".join(f"{c['company_name']} {c['round']}" for c in changed), user=user)
    return changed


def apply_and_recalculate(kind: str = "단가 적용", user=None) -> None:
    changed = rates.detect_changes()
    rates.apply_published()
    audit.set_state(recalculated=True)
    r0, r1 = rate_values(2026), rate_values(2027)
    c0, c1 = calc_cleaning(r0)[TOTAL], calc_cleaning(r1)[TOTAL]
    p0, p1 = payroll_total(calc_payroll(r0)), payroll_total(calc_payroll(r1))
    detail = ", ".join(f"{x['항목']} {fmt(x['적용 중'], x['unit'])}→{fmt(x['새 공표'], x['unit'])}({x['표시']})" for x in changed)
    audit.log(kind, detail or "값 변경 없음(상태·출처·고시일 수정)", user=user)
    audit.log("재산출", f"청소용역 {c0:,}→{c1:,}원({c1 - c0:+,}), 기간제 월 {p0:,.0f}→{p1:,.0f}원({p1 - p0:+,.0f})", user=user)
    basis.save_version(kind, user)
    recheck_all(user)


def rollback(user: dict, n: int) -> dict:
    doc = basis.rollback(user, n)
    audit.set_state(recalculated=doc["year"] == 2027)
    recheck_all(user)
    return doc


def set_caps(user: dict, overhead: float, profit: float) -> dict:
    doc = basis.set_caps(user, overhead, profit)
    recheck_all(user)
    return doc


def pension_table(values: dict | None = None) -> list[dict]:
    """국민연금 단계 인상(2026~2033)이 사용자 부담분과 계약 기준금액에 주는 영향. 그 밖의 기준은 현행 유지 가정."""
    base = values or rate_values(active_year())
    schedule = sorted(int(k) for k in standards()["pension_schedule"] if k.isdigit())
    out, first = [], None
    for year in schedule:
        x = calc_standard({}, standard_rates({**base, "pension": pension_rate(year)}))
        first = first or x
        out.append({"연도": year, "국민연금(합계)": pension_rate(year) * 2, "사용자 부담": pension_rate(year), "1인 사용자 부담(연)": x["국민연금"],
                    "계약 기준금액(3인)": x[TOTAL], "2026 요율 대비": x[TOTAL] - first[TOTAL],
                    "다른 기준": "현행 유지(가정)" if year > active_year() else "적용값"})
    return out


def approved(user: dict) -> list[dict]:
    """기업별 최신 승인 착수계."""
    best: dict[str, dict] = {}
    for c in startup.list_for(user):
        if c["status"] == startup.APPROVED and (c["company"] not in best or c["version"] > best[c["company"]]["version"]):
            best[c["company"]] = c
    return list(best.values())


def approved_shortfalls(user: dict, values: dict | None = None) -> list[dict]:
    """승인된 착수계 산출내역(등록 시점 금액)이 현재 기준 공단 산정에 미달·누락하는 건."""
    out = []
    for c in approved(user):
        ev = evaluate(c, r=values)
        bad = {k: v for g in ev["groups"] for k, v in g["check"]["items"].items() if v["상태"] in (standard.LOW, standard.MISSING)}
        if bad:
            out.append({"case": c, "items": bad, "ev": ev})
    return out


def log_shortfalls(user: dict) -> list[dict]:
    found = approved_shortfalls(user)
    text = (f"새 기준 미달 {len(found)}건: " + ", ".join(f"{x['case']['company_name']} {x['case']['round']}" for x in found)) if found else "새 기준 미달 없음"
    audit.log("승인 계약 점검", text, user=user)
    return found


def whatif(values: dict, user: dict) -> dict:
    """세션 입력 기준으로 공단 표준 산출과 승인된 착수계의 금액 변화를 다시 계산한다(파일은 바꾸지 않음)."""
    cur = rate_values(active_year())
    rows = []
    for c in approved(user):
        now, new = evaluate(c), evaluate(c, r=values)
        rows.append({"계약": c["contract"]["name"], "기업": c["company_name"], "승인 버전": c["round"], "승인 금액": now["company_total"],
                     "새 기준 공단 산정": new["office_total"], "차이액": new["office_total"] - now["company_total"],
                     "미달": new["counts"]["미달"], "누락": new["counts"]["누락"]})
    return {"before": calc_standard({}, standard_rates(cur)), "after": calc_standard({}, standard_rates(values)), "contracts": rows}


# ───────────── 시연 시나리오 ─────────────
DEMO_LOW_DAILY = 90085   # 시나리오 1에서 기업이 처음 넣는 옛 일급(2024년 6월 노임단가)
STARTUP = "pages/04_startup.py"
CALC = "pages/06_calculator.py"
C_NAME, C_CONTRACT, C_FILE = "가상기업C(청소)", "가상 시설 청소용역(관리자 단독 시연)", "가상업체C_산출내역.pdf"
STEPS1 = [
    {"title": "가상기업A 로그인", "page": STARTUP, "say": "용역 기업이 자기 계정으로 로그인합니다. 다른 기업 자료는 보이지 않습니다.", "account": "company_a"},
    {"title": "새 착수계 등록", "page": STARTUP, "say": f"채용정보 등록처럼 단계별로 입력합니다. 일급 {DEMO_LOW_DAILY:,}원을 넣으면 시중노임단가 미달 경고가 바로 뜹니다.", "account": "company_a"},
    {"title": "고쳐서 등록", "page": STARTUP, "say": "일급을 시중노임단가로 고치면 경고가 사라지고 등록됩니다.", "account": "company_a"},
    {"title": "관리자 로그인", "page": STARTUP, "say": "공단 관리자 계정으로 바꿉니다.", "account": "admin"},
    {"title": "등록 목록 확인", "page": STARTUP, "say": "가상기업A·B의 착수계가 등록됨 상태로 들어와 있습니다.", "account": "admin"},
    {"title": "B를 계산기로", "page": CALC, "say": "B의 첨부 엑셀을 AI 문서 인식으로 읽어 공단 산정과 비교합니다. 누락·미달·과지급이 색으로, 정정 필요가 ☑로 표시됩니다.", "account": "admin"},
    {"title": "B 보완 요청 · A 검수", "page": STARTUP, "say": "B는 사유를 적어 보완 요청하고, A는 체크리스트로 검수를 마칩니다.", "account": "admin"},
    {"title": "A 착수계 생성 · 승인", "page": STARTUP, "say": "검수가 끝난 A만 착수계 4종을 만들 수 있고, 승인하면 버전이 잠깁니다.", "account": "admin"},
    {"title": "이력 로그", "page": "pages/09_history.py", "say": "기업·관리자의 등록·추출·정정·검수·승인·문서 생성이 모두 남았습니다.", "account": "admin"},
]
STEPS2 = [
    {"title": "관리자 로그인", "page": CALC, "say": "관리자 계정 하나만으로 처음부터 끝까지 작업합니다.", "account": "admin"},
    {"title": "업체 직접 추가", "page": CALC, "say": "계정이 없는 가상기업C를 기업명·계약명만으로 추가합니다.", "account": "admin"},
    {"title": "PDF 올리기", "page": CALC, "say": "C 업체의 산출내역 PDF를 올리면 앱 안의 AI 문서 인식 모듈이 읽습니다(파일은 밖으로 나가지 않음).", "account": "admin"},
    {"title": "추출 결과 확인", "page": CALC, "say": "값마다 원문 위치(쪽·줄)와 확신도를 확인합니다.", "account": "admin"},
    {"title": "산정기준 확인", "page": CALC, "say": "어떤 단가·요율·고시로 계산했는지 산정기준 패널에서 확인합니다.", "account": "admin"},
    {"title": "과지급 정정", "page": CALC, "say": "일반관리비 10%(상한 9% 초과) 과지급 1건을 정정합니다.", "account": "admin"},
    {"title": "검수 완료", "page": CALC, "say": "체크리스트 5개를 확인하고 검수를 마칩니다.", "account": "admin"},
    {"title": "산출내역서 생성", "page": CALC, "say": "검수가 끝나야 산출내역서를 내려받을 수 있습니다.", "account": "admin"},
]
STEPS3 = [
    {"title": "2027 기준 적용", "page": "pages/03_rates.py", "say": "기준 관리에서 2027년 기준을 적용하면 새 기준 버전이 남습니다.", "account": "admin"},
    {"title": "영향 건 재산출", "page": "pages/03_rates.py", "say": "등록된 착수계와 계산기 결과를 새 기준으로 다시 계산합니다.", "account": "admin"},
    {"title": "재검수 필요 배지", "page": STARTUP, "say": "금액이 바뀐 건에 '기준 변경으로 재검수 필요'가 붙고 검수가 풀립니다.", "account": "admin"},
    {"title": "재검수", "page": STARTUP, "say": "새 기준 미달 항목을 '정정 불필요(재제출 요청 예정)'로 처리하고 다시 검수합니다.", "account": "admin"},
    {"title": "재제출 요청 공문", "page": "pages/07_docs.py", "say": "재검수가 끝난 승인 착수계에 재제출 요청 공문을 만듭니다.", "account": "admin"},
]
STEPS = STEPS3  # 기준 변경 흐름(이전 시나리오 2 자리)
SCENARIOS = {"1": {"title": "시나리오 1 · 기업 등록 → 관리자 검수", "steps": STEPS1},
             "2": {"title": "시나리오 2 · 관리자 단독(계산기)", "steps": STEPS2},
             "3": {"title": "시나리오 3 · 기준 변경 → 재검수", "steps": STEPS3}}


def blocked(scn: str) -> str | None:
    """시나리오 시작 전 상태 확인. 문제가 있으면 안내 문구."""
    cases = startup.all_cases()
    if scn == "1":
        if active_year() != 2026:
            return "2027년 기준이 적용된 상태입니다. 시연 초기화 후 시작하세요."
        if any(c["company"] == "CO-A" for c in cases) or not any(c["company"] == "CO-B" and c["status"] == startup.REGISTERED for c in cases):
            return "이미 등록·승인이 진행된 상태입니다. 시연 초기화 후 시작하세요."
    elif scn == "2":
        if any(c["name"] == C_NAME for c in auth.companies()):
            return f"{C_NAME}가 이미 추가되어 있습니다. 시연 초기화 후 시작하세요."
    else:
        try:
            changes = rates.detect_changes()
        except rates.RateError:
            return "공표단가 값 오류. 기준 관리 화면을 확인하세요."
        if active_year() != 2026 or changes:
            return "이미 기준이 바뀐 상태입니다. 시연 초기화 후 시작하세요."
        if not any(c["company"] == "CO-A" and c["status"] == startup.APPROVED for c in cases):
            return "승인된 가상기업A 착수계가 필요합니다. 시나리오 1을 먼저 진행하세요."
    return None


def reason_example(case: dict) -> str:
    """보완 요청 사유 예시: 누락·미달·과지급 항목을 자동으로 요약한다."""
    ev = evaluate(case)
    items = [f"{row['항목']} {row['상태']}" for g in ev["groups"] for row in g["rows"] if row["상태"] in standard.FLAGGED]
    return "; ".join(dict.fromkeys(items)) + ". 보완 후 새 버전으로 다시 등록 바랍니다."


def _latest(user: dict, company: str, status: str | None = None) -> dict:
    rows = [c for c in startup.list_for(user) if c["company"] == company and (status is None or c["status"] == status)]
    return max(rows, key=lambda c: c["version"])


def _company_form(daily: int) -> dict:
    form = startup.default_form("CO-A")
    form["wage"]["daily"] = daily
    return form


def run(scn: str, index: int, session) -> None:
    """시나리오 한 단계를 실행한다. session은 st.session_state 또는 dict. 필요한 계정 전환을 자동으로 한다."""
    from . import calculator
    step = SCENARIOS[scn]["steps"][index]
    user = auth.switch(session, step["account"])
    if scn == "1":
        if index == 0:
            session.pop("reg_form", None)
        elif index == 1:
            form = _company_form(DEMO_LOW_DAILY)
            draft = startup.save_draft(user, "CO-A", form)
            session.update(reg_form=form, reg_id=draft["id"], reg_step=3, reg_open=True)
        elif index == 2:
            form = _company_form(rate_values(active_year())["market_daily"])
            draft = startup.save_draft(user, "CO-A", form, sid=session.get("reg_id") or _latest(user, "CO-A", startup.DRAFT)["id"])
            ev = evaluate(draft)
            startup.register(user, draft["id"], "시연: 확인 사유 기재" if any(ev["counts"].values()) else "")
            session.update(reg_open=False)
            session.pop("reg_form", None)
        elif index == 3:
            session.pop("st_sel", None)
        elif index == 4:
            subs = [c for c in startup.list_for(user) if c["status"] == startup.REGISTERED]
            audit.log("등록 확인", f"등록됨 {len(subs)}건: " + ", ".join(f"{c['company_name']} {c['round']}" for c in subs), user=user)
        elif index == 5:
            b = _latest(user, "CO-B", startup.REGISTERED)
            run_ = calculator.from_startup(user, b)
            session.update(calc_company="CO-B", calc_run=run_["n"], calc_step="④ 산출 결과")
        elif index == 6:
            b = _latest(user, "CO-B", startup.REGISTERED)
            startup.request_fix(user, b["id"], reason_example(b))
            a = _latest(user, "CO-A", startup.REGISTERED)
            review.complete(user, a, {c: True for c in review.CHECKLIST})
            session["st_sel"] = a["id"]
        elif index == 7:
            a = _latest(user, "CO-A", startup.REGISTERED)
            session["st_files"] = {**startup_docs.build_all(user, a), "id": a["id"]}
            startup.approve(user, a["id"])
            session["st_sel"] = a["id"]
        elif index != 8:
            raise IndexError(index)
    elif scn == "2":
        if index == 1:
            co = auth.add_company(user, C_NAME, C_CONTRACT, 2)
            session.update(calc_company=co["id"], calc_step="② 파일 올리기")
        elif index == 2:
            co = next(c for c in auth.companies() if c["name"] == C_NAME)
            path = DATA / "demo_vendors" / C_FILE
            run_ = calculator.upload(user, co["id"], path.read_bytes(), path.name)
            session.update(calc_company=co["id"], calc_run=run_["n"], calc_step="③ AI 추출 결과")
        elif index in (3, 4, 5, 6, 7):
            co = next(c for c in auth.companies() if c["name"] == C_NAME)
            case = calculator.runs(user, co["id"])[-1]
            ev = evaluate(case)
            if index == 3:
                review.confirm_fields(user, case, [f["key"] for f in ev["unconfirmed"]])
                session["calc_step"] = "③ AI 추출 결과"
            elif index == 4:
                audit.log("산정기준 확인", f"{basis.label()} 기준으로 산출", user=user, company=case["company_name"], round_=case["round"])
                session["calc_step"] = "④ 산출 결과"
            elif index == 5:
                for key in ev["pending"]:
                    gi, item = int(key.split(":")[0][1:]), key.split(":", 1)[1]
                    review.correct(user, case, key, "정정 완료", round(ev["groups"][gi]["office"][item]))
                session["calc_step"] = "④ 산출 결과"
            elif index == 6:
                review.complete(user, case, {c: True for c in review.CHECKLIST})
                session["calc_step"] = "⑥ 검수"
            else:
                session["calc_file"] = {"data": startup_docs.build_cost_sheet(user, case), "id": case["id"]}
                session["calc_step"] = "⑦ 산출물"
            session.update(calc_company=co["id"], calc_run=case["n"])
    else:
        if index == 0:
            rates.simulate_publication()
            audit.log("단가 변경", "공표단가.json 갱신(시연 시나리오: 2027 기준)", user=user)
            apply_and_recalculate("기준 적용", user)
            log_alerts()
        elif index == 1:
            changed = [c for c in all_cases() if c.get("recheck")]
            audit.log("영향 분석", f"재검수 필요 {len(changed)}건: " + ", ".join(f"{c['company_name']} {c['round']}" for c in changed), user=user)
            log_shortfalls(user)
        elif index == 2:
            a = _latest(user, "CO-A", startup.APPROVED)
            session["st_sel"] = a["id"]
        elif index == 3:
            a = _latest(user, "CO-A", startup.APPROVED)
            for key in evaluate(a)["pending"]:
                review.correct(user, a, key, "정정 불필요", reason="새 기준 미달: 재제출 요청 예정(승인 버전은 수정 불가)")
            review.complete(user, a, {c: True for c in review.CHECKLIST})
            session["st_sel"] = a["id"]
        elif index == 4:
            item = next(x for x in approved_shortfalls(user) if x["case"]["company"] == "CO-A")
            session["doc_kind"] = "재제출 요청 공문"
            session["doc_file"] = {"data": startup_docs.resubmit_doc(user, item["case"], item["items"], rate_values(active_year())), "id": item["case"]["id"]}
        else:
            raise IndexError(index)
