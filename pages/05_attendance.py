import pandas as pd
import streamlit as st

from core import auth, audit, explain, standard as sd, ui, virtual
from core.anomaly import FORMULA, attendance_summary, clean, enrich, payslip_check
from core.calc import calc_freelancer, calc_parttime, calc_payroll, calc_standard, payroll_total, standard_rates
from core.data import active_year, rate_values
from core.guide import cite

user = ui.guard(auth.ADMIN)
ui.page("유형별 산출 · 근태", "근로 유형을 고르면 공단 표준 양식으로 산출하고, 항목마다 이 금액이 나온 이유를 보여 줍니다.")
year = active_year()
r = rate_values(year)
kind = st.segmented_control("근로 유형", ["기간제", "용역", "프리랜서", "아르바이트"], default="용역", key="type_kind") or "용역"

if kind == "용역":
    st.caption(f"청소용역 1인 기준 공단 표준 산출({year}년 적용 단가, 장기요양 법정 요율).")
    x = calc_standard({}, standard_rates(r))
    office = sd.office_amounts({}, r)
    check = sd.check_standard(sd.base_amounts(office), office, r)
    ui.basis_panel(year, expanded=False)
    ui.standard_table(sd.rows({}, office, r, year, {}, check), show_reason=False)
    with st.expander("이 금액이 나온 이유"):
        for item in sd.BASE_ITEMS:
            st.markdown(f"**{item}** · {explain.why(item, x, {}, r)}")
elif kind == "기간제":
    rows = calc_payroll(r)
    st.caption(f"기간제 9명, {year}년 적용 단가로 재산출(원본 2026년 9월 급여대장 구조). 이름은 행 순서로 만든 익명입니다.")
    m = st.columns(3)
    m[0].metric("지급 계", ui.won(payroll_total(rows)))
    m[1].metric("공제 계", ui.won(payroll_total(rows, "공제계")))
    m[2].metric("실수령 계", ui.won(payroll_total(rows, "실수령액")))
    st.dataframe(pd.DataFrame(rows).style.format({k: "{:,.0f}" for k in rows[0] if k != "성명"}), hide_index=True, width="stretch")
    st.caption("기본급 = 시급 × 8 × (근무일 + 유급일), 주휴수당 = 시급 × 8 × 주휴일수, 연장·휴일 = 통상시급 × 1.5(8시간 초과 휴일 2.0). "
               + explain.GLOSSARY["통상임금"])
elif kind == "프리랜서":
    fee = st.number_input("지급액(원)", 0, 100_000_000, 1_000_000, 10_000, key="type_fee")
    x = calc_freelancer(fee)
    ui.log_on_change("type_free", "유형별 산출", f"프리랜서 지급 {fee:,}원 → 실지급 {x['실지급액']:,.0f}원")
    m = st.columns(3)
    m[0].metric("원천징수(3.3%)", ui.won(x["원천징수 계"]))
    m[1].metric("실지급액", ui.won(x["실지급액"]))
    m[2].metric("4대보험", "없음")
    ui.simple_table(sd.freelancer_rows(x))
    st.warning("**근로자성이 인정되면 근로자로 다시 산출해야 합니다.** 업무 지시·근무시간·장소가 정해져 있으면 이름과 관계없이 근로자로 봅니다.", icon=":material/warning:")
    st.info("산재보험 노무제공자 특례 적용 여부는 확인 필요입니다(직종별 적용 대상이 정해져 있음).", icon=":material/search:")
    st.caption(explain.GLOSSARY["원천징수 3.3%"])
