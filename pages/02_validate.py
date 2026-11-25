from datetime import date

import pandas as pd
import streamlit as st

from core import auth, audit, ui
from core.anomaly import duplicates, enrich, payslip_check
from core.data import load_births, load_contracts, open_book, save_births
from core.guide import cite
from core.validate import CHECK, ERROR, INFO, as_rows, cell_marks, payroll_values, pension_summary

STYLE = {ERROR: ui.RED, CHECK: ui.AMBER}
user = ui.guard(auth.ADMIN)
ui.page("오류·근거 검증", "실제 엑셀의 옛 단가·요율, 수식 오류, 공제 누락을 규칙으로 검사하고 근거(법령·지침 조항)와 함께 보여 줍니다.")
t1, t2 = st.tabs(["입력 오류 검증 (실제 엑셀)", "근태 중복·명세서 확인 (가상 근태)"])

with t1:
    def on_demo():
        audit.log("오류 검증", "시연용 오류 주입본 검사" if st.session_state.get("demo") else "원본 검사로 복귀")
    demo = st.toggle("시연용 오류 주입본으로 검사 (원본 불변, 메모리 사본)", key="demo", on_change=on_demo)
    metric_box = st.container()

    st.markdown("#### 국민연금 대상 판정")
    ui.virtual_tag("생년월일은 시연용 가상 데이터")
    info = load_contracts()
    saved = load_births()
    left, right = st.columns([1, 1.5])
    with left:
        base = pd.DataFrame([{"사원": k, "생년월일": v} for k, v in saved.items()])
        edited = st.data_editor(base, key="birth_editor", hide_index=True, width="stretch", disabled=["사원"], num_rows="fixed", column_config={
            "생년월일": st.column_config.DateColumn(format="YYYY-MM-DD", min_value=date(1930, 1, 1), max_value=info["demo_today"])})
        births = {row["사원"]: (None if pd.isna(row["생년월일"]) else pd.Timestamp(row["생년월일"]).date()) for _, row in edited.iterrows()}
        st.session_state["birth_edits"] = births
        if st.button("생년월일 저장", key="save_births", disabled=births == saved):
            save_births(births)
            st.cache_data.clear()
            audit.log("국민연금 판정", "가상 생년월일 저장")
            st.rerun()
        st.caption("값을 바꾸면 바로 판정이 갱신됩니다. 저장을 눌러야 파일에 기록됩니다.")
    summary = pension_summary(births, payroll_values(demo))
    ui.log_on_change("pension", "국민연금 판정", f"대상·공제 누락 {summary['누락']}건, 연령 제외 {summary['제외']}건, 생년월일 없음 {summary['미입력']}건")
    with right:
        status_style = {"대상·공제 누락": ui.RED, "생년월일 없음": ui.AMBER}
        table = pd.DataFrame([{**x, "나이": "-" if x["나이"] is None else f"만 {x['나이']}세", "9월 공제액": f"{x['9월 공제액']:,.0f}원" if x["9월 공제액"] else "공란"} for x in summary["rows"]])
        st.dataframe(table.style.map(lambda s: status_style.get(s, ""), subset=["판정"]), hide_index=True, width="stretch")
        st.caption(f"기준일 {info['demo_today']}, 만 18세 이상 60세 미만이면 사업장가입 대상입니다.")

    fs = ui.findings(demo)
    with metric_box:
        c = st.columns(4)
        c[0].metric("오류", sum(x.severity == ERROR for x in fs))
        c[1].metric("확인 필요", sum(x.severity == CHECK for x in fs))
        c[2].metric("참고", sum(x.severity == INFO for x in fs))
        c[3].metric("국민연금 판정", f"누락 {summary['누락']} · 제외 {summary['제외']}", "가상 생년월일 기준", delta_color="off", delta_arrow="off")
    if demo:
        st.warning("주입된 오류 3건: 사원4 실수령액 수식 삭제(AD9), 사원5 지방소득세 미차감(U10), 사원8 고용보험 공란(Y13)", icon=":material/science:")
    else:
        st.info("원본의 실수령액 수식은 9명 모두 정상입니다. 실제 수식 오류는 청소용역 경비 소계(D31)입니다. 산재보험 공란은 사업주 전액 부담이라 오류가 아닙니다.")

    st.markdown("#### 기간제 급여대장")
    v = payroll_values(demo)
    cols = {"H": "시급", "J": "지급계", "Q": "명절휴가비", "U": "공제계", "V": "건강", "W": "장기요양", "X": "국민연금", "Y": "고용", "AA": "소득세", "AB": "지방세", "AD": "실수령액"}
    grid = pd.DataFrame([{"성명": f"사원{i + 1}", **{n: v[f"{k}{6 + i}"].value for k, n in cols.items()}} for i in range(9)])
    for n in cols.values():
        grid[n] = grid[n].map(lambda x: "공란" if pd.isna(x) else f"{x:,.0f}")
    marks = cell_marks(fs, "기간제 급여")
    def style_pay(_):
        out = pd.DataFrame("", index=grid.index, columns=grid.columns)
        for i in range(9):
            for k, n in cols.items():
                mark = marks.get(f"{k}{6 + i}")
                out.loc[i, n] = (ui.RED if k == "X" and mark else STYLE.get(mark, "")) + ";text-align:right"
        return out
    st.dataframe(grid.style.apply(style_pay, axis=None), hide_index=True, width="stretch")
    st.caption("빨간색: 오류 · 노란색: 담당자 확인 필요. 국민연금 판정은 위 생년월일(가상) 기준입니다.")
    local_tax = [x for x in fs if x.category == "지방소득세 불일치"]
    if local_tax:
        st.warning(f"**지방소득세 확인 필요 {len(local_tax)}명** · 지방소득세 = 소득세 × 10%(10원 미만 버림) 규칙과 다릅니다. 대상: "
                   + ", ".join(f"{x.target}({x.cell})" for x in local_tax), icon=":material/receipt_long:")

    st.markdown("#### 청소용역 산출내역")
    _, cv = open_book("청소용역")
    cmarks = cell_marks(fs, "청소용역")
    rows = [{"셀": "J3·K3", "항목": "노임단가 표기", "금액": cv["K3"].value, "산출근거": str(cv["J3"].value).replace("\n", " "), "비고": ""}]
    ids = [("", "K3", "J3", "")]
    for r in (7, 14, 15, 17, 31):
        rows.append({"셀": f"행 {r}", "항목": str(cv[f"B{r}"].value or cv[f"C{r}"].value).strip(), "금액": cv[f"D{r}"].value, "산출근거": cv[f"F{r}"].value or "", "비고": str(cv[f"G{r}"].value or "").replace("\n", " ")})
        ids.append((f"B{r}", f"D{r}", f"F{r}", f"G{r}"))
    cg = pd.DataFrame(rows)
    def style_clean(_):
        out = pd.DataFrame("", index=cg.index, columns=cg.columns)
        for i, (b, d, f_, g) in enumerate(ids):
            for col, ref in (("항목", b), ("금액", d), ("산출근거", f_), ("비고", g)):
                out.loc[i, col] = STYLE.get(cmarks.get(ref), "")
        return out
    st.dataframe(cg.style.apply(style_clean, axis=None).format({"금액": "{:,.0f}"}), hide_index=True, width="stretch")

    st.markdown("#### 검출 내역: 왜 문제인가")
    pick = st.multiselect("심각도", [ERROR, CHECK, INFO], default=[ERROR, CHECK], key="sev")
    table = pd.DataFrame([{"심각도": x.severity, "위치": f"{x.source} {x.cell}", "대상": x.target, "왜 문제인가": f"{x.title}. {x.evidence}", "근거": x.basis, "조치": x.action} for x in fs if x.severity in pick])
    if len(table):
        st.table(table.style.map(lambda s: STYLE.get(s, ""), subset=["심각도"]).hide(axis="index"))
    st.download_button("검증 결과 CSV", pd.DataFrame(as_rows(fs)).to_csv(index=False).encode("utf-8-sig"), "검증결과.csv", "text/csv")

