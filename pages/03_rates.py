import hashlib
import json

import pandas as pd
import streamlit as st

from core import auth, audit, basis, rates, review, standard as sd, ui, workflow
from core.calc import DEFAULT_AWARD_RATE, calc_standard, standard_rates
from core.data import active_year, load_rates, rate_values
from core.guide import cite
from core.workflow import TOTAL, fmt

user = ui.guard(auth.ADMIN)
ui.page("기준 관리 · 재산출", "급여 기준(최저임금·시중노임단가·보험요율·상한)을 화면에서 업데이트하면 버전으로 남기고, 영향받는 착수계·계산 결과를 다시 계산해 재검수를 요청합니다.")


def on_simulate():
    rates.simulate_publication()
    audit.log("단가 변경", "공표단가.json 갱신(2027 시연 값)")


def on_apply():
    workflow.apply_and_recalculate("기준 적용", user)
    workflow.log_alerts()
    workflow.log_shortfalls(user)
    st.cache_data.clear()


def edit_form() -> None:
    doc = rates.checked_published()
    sig = hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:10]
    with st.expander("공표단가 직접 편집", expanded=False):
        st.caption("저장하면 값을 검사한 뒤 `공표단가.json`에 저장하고 자동으로 재산출하며, 이력 로그에 남깁니다. 요율은 % 단위로 입력합니다.")
        with st.form(f"rate_form_{sig}"):
            widths = [2.1, 1.1, 1.05, 1.35, 2.7, .95]
            for col, title in zip(st.columns(widths), ("항목", "값", "상태", "고시일", "출처", "현재 표시")):
                col.markdown(f"**{title}**")
            inputs = {}
            for key in rates.REQUIRED:
                item = doc["items"][key]
                cols = st.columns(widths)
                cols[0].markdown(f"{item.get('name', rates.LABELS[key])}")
                shown = f"{item['value']:,}" if item["unit"] == "원" else f"{item['value'] * 100:.3f}".rstrip("0").rstrip(".")
                value = cols[1].text_input("값", shown, key=f"{sig}_{key}_v", label_visibility="collapsed")
                options = ["확정", "잠정", "가정", "원본"]
                status = cols[2].selectbox("상태", options, options.index(item.get("status", "가정")), key=f"{sig}_{key}_s", label_visibility="collapsed")
                announced = cols[3].text_input("고시일", item.get("announced", ""), key=f"{sig}_{key}_a", label_visibility="collapsed")
                source = cols[4].text_input("출처", item.get("source", ""), key=f"{sig}_{key}_o", label_visibility="collapsed")
                cols[5].caption(rates.status_label(item))
                inputs[key] = {"value": value, "status": status, "announced": announced, "source": source}
            submitted = st.form_submit_button("저장하고 재산출", type="primary")
        if submitted:
            edited = rates.edited_doc(doc, inputs)
            _, errors = rates.validate_doc(edited)
            if errors:
                st.error("저장하지 않았습니다.\n\n" + "\n".join(f"- {x}" for x in errors), icon=":material/block:")
            else:
                rates.save_published(edited)
                workflow.apply_and_recalculate("기준 편집", user)
                workflow.log_alerts()
                workflow.log_shortfalls(user)
                st.cache_data.clear()
                st.session_state["rate_saved"] = True
                st.rerun()


def show_award_warning(a: dict) -> None:
    if not a["최저임금 충족"]:
        st.error(f"**최저임금 미달 경고** · 낙찰하한율 {DEFAULT_AWARD_RATE:.3%} 적용 시급 {a['낙찰률 적용 시급']:,.0f}원이 최저임금 {a['최저임금']:,}원보다 낮습니다. "
                 f"일급이 {a['필요 최소 일급']:,}원 이상이어야 하며, 그 전에는 최저임금 이상을 지급하도록 계약에 반영해야 합니다.", icon=":material/error:")
        st.caption("근거: " + cite("5-2-c"))
    else:
        st.caption(f"낙찰하한율 적용 시급 {a['낙찰률 적용 시급']:,.0f}원, 최저임금 {a['최저임금']:,}원 이상 충족")


