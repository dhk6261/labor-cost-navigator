"""인건비 내비게이터: 기업 착수계 등록 + 관리자 금액 산출 계산기(AI 문서 인식) + 사람 검수 후 착수계 생성. 실행: streamlit run app.py"""
import streamlit as st

from core import audit, auth, basis, rates, startup, ui, virtual, workflow
from core.data import DATA

st.set_page_config(page_title="인건비 산출·관리시스템", page_icon=str(DATA / "brand" / "icon.svg"), layout="wide", initial_sidebar_state="expanded")
virtual.ensure()
rates.sync_derived()
startup.ensure()
basis.versions()  # 기준 버전 이력이 없으면 v1을 만든다

user = auth.current_user(st.session_state)
audit.set_actor(user)

P = lambda path, title, icon, **kw: st.Page(path, title=title, icon=f":material/{icon}:", **kw)
if not user:
    nav = st.navigation([st.Page(ui.login_page, title="로그인", icon=":material/login:", default=True)])
elif user["role"] == auth.COMPANY:
    nav = st.navigation({"착수계": [P("pages/04_startup.py", "착수계 등록·관리", "assignment", default=True)]})
else:
    nav = st.navigation({
        "현황": [P("pages/01_dashboard.py", "대시보드", "dashboard", default=True)],
        "착수계·산출": [P("pages/04_startup.py", "착수계 등록·관리", "assignment"), P("pages/06_calculator.py", "금액 산출 계산기", "calculate")],
        "산출·검증": [
            P("pages/02_validate.py", "오류·근거 검증", "rule"),
            P("pages/10_repair.py", "엑셀 점검·수정본", "upload_file"),
            P("pages/05_attendance.py", "유형별 산출·근태", "schedule"),
            P("pages/03_rates.py", "기준 관리·재산출", "published_with_changes"),
            P("pages/08_compliance.py", "보호지침 점검", "verified"),
        ],
        "업무 지원": [P("pages/07_docs.py", "문서 초안", "description"), P("pages/09_history.py", "이력 로그", "history")],
    })

goto = st.session_state.pop("goto", None)
if goto and user:
    st.switch_page(goto)


def on_logout() -> None:
    auth.logout(st.session_state)


def on_switch() -> None:
    target = st.session_state.get("switch_to")
    if target:
        auth.switch(st.session_state, target)


ui.sidebar_brand()
with st.sidebar:
    if user:
        ui.sidebar_user(user)
        accounts = [a["아이디"] for a in auth.demo_accounts() if a["아이디"] != user["id"]]
        a, b = st.columns([1.5, 1])
        a.selectbox("계정 전환", accounts, key="switch_to", label_visibility="collapsed")
        b.button("전환", on_click=on_switch, key="switch_btn", width="stretch")
        st.button("로그아웃", on_click=on_logout, key="logout", width="stretch", icon=":material/logout:")
    error = None
    if user and user["role"] == auth.ADMIN:
        changes, error = ui.safe_detect()
        if error:
            st.error("공표단가 값 오류. 기준 관리 화면을 확인하세요.", icon=":material/block:")
        elif changes:
            st.warning(f"새 단가 감지 {len(changes)}건 · 기준 관리에서 적용", icon=":material/notifications:")

    ui.sidebar_label("시연 지원")
    scenario = st.session_state.get("scenario_step")
    if st.button("시연 시나리오" if scenario is None else "시나리오 닫기", width="stretch", key="scenario_toggle", icon=":material/slideshow:"):
        if scenario is None:
            st.session_state["scenario_step"] = 0
        else:
            del st.session_state["scenario_step"]
        st.rerun()
    if scenario is not None:
        scn = st.radio("시나리오", list(workflow.SCENARIOS), format_func=lambda k: workflow.SCENARIOS[k]["title"], key="scenario",
                       disabled=scenario > 0, label_visibility="collapsed")
        steps = workflow.SCENARIOS[scn]["steps"]
        items = []
        for i, step in enumerate(steps):
            mark, style = ("완료", "color:#7FA6D9") if i < scenario else ("진행", "color:#fff;font-weight:700") if i == scenario else ("대기", "color:#9FB4D3")
            items.append(f"<div style='{style};font-size:.84rem;padding:2px 0'><span style='display:inline-block;width:34px;font-size:.7rem;"
                         f"opacity:.85'>{mark}</span>{i + 1}. {step['title']}</div>")
        st.markdown("".join(items), unsafe_allow_html=True)
        if scenario < len(steps):
            current = steps[scenario]
            st.caption(current["say"])
            why = workflow.blocked(scn) if scenario == 0 else None
            if why:
                st.warning(why)
            if st.button(f"다음: {current['title']}", type="primary", width="stretch", key="scenario_next", disabled=bool(why) or bool(error)):
                workflow.run(scn, scenario, st.session_state)
                st.cache_data.clear()
                st.session_state["scenario_step"] = scenario + 1
                st.session_state["goto"] = current["page"]  # 계정이 바뀌면 메뉴가 달라지므로 다시 그린 뒤 이동
                st.rerun()
        else:
            st.success("시연 시나리오를 마쳤습니다.")
    st.button("시연 초기화", on_click=ui.reset_demo, width="stretch", key="reset", icon=":material/restart_alt:",
              help="기준(버전 이력 포함), 생년월일, 등록물(B의 v1만), 계산기 회차, 정정·검수 기록, 추출 보조값, 로그인, 이력 로그를 처음 상태로 되돌립니다.")
    if user and user["role"] == auth.ADMIN:
        ui.watch_rates()

nav.run()
ui.footer()