else:
    a, b, c, d = st.columns(4)
    hourly = a.number_input("시급(원)", 5_000, 50_000, int(r["min_wage"]), 10, key="type_hourly")
    weekly = b.number_input("주 소정근로시간", 1.0, 40.0, 15.0, 0.5, key="type_weekly")
    weeks = c.number_input("근무 주 수", 1, 104, 4, key="type_weeks")
    cont = d.number_input("계속 근로 개월 수", 1, 36, 1, key="type_cont")
    x = calc_parttime(hourly, weekly, weeks, r, cont)
    ui.log_on_change("type_part", "유형별 산출", f"아르바이트 시급 {hourly:,}원·주 {weekly:g}시간·{weeks}주 → 지급 {x['지급 계']:,.0f}원")
    for f in x["flags"]:
        {"미달": st.error, "확인 필요": st.warning}.get(f["상태"], st.info)(f["내용"])
    m = st.columns(3)
    m[0].metric("지급 계", ui.won(x["지급 계"]), f"월 평균 {x['월평균 지급']:,.0f}원", delta_color="off", delta_arrow="off")
    m[1].metric("월 소정근로시간", f"{x['월 소정시간']:.1f}시간", "60시간 미만" if x["월60시간 미만"] else "60시간 이상", delta_color="off", delta_arrow="off")
    m[2].metric("사업주 보험 계", ui.won(x["보험 계"]))
    ui.simple_table(sd.parttime_rows(x, r))
    st.caption(explain.GLOSSARY["주휴수당"] + " 4대보험 예외 판단(3개월 이상 계속 근로 등)은 가정입니다.")

st.divider()
st.subheader("근태 기반 수당 계산")
ui.virtual_tag("시연용 가상 데이터 (실제 직원 아님)")
a, b, _ = st.columns([1, 1.2, 3])
seed = a.number_input("생성 시드", 1, 9999, 2026, key="seed")
b.write("")
if b.button("가상 근태 생성", key="gen_att", width="stretch"):
    virtual.ensure(int(seed), force=True)
    st.cache_data.clear()
    audit.log("근태 생성", f"가상 근태 재생성(시드 {int(seed)})")
    st.rerun()

e = enrich()
c_ = clean(e)
s = attendance_summary(e)
m = st.columns(5)
m[0].metric("직원", f"{e['직원'].nunique()}명")
m[1].metric("근태 기록", f"{len(e):,}건", "2026.7~9월", delta_color="off", delta_arrow="off")
m[2].metric("지각·조퇴", f"{s['지각'].sum() + s['조퇴'].sum()}건")
m[3].metric("결근", f"{s['결근'].sum()}건")
m[4].metric("3개월 수당 합계", ui.won(c_["수당"].sum()))

st.info("**계산식** " + FORMULA, icon=":material/calculate:")
t1, t2, t3 = st.tabs(["개인별 집계", "수당 계산 내역", "분기 임금명세서 확인"])
with t1:
    st.dataframe(s.sort_values("초과근무(시간)", ascending=False).style.format({"수당 합계": "{:,.0f}원", "초과근무(시간)": "{:.1f}", "야간(시간)": "{:.1f}", "휴일(시간)": "{:.1f}"}), hide_index=True, width="stretch", height=430)
with t2:
    who = st.selectbox("직원", sorted(e["직원"].unique()), index=6, key="who")
    d = c_[(c_["직원"] == who) & (c_["수당"] > 0)].sort_values("날짜", ascending=False)
    view = d.assign(출근=d["출근"].dt.strftime("%H:%M"), 퇴근=d["퇴근"].dt.strftime("%H:%M"), 연장=(d["연장분"] / 60).round(2), 야간=(d["야간분"] / 60).round(2), 휴일=(d["휴일분"] / 60).round(2))
    st.dataframe(view[["날짜", "출근", "퇴근", "시급", "연장", "야간", "휴일", "연장수당", "야간가산", "휴일수당", "수당"]].style.format({k: "{:,.0f}" for k in ("시급", "연장수당", "야간가산", "휴일수당", "수당")} | {k: "{:.2f}" for k in ("연장", "야간", "휴일")}), hide_index=True, width="stretch", height=380)
with t3:
    p = payslip_check(e)
    st.metric("명세서 미달", f"{(p['확인 결과'] == '미달').sum()}명", f"전체 {len(p)}명 중", delta_color="off", delta_arrow="off")
    st.dataframe(p.style.apply(lambda r_: [ui.RED if r_["확인 결과"] == "미달" else ""] * len(r_), axis=1).format({k: "{:,.0f}원" for k in ("산정액", "제출액", "차액")}), hide_index=True, width="stretch", height=380)
    st.caption("근거: " + cite("6-2-2"))