def show_impact(im: dict, label: str) -> None:
    """① 영향 분석: 영향받는 계약·인원·추가 금액."""
    st.markdown(f"#### ① 영향 분석{label}")
    a = im["award"]
    m = st.columns(4)
    m[0].metric("청소용역 연 증가", ui.won(im["clean_diff"]), f"{im['clean_rate']:+.2%}", delta_color="off", delta_arrow="off")
    m[1].metric("기간제 월 증가", ui.won(im["pay_diff"]), "9월 실적 기준", delta_color="off", delta_arrow="off")
    m[2].metric("추가 소요(연 환산)", ui.won(im["annual"]), "기간제 9월×12 단순 환산", delta_color="off", delta_arrow="off")
    m[3].metric("낙찰하한율 적용", ui.won(a["낙찰 예상금액"]), f"{DEFAULT_AWARD_RATE:.3%}", delta_color="off", delta_arrow="off")
    show_award_warning(a)
    l, r = st.columns([1.35, 1])
    l.dataframe(pd.DataFrame([{"계약": x["name"], "인원": x["headcount"], "사유": "노임단가·국민연금·장기요양", "조치": "계약금액 조정"} for x in im["contracts"]]), hide_index=True, width="stretch")
    if im["low"]:
        r.dataframe(pd.DataFrame([{"성명": e.name, "기존 시급": ui.won(e.hourly), "새 최저임금": ui.won(im["min_wage"]), "부족액": ui.won(im["min_wage"] - e.hourly)} for e in im["low"]]), hide_index=True, width="stretch", height=210)
    else:
        r.success("최저임금에 미달하는 기간제 인원이 없습니다.")


changes, error = ui.safe_detect()
if error:
    st.error(error, icon=":material/block:")
    st.info("잘못된 값은 적용되지 않았고, 현재 적용 단가로 계속 계산합니다. `data/공표단가.json`을 고치면 자동으로 다시 검사합니다.")
    st.stop()

if changes:
    st.error(f"**새 단가 감지!** {len(changes)}개 항목이 공표값과 다릅니다.", icon=":material/notifications:")
    st.dataframe(pd.DataFrame([{"항목": x["항목"], "적용 중": fmt(x["적용 중"], x["unit"]), "새 공표": fmt(x["새 공표"], x["unit"]), "상태": x["표시"], "고시일": x["고시일"], "출처": x["출처"]} for x in changes])
                 .style.map(lambda s: ui.AMBER if str(s).startswith("가정") else "", subset=["상태"]), hide_index=True, width="stretch")
    if any(x["상태"] == "가정" for x in changes):
        st.warning("**가정값**이 포함되어 있습니다. 시중노임단가는 2026.11.30 공표 후 실제 값으로 갱신하세요.")
    show_impact(workflow.impact({k: v["value"] for k, v in rates.checked_published()["items"].items()}), " (적용 전 미리 보기)")
    st.button("적용 · 재산출", type="primary", on_click=on_apply, key="apply")
elif active_year() == 2026:
    st.success("현재 공표값과 적용값이 같습니다.")
    st.button("시연: 2027년 단가 공표 (공표단가.json 갱신)", type="primary", on_click=on_simulate, key="simulate")
if st.session_state.pop("rate_saved", False):
    st.success("단가를 저장하고 재산출했습니다. 이력 로그에 기록했습니다.")

