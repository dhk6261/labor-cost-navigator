import pandas as pd
import streamlit as st

from core import auth, calculator, extract, review, standard as sd, startup_docs, ui
from core.case import evaluate
from core.data import DATA, active_year, rate_values

user = ui.guard(auth.ADMIN)
ui.page("금액 산출 계산기", "업체별 파일을 올리면 앱 안의 AI 문서 인식 모듈이 핵심 값을 읽고, 계산 엔진이 공단 산정 금액을 만들어 비교합니다.")
st.caption("AI 문서 인식은 앱 안에서만 동작하며 파일 내용은 밖으로 나가지 않습니다. 추출기는 값과 위치만 꺼내고 금액은 계산 엔진(core/calc.py)이 만듭니다.")
r = rate_values(active_year())
ss = st.session_state
STEPS = ["① 업체 선택", "② 파일 올리기", "③ AI 추출 결과", "④ 산출 결과", "⑤ 업체 비교", "⑥ 검수", "⑦ 산출물"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DEMO = {"가상업체A_산출내역.xlsx": "엑셀(승인 가능 자료)", "가상업체B_산출내역.xlsx": "엑셀(미달·누락·과지급)", "가상업체C_산출내역.pdf": "텍스트 PDF(과지급 1)"}

companies = auth.companies()
ids = [c["id"] for c in companies]
if ss.get("calc_company") not in ids:
    ss["calc_company"] = ids[0]
if ss.get("calc_step") not in STEPS:
    ss["calc_step"] = STEPS[0]
step = st.segmented_control("단계", STEPS, key="calc_step") or STEPS[0]

a, b = st.columns([2, 1])
cid = a.selectbox("업체", ids, format_func=lambda i: next(f"{c['name']}" + ("" if c["account"] else " · 계정 없음(관리자 추가)") for c in companies if c["id"] == i),
                  key="calc_company")
co = auth.company(cid)
runs = calculator.runs(user, cid)
if runs:
    nums = [x["n"] for x in runs]
    if ss.get("calc_run") not in nums:
        ss["calc_run"] = nums[-1]
    n = b.selectbox("회차", nums, format_func=lambda k: f"R{k} · {next(x['file']['name'] for x in runs if x['n'] == k)}", key="calc_run")
    case = calculator.get(user, cid, n)
    ev = evaluate(case)
else:
    case, ev = None, None
    b.caption("아직 올린 파일이 없습니다.")

if step == STEPS[0]:
    st.dataframe(pd.DataFrame([{"ID": c["id"], "업체": c["name"], "계정": "있음" if c["account"] else "없음(관리자 추가)",
                                "회차": len(calculator.runs(user, c["id"]))} for c in companies]), hide_index=True, width="stretch")
    with st.form("calc_add"):
        st.markdown("**업체 직접 추가** (기업명·계약명만, 계정 없이)")
        x, y, z = st.columns([2, 2.4, 1])
        name = x.text_input("기업명", key="calc_new_name")
        contract = y.text_input("계약명", key="calc_new_contract")
        heads = z.number_input("인원", 1, 200, 3, key="calc_new_heads")
        if st.form_submit_button("추가"):
            try:
                new = auth.add_company(user, name, contract, heads)
                ss["calc_company"] = new["id"]
                st.rerun()
            except ValueError as e:
                st.error(str(e))

elif step == STEPS[1]:
    x, y = st.columns([2, 1])
    up = x.file_uploader("산출내역 파일(.xlsx 10MB 이하·.csv·.docx(표)·텍스트 .pdf)", type=["xlsx", "csv", "docx", "pdf"], key="calc_file_up")
    engine = y.selectbox("추출기", list(extract.REGISTRY), key="calc_engine", help="시연판은 규칙 추출기. 공단 내부망 설치형 모델을 같은 인터페이스로 등록할 수 있습니다.")
    demo = y.selectbox("또는 시연용 가상 파일", ["(선택 안 함)"] + list(DEMO), format_func=lambda k: k if k not in DEMO else f"{k} · {DEMO[k]}", key="calc_demo")
    st.caption("스캔 이미지 PDF는 텍스트가 없어 지원하지 않습니다(OCR은 향후 확장). 원본 파일은 저장하지 않고 추출 결과만 보관합니다.")
    raw, fname = (up.getvalue(), up.name) if up else ((DATA / "demo_vendors" / demo).read_bytes(), demo) if demo in DEMO else (None, None)
    if raw and st.button(f"AI 문서 인식 실행 · {fname}", type="primary", key="calc_run_extract"):
        try:
            new = calculator.upload(user, cid, raw, fname, engine)
            ss.update(calc_run=new["n"], calc_step=STEPS[2])
            st.rerun()
        except extract.RepairError as e:
            st.error(str(e))

elif case is None:
    st.info("먼저 ② 파일 올리기에서 이 업체의 파일을 올리세요.")

elif step == STEPS[2]:
    st.markdown(f"**{case['round']} · {case['file']['name']}** · {case['source']} · 원본 보관: {case['file'].get('원본 보관', '-')}")
    if case.get("pii_dropped"):
        st.info(f"개인정보 열 {case['pii_dropped']}개는 읽지 않았습니다.", icon=":material/shield_lock:")
    for w in case.get("warnings") or []:
        st.warning(w)
    low = sd.judge()["low_confidence"]["value"]
    fields = case["fields"]
    if not fields:
        st.info("첨부 없이 착수계 양식 값으로 산출한 회차입니다.")
    else:
        table = pd.DataFrame([{"종류": f["종류"], "이름(표준 항목)": f["이름"], "값": f["값"], "단위": f["단위"], "원문 위치": f["위치"], "원문 글자": f["원문"],
                               "확신도": f["확신도"], "방식": f["방식"], "확인": "확인됨" if f["key"] in case["confirmed"] else ("확인 필요" if f["확신도"] < low else "")}
                              for f in fields])
        st.dataframe(table.style.map(lambda v: ui.AMBER if isinstance(v, float) and v < low else "", subset=["확신도"])
                     .map(lambda v: ui.AMBER if v == "확인 필요" else "", subset=["확인"]), hide_index=True, width="stretch", height=min(38 + 35 * len(table), 700))
        st.caption(f"확신도 {low:.2f} 미만 값은 검수 전에 확인해야 합니다. 0.85 이상 자동 연결, 0.6~0.85 확인 필요, 0.6 미만 미분류.")
        if ev["unconfirmed"] and st.button(f"확신도 낮은 값 {len(ev['unconfirmed'])}개 확인 완료", key="calc_confirm"):
            review.confirm_fields(user, case, [f["key"] for f in ev["unconfirmed"]])
            st.rerun()
        with st.expander("값 고치기 · 항목 연결 고치기 (이력에 남고 다음 추출 때 보조값으로 쓰임)"):
            labels = {f["key"]: f"{f['이름']} · {f['위치']} · {f['원문']}" for f in fields}
            key = st.selectbox("대상", list(labels), format_func=labels.get, key="calc_fix_key")
            f = next(x for x in fields if x["key"] == key)
            x, y = st.columns(2)
            if f["종류"] == extract.ITEM:
                options = sd.BASE_ITEMS + ["(제외)"]
                cur = f["이름"] if f["이름"] in options else "(제외)"
                item = x.selectbox("표준 항목 연결", options, index=options.index(cur), key=f"calc_link_{key}")
                if x.button("연결 저장", key="calc_link_save"):
                    calculator.relink(user, case, key, None if item == "(제외)" else item)
                    st.rerun()
            value = y.text_input("값", str(f["값"]), key=f"calc_val_{key}")
            if y.button("값 저장", key="calc_val_save"):
                num, _ = extract.normalize(value)
                calculator.edit_field(user, case, key, num if num is not None and f["단위"] != "" else value)
                st.rerun()

elif step == STEPS[3]:
    st.markdown(f"**{case['company_name']} · {case['round']}** &nbsp; {ui.pill(ui.review_state(case, ev))}", unsafe_allow_html=True)
    if case.get("recheck") and not review.is_valid(case, ev):
        st.error("**기준 변경으로 재검수 필요** · 새 기준으로 다시 계산해 금액이 바뀌었습니다.", icon=":material/autorenew:")
    ui.basis_panel(ev["year"])
    ui.badges(ev)
    for g in ev["groups"]:
        st.caption(f"산출 입력(추출값): 인원 {g['inputs']['headcount']}명 · 월 {g['inputs']['monthly_hours']:g}시간 · 일급 {g['inputs']['daily'] or r['market_daily']:,.0f}원 · "
                   f"공단 산정은 시중노임단가 이상·법정 요율로 계산")
        ui.standard_table(g["rows"])
    ui.correction_box(user, case, ev, f"cr_{case['id']}")

elif step == STEPS[4]:
    st.caption("업체별 최신 회차를 같은 항목 기준으로 나란히 놓았습니다. 공단 산정은 calc_standard(기본 입력: 월 209시간), 규모가 달라도 **1인·연간** 기준입니다.")
    latest = calculator.latest(user)
    std = sd.base_amounts(sd.office_amounts({}, r))
    evs = {c["company_name"]: (c, evaluate(c)) for c in latest}
    names = list(evs)
    rows, status = [], []
    for item in sd.BASE_ITEMS:
        row, srow = {"항목": item}, {}
        for nm in names:
            v = evs[nm][1]["groups"][0]["company"].get(item)
            row[nm] = v
            row[f"{nm} 차이"] = None if v is None else v - std[item]
            row[f"{nm} 차이율"] = None if v is None else v / std[item] - 1
            srow[nm] = evs[nm][1]["groups"][0]["check"]["items"][item]["상태"]
        row["공단 산정"] = std[item]
        rows.append(row)
        status.append(srow)
    if not names:
        st.info("비교할 회차가 없습니다.")
    else:
        df = pd.DataFrame(rows)[["항목"] + names + ["공단 산정"] + [f"{n_} {k}" for n_ in names for k in ("차이", "차이율")]]
        colors = {sd.LOW: ui.RED, sd.OVER: ui.PURPLE, sd.MISSING: ui.ORANGE, sd.CHECK: ui.AMBER}

        def paint(frame):
            out = pd.DataFrame("", index=frame.index, columns=frame.columns)
            for i in frame.index:
                for nm in names:
                    s = status[i].get(nm)
                    cols = [nm, f"{nm} 차이", f"{nm} 차이율"]
                    if frame.loc[i, nm] is None or pd.isna(frame.loc[i, nm]):
                        out.loc[i, cols] = ui.GRAY
                    elif s in colors:
                        out.loc[i, cols] = colors[s]
            return out

        fmt = {c: (lambda v: "없음" if v is None or pd.isna(v) else f"{v:,.0f}") for c in names + ["공단 산정"]}
        fmt |= {f"{n_} 차이": (lambda v: "-" if v is None or pd.isna(v) else f"{v:+,.0f}") for n_ in names}
        fmt |= {f"{n_} 차이율": (lambda v: "-" if v is None or pd.isna(v) else f"{v:+.1%}") for n_ in names}
        st.dataframe(df.style.apply(paint, axis=None).format(fmt), hide_index=True, width="stretch", height=38 + 35 * len(df))
        st.caption("누락(회색 '없음') · 미달 · 과지급 · 확인 필요. " + " / ".join(f"{nm} {evs[nm][0]['round']}" for nm in names))

elif step == STEPS[5]:
    ui.badges(ev)
    ui.correction_box(user, case, ev, f"cr6_{case['id']}")
    ui.review_box(user, case, ev, f"rv_{case['id']}")

elif step == STEPS[6]:
    if not review.is_valid(case, ev):
        st.warning(f"**{review.DRAFT_MARK}** · 검수 완료 전에는 산출물을 만들 수 없습니다(화면 미리보기만).", icon=":material/edit_note:")
        for g in ev["groups"]:
            st.markdown(f"<span class='tag'>{review.DRAFT_MARK}</span>", unsafe_allow_html=True)
            ui.standard_table(g["rows"], show_reason=False)
    else:
        st.success(review.stamp(case))
        x, y, z = st.columns(3)
        if x.button("인건비 산출내역서", type="primary", key="calc_make_cost"):
            ss["calc_file"] = {"id": case["id"], "data": startup_docs.build_cost_sheet(user, case)}
        if y.button("착수계 4종", key="calc_make_all"):
            ss["calc_files"] = {**startup_docs.build_all(user, case), "id": case["id"]}
        if z.button("근로자 설명서", key="calc_make_worker"):
            ss["calc_worker"] = {"id": case["id"], "data": startup_docs.worker_doc(user, case)}
        f = ss.get("calc_file")
        if f and f["id"] == case["id"]:
            st.download_button("인건비 산출내역서(.xlsx)", f["data"], f"인건비_산출내역서_{case['company_name']}_{case['round']}.xlsx", XLSX, key="calc_dl_cost")
        f = ss.get("calc_files")
        if f and f["id"] == case["id"]:
            st.download_button("착수계 4종(ZIP)", f["zip"], f"착수계_{case['company_name']}_{case['round']}.zip", "application/zip", key="calc_dl_zip")
        f = ss.get("calc_worker")
        if f and f["id"] == case["id"]:
            st.download_button("근로자 설명서(.docx)", f["data"], f"근로자_설명서_{case['company_name']}.docx", DOCX, key="calc_dl_worker")
