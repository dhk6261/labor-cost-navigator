import pandas as pd
import streamlit as st

from core import auth, compliance, review, startup, ui, workflow
from core.case import evaluate
from core.data import load_contracts, load_employees
from core.validate import ERROR

user = ui.guard(auth.ADMIN)
ui.page("대시보드", "착수계 등록부터 AI 추출, 산출·판정, 오류 정정, 관리자 검수, 산출물 생성까지 오늘 처리할 업무를 한눈에 봅니다.")
ui.flow([("착수계 등록", "기업이 단계별 양식으로 등록"), ("AI 추출", "업체 파일에서 값·위치 인식"), ("산출·판정", "공단 산정과 비교, 색 표시"),
         ("오류 정정", "☑ 항목 정정·사유 처리"), ("관리자 검수", "체크리스트 5개 확인"), ("산출물", "검수 후 착수계 4종 생성")])

cases = workflow.all_cases(user)
evs = [(c, evaluate(c)) for c in cases]
starts = [c for c in cases if c["kind"] == "startup"]
fs = ui.findings()
n_err = sum(x.severity == ERROR for x in fs)
changes, error = ui.safe_detect()
found = compliance.violations()
pending = sum(len(ev["pending"]) for c, ev in evs)
waiting = sum(review.state(c, ev) != review.DONE and c.get("status") != startup.FIX for c, ev in evs)
recheck = sum(bool(c.get("recheck")) and not review.is_valid(c, ev) for c, ev in evs)

ui.kpis([("등록 대기", sum(c["status"] == startup.REGISTERED for c in starts), "건", "기업이 등록한 착수계", "blue"),
         ("보완 요청", sum(c["status"] == startup.FIX for c in starts), "건", "기업 재등록 대기", "orange"),
         ("오류 정정 대기", pending, "건", "☑ 누락·미달·과지급", "red" if pending else "green"),
         ("검수 대기", waiting, "건", "체크리스트 미완료", "yellow" if waiting else "green"),
         ("기준 변경 재검수", recheck, "건", "금액이 바뀐 건", "red" if recheck else "green"),
         ("지침 위반", len(found), "건", ", ".join(x["조항"] for x in found) or "없음", "violet" if found else "green")])
if error:
    st.error("공표단가.json 값 오류. 기준 관리 화면을 확인하세요.", icon=":material/block:")
elif changes:
    st.warning(f"**새 단가 감지** · {len(changes)}개 항목이 공표값과 다릅니다. 기준 관리·재산출에서 적용하세요.", icon=":material/notifications:")

left, right = st.columns([1.65, 1], gap="large")
with left:
    st.markdown("#### 착수계·계산기 진행 현황")
    rows = [{"구분": "착수계" if c["kind"] == "startup" else "계산기", "업체": c["company_name"], "회차": c["round"], "상태": c.get("status", "-"),
             "검수": ui.review_state(c, ev), "판정 요약": ui.counts_line(ev["counts"], len(ev["pending"]))} for c, ev in evs]
    if rows:
        st.dataframe(pd.DataFrame(rows).style.map(lambda v: ui.STATUS_STYLE.get(v, ""), subset=["상태", "검수"]), hide_index=True, width="stretch")
    else:
        st.info("진행 중인 건이 없습니다.", icon=":material/info:")
    ui.virtual_tag("가상 기업·C-002 계약·업로드 파일은 시연용 가상 데이터")
    a, b = st.columns(2)
    a.page_link("pages/04_startup.py", label="착수계 등록·관리", icon=":material/assignment:")
    b.page_link("pages/06_calculator.py", label="금액 산출 계산기", icon=":material/calculate:")
with right:
    st.markdown("#### 처리할 일")
    todo = []
    for c, ev in evs:
        if ev["pending"]:
            todo.append(f"<li>{ui.pill('오류 정정', 'red')} {c['company_name']} {c['round']} · {len(ev['pending'])}건</li>")
        elif review.state(c, ev) != review.DONE and c.get("status") != startup.FIX:
            todo.append(f"<li>{ui.pill('검수', 'yellow')} {c['company_name']} {c['round']}</li>")
    st.markdown("<div class='notice'><div class='h'>오늘 처리할 업무</div><ul>" + ("".join(todo[:8]) or "<li>처리할 업무가 없습니다.</li>") + "</ul></div>",
                unsafe_allow_html=True)
    st.markdown("#### 계약 만료·갱신 알림")
    info = load_contracts()
    today = info["demo_today"]
    alerts = [("외주", c_["name"], c_["end"]) for c_ in info["contracts"]]
    alerts += [("기간제", x.name, info["temp_staff"][x.name]["end"]) for x in load_employees()]
    alerts = sorted(((k, n, end, (end - today).days) for k, n, end in alerts if (end - today).days <= info["alert_days"]), key=lambda x: x[3])
    st.dataframe(pd.DataFrame([{"D-day": f"D-{d_}", "구분": k, "대상": n, "종료일": str(end)} for k, n, end, d_ in alerts]), hide_index=True, width="stretch")
    st.caption("계약기간은 원본에 없어 시연용 가정값입니다.")
    st.page_link("pages/02_validate.py", label=f"오류·근거 검증 결과 (실제 엑셀 오류 {n_err}건)", icon=":material/rule:")