if audit.get_state()["recalculated"] and active_year() == 2027 and not changes:
    values = rate_values(2027)
    im = workflow.impact(values)
    c0, c1, p0, p1 = im["c0"], im["c1"], im["p0"], im["p1"]
    show_impact(im, "")

    st.markdown("#### ② 재산출: 변경 전후 비교")
    summary = ["인건비 계", "복리후생비 계", "일반관리비(9%)", "이윤(10%)", "부가가치세", TOTAL]
    make_row = lambda k: {"항목": k, "변경 전": ui.won(c0[k]), "변경 후": ui.won(c1[k]), "증감": f"{c1[k] - c0[k]:+,.0f}원", "증감률": f"{c1[k] / c0[k] - 1:+.2%}"}
    st.dataframe(pd.DataFrame([make_row(k) for k in summary]), hide_index=True, width="stretch")
    with st.expander("청소용역 전체 항목과 기간제 9명 비교"):
        keys = ["기본급", "연장근로수당", "휴일근로수당", "연차수당", "상여금", "퇴직충당금", "인건비 계", "산재보험", "국민연금", "건강보험", "장기요양", "고용보험", "임금채권보장", "복리후생비 계", "합계(원가)", "일반관리비(9%)", "이윤(10%)", "부가가치세", "1인 연간 총계", TOTAL]
        bold = {"인건비 계", "복리후생비 계", "합계(원가)", "1인 연간 총계", TOTAL}
        st.dataframe(pd.DataFrame([make_row(k) for k in keys]).style.apply(lambda s: ["font-weight:700;background-color:#EEF3FA" if s["항목"] in bold else "" for _ in s], axis=1), hide_index=True, width="stretch", height=738)
        st.dataframe(pd.DataFrame([{"성명": x["성명"], "시급 전": ui.won(x["시급"]), "시급 후": ui.won(y["시급"]), "지급 전": ui.won(x["지급계"]), "지급 후": ui.won(y["지급계"]), "지급 증감": f"{y['지급계'] - x['지급계']:+,.0f}원", "실수령 전": ui.won(x["실수령액"]), "실수령 후": ui.won(y["실수령액"])} for x, y in zip(p0, p1)]), hide_index=True, width="stretch")
    st.caption("가정: 통상시급·보수월액은 시급 인상률만큼 변동, 소득세는 9월 값 유지, 국민연금 공란자는 공란 유지. 낙찰 계산은 예정가격=기준금액으로 가정.")

    st.markdown("#### ③ 오류 경고")
    found = workflow.alerts(values)
    level_style = {"오류": ui.RED, "위반": ui.RED, "주의": ui.AMBER}
    st.table(pd.DataFrame(found).style.map(lambda s: level_style.get(s, ""), subset=["수준"]).hide(axis="index"))
    short = workflow.approved_shortfalls(user)
    st.markdown("##### 승인된 착수계가 새 기준에 미달하는 건")
    if not short:
        st.success("승인된 착수계 가운데 새 기준에 미달하는 건이 없습니다." if workflow.approved(user) else "아직 승인된 착수계가 없습니다.")
    for item in short:
        c = item["case"]
        with st.container(border=True):
            st.markdown(f"**{c['contract']['name']}** · {c['company_name']} · 승인 {c['round']} ({c.get('approved_at', '')[:16]}) · 검수: **{ui.review_state(c, item['ev'])}**")
            st.dataframe(pd.DataFrame([{"항목": k, "상태": v["상태"], "사유": " / ".join(v["사유"])} for k, v in item["items"].items()])
                         .style.map(lambda s: ui.STATUS_STYLE.get(s, ""), subset=["상태"]), hide_index=True, width="stretch")
            st.caption("재제출 요청 공문은 **착수계 등록·관리**에서 재검수를 마친 뒤 만들 수 있습니다(검수 전 생성 불가).")
    st.caption("근거: " + cite("5-2-b"))

    st.markdown("#### ④ 공문 생성")
    if st.button("계약 변경 공문 만들기", type="primary", key="make_doc"):
        st.session_state["doc_kind"] = "계약 변경 공문"
        st.session_state["doc_ready"] = "계약 변경 공문"
        audit.log("문서 생성", "계약 변경 공문 초안 생성")
        st.switch_page("pages/07_docs.py")

year = active_year()
with st.expander(f"현재 적용 기준값 ({year}년)", expanded=not changes and year == 2026):
    current = load_rates(year)
    st.dataframe(pd.DataFrame([{"항목": v["name"], "값": fmt(v["value"], v["unit"]), "상태": rates.status_label(v), "고시일": v.get("announced", ""), "출처": v.get("source", "")} for v in current.values()])
                 .style.map(lambda s: ui.AMBER if str(s).startswith("가정") else "", subset=["상태"]), hide_index=True, width="stretch")
edit_form()

st.divider()
st.subheader("기준 버전")
vs = basis.versions()
cur = vs[-1]
st.markdown(f"현재 적용: **{basis.label()}** · {cur['note']} · {cur['by']}")
st.dataframe(pd.DataFrame([{"버전": f"v{v['version']}", "적용 연도": v["year"], "저장 시각": v["at"], "저장자": v["by"], "내용": v["note"],
                            "변경 내역": ", ".join(f"{c['항목']} {c['이전']}→{c['변경']}" for c in v["changes"]) or "-"} for v in reversed(vs)]),
             hide_index=True, width="stretch")
a_, b_ = st.columns([1, 3])
back = a_.selectbox("되돌릴 버전", [v["version"] for v in vs[:-1]] or [None], format_func=lambda n: "없음" if n is None else f"v{n}", key="w_back")
if b_.button("이 버전으로 되돌리기(새 버전으로 기록)", key="w_back_btn", disabled=back is None):
    workflow.rollback(user, back)
    st.cache_data.clear()
    st.rerun()