with t2:
    ui.virtual_tag()
    e = enrich()
    dup = duplicates(e)
    slips = payslip_check(e)
    c = st.columns(2)
    c[0].metric("중복 입력", f"{len(dup)}건", f"과지급 위험 {ui.won(dup['과지급 위험'].sum())}", delta_color="off", delta_arrow="off")
    c[1].metric("임금명세서 미달", f"{(slips['확인 결과'] == '미달').sum()}명", "분기 산정액 대비", delta_color="off", delta_arrow="off")
    st.markdown("#### 같은 날 같은 시간 중복 입력")
    st.dataframe(dup.assign(**{"왜 문제인가": "동일 출퇴근 기록이 2회 입력되어 이중 지급 위험", "과지급 위험": dup["과지급 위험"].map(ui.won), "출근": dup["출근"].dt.strftime("%H:%M"), "퇴근": dup["퇴근"].dt.strftime("%H:%M")}).style.map(lambda _: ui.RED, subset=["과지급 위험"]), hide_index=True, width="stretch")
    st.markdown("#### 분기 임금명세서 미달")
    st.dataframe(slips[slips["확인 결과"] == "미달"].style.format({k: "{:,.0f}원" for k in ("산정액", "제출액", "차액")}), hide_index=True, width="stretch")
    st.caption("근거: " + cite("6-2-2"))
