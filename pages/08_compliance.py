import pandas as pd
import streamlit as st

from core import auth, audit, budget_cap, compliance, guide_qa, ui

user = ui.guard(auth.ADMIN)
ui.page("보호지침 점검", "계약이 공공부문 도급 노동자 보호지침을 지키는지 점검하고, 지침 내용을 원문 그대로 찾아 줍니다.")


def ask_guide(question: str) -> None:
    """질문 원문은 이력에 남기지 않고 찾은 조항만 기록한다."""
    result = guide_qa.answer(question)
    st.session_state["qa_result"] = result
    clauses = list(dict.fromkeys(x["조항"] for x in result["matches"]))
    audit.log("지침 질의응답", "조항 " + ", ".join(clauses) + " 조회" if clauses else "관련 조항 없음")


tab_rules, tab_qa = st.tabs(["보호지침 점검", "지침 질의응답"])

with tab_rules:
    ui.virtual_tag("계약기간·낙찰률·임금명세서는 시연용 가상 데이터")
    results = compliance.run_compliance()
    style = {compliance.VIOLATION: ui.RED, compliance.CHECK: ui.AMBER}
    all_rows = [x for r in results for x in r["rows"]]
    count = lambda s: sum(x["결과"] == s for x in all_rows)
    ui.log_on_change("compliance", "지침 점검", f"충족 {count(compliance.OK)}, 위반 {count(compliance.VIOLATION)}, 확인 필요 {count(compliance.CHECK)}, 해당 없음 {count(compliance.NONE)}")
    c = st.columns(4)
    c[0].metric("충족", count(compliance.OK))
    c[1].metric("위반", count(compliance.VIOLATION))
    c[2].metric("확인 필요", count(compliance.CHECK))
    c[3].metric("해당 없음", count(compliance.NONE))
    for result in results:
        contract = result["contract"]
        st.markdown(f"#### {contract['name']} · {contract['method']}")
        table = pd.DataFrame(result["rows"])[["조항", "점검 내용", "근거값", "결과", "조치", "지침 원문"]]
        st.table(table.style.map(lambda s: style.get(s, ""), subset=["결과"]).hide(axis="index"))
    st.page_link("pages/07_docs.py", label="위반·조치가 포함된 계약 변경 공문 만들기", icon=":material/arrow_forward:")

with tab_qa:
    st.caption("공공부문 도급 노동자 보호지침 원문에서 찾아 그대로 보여 줍니다. 외부 AI를 쓰지 않고, 질문 내용은 저장하지 않습니다.")
    cols = st.columns(3)
    for i, question in enumerate(guide_qa.EXAMPLES):
        cols[i % 3].button(question, key=f"qa_ex{i}", on_click=ask_guide, args=(question,), width="stretch")
    with st.form("qa_form", clear_on_submit=True):
        a, b = st.columns([6, 1])
        typed = a.text_input("지침 질문", placeholder="예: 하도급 승인 여부는 며칠 안에 결정해?", label_visibility="collapsed")
        if b.form_submit_button("찾기", width="stretch") and typed.strip():
            ask_guide(typed.strip())
    result = st.session_state.get("qa_result")
    if result and not result["found"]:
        st.warning("지침에서 관련 내용을 찾지 못했습니다. 조항 이름이나 핵심 단어로 다시 질문해 주세요.", icon=":material/search:")
    elif result:
        current = None
        for item in result["matches"]:
            if item["조항"] != current:
                current = item["조항"]
                st.markdown(f"#### {current}. {item['제목']}")
            st.info(item["원문"])
        st.caption("지침 원문을 그대로 표시했습니다. 실제 적용은 담당자가 계약 조건과 관련 법령을 함께 확인해 판단합니다.")

with st.expander("참고: 총인건비 한도"):
    ui.virtual_tag("기준액·인상률·산정 범위·실적은 시연용 가정값")
    try:
        cap = budget_cap.evaluate()
    except budget_cap.CapError as e:
        st.error(str(e), icon=":material/block:")
    else:
        m = st.columns(3)
        m[0].metric("2027 한도", ui.won(cap["한도"]), f"기준액 × (1+{cap['config']['rate']['value']:.1%}, 가정)", delta_color="off", delta_arrow="off")
        m[1].metric("2027 예상액(직영+기간제)", ui.won(cap["예상액"]))
        m[2].metric("사용률", f"{cap['사용률']:.1%}", cap["상태"], delta_color="off", delta_arrow="off")
        st.caption("참고 기능입니다. 인상률·산정 범위는 행정안전부 지방공기업 예산편성기준과 공단 기준으로 교체해야 합니다.")