with st.expander("일반관리비율·이윤율 상한(판정 기준, 가정)"):
    j = sd.judge()
    x_, y_ = st.columns(2)
    oh = x_.number_input("일반관리비율 상한(%)", 1.0, 30.0, j["overhead_cap"]["value"] * 100, 0.5, key="w_oh")
    pf = y_.number_input("이윤율 상한(%)", 1.0, 30.0, j["profit_cap"]["value"] * 100, 0.5, key="w_pf")
    if st.button("상한 저장(새 버전)", key="w_caps"):
        workflow.set_caps(user, oh / 100, pf / 100)
        st.rerun()
re = [c for c in workflow.all_cases(user) if c.get("recheck")]
if re:
    st.error(f"**기준 변경으로 재검수 필요 {len(re)}건** · " + ", ".join(f"{c['company_name']} {c['round']}({'착수계' if c['kind'] == 'startup' else '계산기'})" for c in re), icon=":material/autorenew:")
    st.page_link("pages/04_startup.py", label="착수계 등록·관리에서 재검수", icon=":material/arrow_forward:")
with st.expander("현재 공표단가.json 보기"):
    st.code(json.dumps({k: v["value"] for k, v in rates.checked_published()["items"].items()}, ensure_ascii=False, indent=1), language="json")

st.divider()
st.subheader("기준 변경 영향")
st.caption("선형회귀나 추세 예측은 쓰지 않습니다. 기준값만 바꿔 계산 엔진(core/calc.py)으로 다시 계산한 결과입니다.")
pt = pd.DataFrame(workflow.pension_table())
st.markdown("##### 국민연금 단계 인상(2026년 9.5% → 매년 0.5%p → 2033년 13%)")
st.dataframe(pt.style.format({"국민연금(합계)": "{:.1%}", "사용자 부담": "{:.2%}", "1인 사용자 부담(연)": "{:,.0f}원", "계약 기준금액(3인)": "{:,.0f}원", "2026 요율 대비": "{:+,.0f}원"})
             .map(lambda s: ui.AMBER if str(s).startswith("현행 유지") else "", subset=["다른 기준"]), hide_index=True, width="stretch")
st.caption(f"청소용역 표준 산출(3인) 기준. {year}년 이후 최저임금·시중노임단가·건강보험 등 다른 기준은 **현행 유지 가정**입니다.")

st.markdown("##### 기준값 직접 바꿔 보기 (세션에만 적용, 적용 단가 파일은 바꾸지 않음)")
cur = rate_values(year)
a, b, c, d = st.columns(4)
w_market = a.number_input("시중노임단가(일급, 원)", 50_000, 300_000, int(cur["market_daily"]), 100, key="w_market")
w_min = b.number_input("최저임금(시급, 원)", 5_000, 30_000, int(cur["min_wage"]), 10, key="w_min")
w_pension = c.number_input("국민연금 사용자 부담(%)", 0.0, 10.0, round(cur["pension"] * 100, 3), 0.25, format="%.3f", key="w_pension")
w_health = d.number_input("건강보험 사용자 부담(%)", 0.0, 10.0, round(cur["health"] * 100, 3), 0.005, format="%.3f", key="w_health")
trial = {**cur, "market_daily": w_market, "min_wage": w_min, "pension": w_pension / 100, "health": w_health / 100}
if trial != cur:
    ui.log_on_change("whatif", "기준 변경 영향", f"시중노임단가 {w_market:,}, 최저임금 {w_min:,}, 국민연금 {w_pension:.3f}%, 건강보험 {w_health:.3f}%")
wi = workflow.whatif(trial, user)
x0, x1 = wi["before"], wi["after"]
keys = ["기본급", "인건비 계", "국민연금", "건강보험", "법정부담금 계", "1인 연간 총계", TOTAL]
full0, full1 = sd.complete(x0, 3), sd.complete(x1, 3)
st.dataframe(pd.DataFrame([{"항목": k, "현재 기준": ui.won(full0[k]), "바꾼 기준": ui.won(full1[k]), "차이": f"{full1[k] - full0[k]:+,.0f}원"} for k in keys]), hide_index=True, width="stretch")
if wi["contracts"]:
    st.markdown("승인된 계약별 금액 변화")
    st.dataframe(pd.DataFrame(wi["contracts"]).style.format({"승인 금액": "{:,.0f}원", "새 기준 공단 산정": "{:,.0f}원", "차이액": "{:+,.0f}원"})
                 .map(lambda v: ui.RED if isinstance(v, int) and v > 0 else "", subset=["미달", "누락"]), hide_index=True, width="stretch")
else:
    st.caption("승인된 계약이 생기면 계약별 차이액을 함께 보여 줍니다.")
