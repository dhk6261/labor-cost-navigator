from datetime import date

import pandas as pd
import streamlit as st

from core import auth, calculator, review, startup, startup_docs, ui, workflow
from core.calc import STANDARD_JOB
from core.case import evaluate
from core.data import active_year, rate_values

user = ui.guard()
ui.page("착수계 등록·관리", "기업은 착수계 내용을 단계별 양식으로 등록하고, 관리자는 표준 산출서로 검증·정정·검수한 뒤 승인합니다.")
r = rate_values(active_year())
STEPS = ["① 계약 정보", "② 투입 인력", "③ 임금 조건", "④ 경비", "⑤ 첨부(선택)", "⑥ 미리보기·등록"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ss = st.session_state


# ───────────── 기업: 채용정보 등록처럼 ─────────────
def _populate(step: int) -> None:
    f = ss["reg_form"]
    c, w, e = f["contract"], f["wage"], f["expense"]
    if step == 1:
        ss.update(reg_name=c["name"], reg_no=c["no"], reg_start=date.fromisoformat(c["start"]), reg_end=date.fromisoformat(c["end"]),
                  reg_sdate=date.fromisoformat(c["start_date"]), reg_manager=c["manager"])
    elif step == 3:
        ss.update(reg_daily=int(w["daily"]), reg_ot=float(w["ot_hours"]), reg_hol=float(w["hol_hours"]), reg_over=float(w["hol_over_hours"]),
                  reg_leave=float(w["leave_days"]))
    elif step == 4:
        ss.update(reg_uniform=int(e["uniform"]), reg_shoes=int(e["shoes"]))
    ss.pop("reg_groups", None)


def _sync() -> None:
    """현재 단계 입력칸 값을 양식에 옮긴다."""
    f = ss.get("reg_form")
    if not f:
        return
    c, w, e = f["contract"], f["wage"], f["expense"]
    for key, sec, name, conv in (("reg_name", c, "name", str), ("reg_no", c, "no", str), ("reg_start", c, "start", str), ("reg_end", c, "end", str),
                                 ("reg_sdate", c, "start_date", str), ("reg_manager", c, "manager", str), ("reg_daily", w, "daily", int),
                                 ("reg_ot", w, "ot_hours", float), ("reg_hol", w, "hol_hours", float), ("reg_over", w, "hol_over_hours", float),
                                 ("reg_leave", w, "leave_days", float), ("reg_uniform", e, "uniform", int), ("reg_shoes", e, "shoes", int)):
        if key in ss:
            sec[name] = conv(ss[key])


def _goto(n: int) -> None:
    _sync()
    ss["reg_step"] = n
    ss.pop("reg_loaded", None)


def _open(form: dict, sid: str | None) -> None:
    ss.update(reg_form=form, reg_id=sid, reg_step=1, reg_open=True)
    ss.pop("reg_loaded", None)


def validation(company_id: str, form: dict) -> dict:
    ev = startup.preview(company_id, form)
    c = ev["counts"]
    st.markdown(f"**입력 즉시 검증** · {ui.counts_line(c)}")
    for g in ev["groups"]:
        for text in g["check"]["items"]["기본급"]["사유"]:
            (st.error if "미달" in text else st.warning)(text, icon=":material/error:" if "미달" in text else "")
    if ev["blocking"]:
        st.error("최저임금 미달이 있어 **등록할 수 없습니다**. 임시저장은 됩니다.", icon=":material/block:")
    elif c["과지급"]:
        st.warning("과지급 의심 항목이 있습니다. 미리보기에서 확인하세요.", icon=":material/report:")
    ui.log_on_change("reg_check", "착수계 입력 검증", f"일급 {form['wage']['daily']:,}원 → {ui.counts_line(c)}")
    return ev


def wizard(company_id: str) -> None:
    f = ss["reg_form"]
    step = ss.get("reg_step", 1)
    if ss.get("reg_loaded") != step:
        _populate(step)
        ss["reg_loaded"] = step
    st.progress(step / len(STEPS), text=" → ".join(f"**{s}**" if i + 1 == step else s for i, s in enumerate(STEPS)))
    with st.container(border=True):
        st.markdown(f"#### {STEPS[step - 1]}")
        if step == 1:
            a, b = st.columns(2)
            a.text_input("계약명", key="reg_name")
            b.text_input("계약번호", key="reg_no")
            a.date_input("계약 시작일", key="reg_start")
            b.date_input("계약 종료일", key="reg_end")
            a.date_input("착수일", key="reg_sdate")
            b.text_input("현장 책임 직위(실명 입력 안 함)", key="reg_manager")
        elif step == 2:
            st.caption("직종·인원·근무형태·근무시간만 적습니다. 실명·주민번호·연락처 칸은 없습니다. 행을 추가해 직종을 여러 개 넣을 수 있습니다.")
            df = pd.DataFrame(f["groups"])
            edited = st.data_editor(df, key="reg_groups", num_rows="dynamic", hide_index=True, width="stretch", column_config={
                "직종": st.column_config.SelectboxColumn(options=[STANDARD_JOB, "경비원", "시설관리원", "기타"], required=True),
                "인원": st.column_config.NumberColumn(min_value=1, max_value=200, step=1, required=True),
                "근무형태": st.column_config.SelectboxColumn(options=["전일", "단시간"], required=True),
                "월 근무시간": st.column_config.NumberColumn(min_value=20.0, max_value=260.0, required=True),
                "근무일수": st.column_config.NumberColumn(min_value=1, max_value=31, step=1, required=True)})
            rows = [x for x in edited.to_dict("records") if x.get("직종") and x.get("인원")]
            if rows:
                f["groups"] = [{"직종": x["직종"], "인원": int(x["인원"]), "근무형태": x["근무형태"] or "전일", "월 근무시간": float(x["월 근무시간"] or 209),
                                "근무일수": int(x["근무일수"] or 22)} for x in rows]
        elif step == 3:
            a, b = st.columns(2)
            a.number_input("일급(원)", 50_000, 300_000, step=1, key="reg_daily", help=f"적용 시점 시중노임단가 {r['market_daily']:,}원")
            b.number_input("연차수당 일수(연)", 0.0, 25.0, step=1.0, key="reg_leave")
            c1, c2, c3 = st.columns(3)
            c1.number_input("연장(시간/월)", 0.0, 60.0, step=0.01, format="%.4f", key="reg_ot")
            c2.number_input("휴일 8시간 이내(시간/월)", 0.0, 40.0, step=0.01, format="%.4f", key="reg_hol")
            c3.number_input("휴일 8시간 초과(시간/월)", 0.0, 20.0, step=0.01, format="%.4f", key="reg_over")
            st.caption("상여금은 기본급 100%(연 1개월분), 퇴직충당금은 임금 ÷ 12로 계산합니다. 시급제는 시급 × 8을 일급으로 적으세요.")
        elif step == 4:
            a, b = st.columns(2)
            a.number_input("피복비(월, 원)", 0, 100_000, step=100, key="reg_uniform")
            b.number_input("작업화(월, 원)", 0, 100_000, step=100, key="reg_shoes")
        elif step == 5:
            up = st.file_uploader("기업이 쓰는 산출내역 파일(선택: .xlsx·.csv·.docx·.pdf, 10MB 이하)", type=["xlsx", "csv", "docx", "pdf"], key="reg_file")
            if up:
                from core import extract
                try:
                    att = {**extract.extract(up.getvalue(), up.name), "filename": up.name}
                    f["attachment"] = att
                    st.success(f"첨부를 읽었습니다: 값 {len(att['fields'])}개. 관리자가 계산기에서 확인합니다.")
                    if att["pii_dropped"]:
                        st.info(f"개인정보 열 {att['pii_dropped']}개는 읽지 않았습니다.", icon=":material/shield_lock:")
                except extract.RepairError as e:
                    st.error(str(e))
            elif f.get("attachment"):
                st.caption(f"첨부됨: {f['attachment'].get('filename')}")
        _sync()
        ev = validation(company_id, f) if step < 6 else startup.preview(company_id, f)
        if step == 6:
            ui.badges(ev)
            ui.basis_panel(expanded=False)
            for g in ev["groups"]:
                st.markdown(f"**{g['label']}**")
                ui.standard_table(g["rows"])
    a, b, c, d = st.columns([1, 1, 1, 2])
    a.button("◀ 이전", on_click=_goto, args=(step - 1,), disabled=step == 1, key="reg_prev", width="stretch")
    if step < len(STEPS):
        b.button("다음 ▶", on_click=_goto, args=(step + 1,), type="primary", key="reg_next", width="stretch")
    if c.button("임시저장", key="reg_save", width="stretch"):
        saved = startup.save_draft(user, company_id, f, sid=ss.get("reg_id"))
        ss["reg_id"] = saved["id"]
        st.success(f"{saved['round']} 임시저장했습니다.")
    if step == len(STEPS):
        need = any(ev["counts"].values())
        reason = d.text_area("사유(미달·누락·과지급·확인 필요가 있을 때 필수)", key="reg_reason", height=70) if need and not ev["blocking"] else ""
        if d.button("등록", type="primary", key="reg_submit", disabled=bool(ev["blocking"]) or (need and not reason.strip())):
            try:
                saved = startup.save_draft(user, company_id, f, sid=ss.get("reg_id"))
                startup.register(user, saved["id"], reason)
                for k in ("reg_open", "reg_id", "reg_form", "reg_loaded"):
                    ss.pop(k, None)
                st.rerun()
            except (startup.StartupError, PermissionError) as e:
                st.error(str(e))


def company_view() -> None:
    cid = user["company"]
    co = auth.company(cid)
    st.info(f"**{user['name']}** · 다른 기업의 자료는 볼 수 없습니다.", icon=":material/lock:")
    mine = sorted(startup.list_for(user), key=lambda x: x["version"], reverse=True)
    if ss.get("reg_open") and ss.get("reg_form"):
        wizard(cid)
        if st.button("목록으로", key="reg_close"):
            ss["reg_open"] = False
            st.rerun()
        return
    draft = next((x for x in mine if x["status"] == startup.DRAFT), None)
    busy = next((x for x in mine if x["status"] == startup.REGISTERED), None)
    a, _ = st.columns([1, 3])
    if draft:
        a.button("임시저장 이어서 작성", type="primary", on_click=_open, args=(draft["form"], draft["id"]), key="reg_continue", width="stretch")
    else:
        a.button("새 착수계 등록", type="primary", on_click=_open, args=(startup.default_form(cid), None), key="reg_new", width="stretch", disabled=bool(busy))
    if not mine:
        st.caption(f"{co['name']}의 등록된 착수계가 없습니다.")
    for x in mine:
        with st.container(border=True):
            l, m = st.columns([3, 1.2])
            people = sum(g["인원"] for g in x["form"]["groups"])
            l.markdown(f"**{x['contract']['name']}** · {x['round']} · 착수일 {x['contract']['start_date']} · {people}명")
            l.markdown(f"{ui.pill(x['status'])} <span style='color:#5A6472;font-size:.86rem'>{ui.counts_line(x['counts'])}</span>", unsafe_allow_html=True)
            if x["status"] == startup.FIX:
                st.error(f"보완 요청 사유: {x['fix_reason']}", icon=":material/undo:")
                m.button("고쳐서 다시 등록", key=f"reg_fix_{x['id']}", disabled=bool(draft or busy),
                         on_click=lambda x=x: _open(startup.new_version(user, x["id"])["form"], _latest_draft()))
            elif x["status"] == startup.APPROVED:
                l.caption(f"승인 {x['approved_at']} · 잠김(수정 불가)")
                m.button("새 버전 만들기", key=f"reg_nv_{x['id']}", disabled=bool(draft or busy),
                         on_click=lambda x=x: _open(startup.new_version(user, x["id"])["form"], _latest_draft()))


def _latest_draft() -> str | None:
    return next((x["id"] for x in startup.list_for(user) if x["status"] == startup.DRAFT), None)


# ───────────── 관리자: 등록 관리 ─────────────
def admin_view() -> None:
    cases = [x for x in startup.list_for(user) if x["status"] != startup.DRAFT]
    if not cases:
        st.info("등록된 착수계가 없습니다. 계정 없는 업체는 **금액 산출 계산기**에서 바로 작업할 수 있습니다.")
        return
    pick = st.multiselect("상태", [startup.REGISTERED, startup.FIX, startup.APPROVED], default=[startup.REGISTERED, startup.FIX, startup.APPROVED], key="st_filter")
    rows = []
    for x in cases:
        ev = evaluate(x)
        rows.append({"기업": x["company_name"], "계약": x["contract"]["name"], "버전": x["round"], "상태": x["status"], "검수": ui.review_state(x, ev),
                     "등록 시각": x.get("registered_at", "-"), "검증": ui.counts_line(ev["counts"], len(ev["pending"]))})
    view = pd.DataFrame([r_ for r_, x in zip(rows, cases) if x["status"] in pick])
    if len(view):
        st.dataframe(view.style.map(lambda v: ui.STATUS_STYLE.get(v, ""), subset=["상태", "검수"]), hide_index=True, width="stretch")
    by_id = {x["id"]: x for x in cases}
    if ss.get("st_sel") not in by_id:
        ss["st_sel"] = next((x["id"] for x in cases if x["status"] == startup.REGISTERED), cases[0]["id"])
    sel = st.selectbox("등록물 열기", list(by_id), format_func=lambda i: f"{by_id[i]['company_name']} · {by_id[i]['round']} · {by_id[i]['status']}", key="st_sel")
    case = startup.get(user, sel)
    ev = evaluate(case)
    state = ui.review_state(case, ev)
    st.markdown(f"### {case['company_name']} · {case['contract']['name']} · {case['round']}")
    st.markdown(f"{ui.pill(case['status'])}{ui.pill(state)}", unsafe_allow_html=True)
    if case.get("recheck") and state != review.DONE:
        st.error("**기준 변경으로 재검수 필요** · 새 기준으로 다시 계산해 금액이 바뀌었습니다. 검수가 풀렸습니다.", icon=":material/autorenew:")
    if case.get("reason"):
        st.caption(f"기업 등록 사유: {case['reason']}")
    ui.badges(ev)
    ui.basis_panel(ev["year"], expanded=False)
    for g in ev["groups"]:
        st.markdown(f"**{g['label']}** · 업체 금액(기업 입력 조건으로 계산) vs 공단 산정")
        ui.standard_table(g["rows"])
    st.caption("원본의 '복리후생비 계'는 표준표에서 **법정부담금 계** + **피복비·작업화(경비)** 로 나뉩니다.")

    t_fix, t_edit, t_review, t_out = st.tabs(["오류 정정", "값 직접 수정", "검수·승인", "산출물"])
    with t_fix:
        ui.correction_box(user, case, ev, f"cr_{case['id']}")
    with t_edit:
        if case.get("locked"):
            st.info("승인된 버전은 수정할 수 없습니다. 기업이 새 버전을 등록해야 합니다.")
        else:
            f = case["form"]
            a, b, c = st.columns(3)
            daily = a.number_input("일급(원)", 50_000, 300_000, int(f["wage"]["daily"]), key=f"st_e_daily_{case['id']}")
            uni = b.number_input("피복비(월)", 0, 100_000, int(f["expense"]["uniform"]), key=f"st_e_uni_{case['id']}")
            shoes = c.number_input("작업화(월)", 0, 100_000, int(f["expense"]["shoes"]), key=f"st_e_shoes_{case['id']}")
            if st.button("수정 저장(수정 전후 이력 기록)", key=f"st_e_save_{case['id']}"):
                new = {**f, "wage": {**f["wage"], "daily": daily}, "expense": {**f["expense"], "uniform": uni, "shoes": shoes}}
                startup.admin_edit(user, case["id"], new)
                st.rerun()
        if case["status"] == startup.REGISTERED:
            st.divider()
            reason = st.text_area("보완 요청 사유(필수)", workflow.reason_example(case) if ev["pending"] else "", key=f"st_fix_{case['id']}", height=80)
            x, y = st.columns(2)
            if x.button("보완 요청", key=f"st_fixbtn_{case['id']}", disabled=not reason.strip()):
                startup.request_fix(user, case["id"], reason)
                st.rerun()
            if y.button("계산기로 보내기", key=f"st_calc_{case['id']}"):
                run = calculator.from_startup(user, case)
                ss.update(calc_company=case["company"], calc_run=run["n"], calc_step="④ 산출 결과")
                st.switch_page("pages/06_calculator.py")
    with t_review:
        done = ui.review_box(user, case, ev, f"rv_{case['id']}")
        if case["status"] == startup.REGISTERED:
            blocked = bool(ev["pending"]) or not done
            if st.button("승인", type="primary", key=f"st_ok_{case['id']}", disabled=blocked):
                try:
                    startup.approve(user, case["id"])
                    st.rerun()
                except startup.StartupError as e:
                    st.error(str(e))
            if blocked:
                st.caption("승인은 검수 완료 + 누락·미달·과지급 정정 대기 0건일 때만 가능합니다.")
        elif case["status"] == startup.APPROVED:
            st.success(f"승인됨 · {case['approved_at']} · {case['approver']} · 버전 잠김", icon=":material/lock:")
    with t_out:
        if not review.is_valid(case, ev):
            st.warning(f"**{review.DRAFT_MARK}** · 검수 완료 전에는 착수계 4종·근로자 설명서·공문을 내려받을 수 없습니다. 위 표가 미리보기입니다.", icon=":material/edit_note:")
        else:
            st.caption(f"{startup_docs.FORM_NOTE} · {review.stamp(case)}")
            files = ss.get("st_files")
            if st.button("착수계 4종 생성", type="primary", key="st_make"):
                ss["st_files"] = files = {**startup_docs.build_all(user, case), "id": case["id"]}
            if files and files.get("id") == case["id"]:
                cols = st.columns(5)
                cols[0].download_button("ZIP(4종)", files["zip"], f"착수계_{case['company_name']}_{case['round']}.zip", "application/zip", key="st_zip", width="stretch")
                for col, (k, name) in zip(cols[1:], startup_docs.NAMES.items()):
                    col.download_button(k, files[k], name, DOCX if name.endswith(".docx") else XLSX, key=f"st_dl_{k}", width="stretch")
            if st.button("근로자 설명서 만들기", key="st_worker"):
                ss["st_worker"] = {"id": case["id"], "data": startup_docs.worker_doc(user, case)}
            w = ss.get("st_worker")
            if w and w["id"] == case["id"]:
                st.download_button("근로자 설명서(.docx, 1쪽)", w["data"], f"근로자_설명서_{case['company_name']}.docx", DOCX, key="st_worker_dl")
            short = next((x for x in workflow.approved_shortfalls(user) if x["case"]["id"] == case["id"]), None)
            if short:
                st.markdown("##### 새 기준 미달 → 재제출 요청 공문")
                if st.button("재제출 요청 공문 만들기", key="st_resubmit"):
                    ss["st_resub"] = {"id": case["id"], "data": startup_docs.resubmit_doc(user, case, short["items"], r)}
                rs = ss.get("st_resub")
                if rs and rs["id"] == case["id"]:
                    st.download_button("재제출 요청 공문(.docx)", rs["data"], f"재제출요청_{case['company_name']}.docx", DOCX, key="st_resub_dl")


if user["role"] == auth.COMPANY:
    company_view()
else:
    admin_view()
