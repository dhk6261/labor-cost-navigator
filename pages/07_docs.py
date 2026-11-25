import re

import streamlit as st

from core import audit, auth, review, startup_docs, ui, workflow
from core.case import evaluate
from core.data import active_year, rate_values
from core.docs import KINDS, TEXT_KINDS, build, to_docx, to_markdown

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
user = ui.guard(auth.ADMIN)
ui.page("문서 초안 생성", "계산 결과로 채운 초안입니다. 모든 문서는 관리자가 검수 완료를 누른 뒤에만 내려받을 수 있습니다.")
ss = st.session_state

kinds = list(KINDS)
if not audit.get_state()["recalculated"]:
    kinds = [k for k in kinds if k not in ("계약 변경 공문", "품의서")]
    st.info("계약 변경 공문·품의서는 **기준 관리·재산출**에서 새 기준을 적용하면 만들 수 있습니다.")
if ss.get("doc_kind") not in kinds:
    ss["doc_kind"] = kinds[0]
kind = st.radio("문서 종류", kinds, horizontal=True, key="doc_kind")
reviewed = [c for c in workflow.all_cases(user) if review.is_valid(c)]
label = lambda c: f"{c['company_name']} · {c['round']} · {'착수계' if c['kind'] == 'startup' else '계산기'}"

if kind in TEXT_KINDS:
    if st.button("초안 생성", type="primary", key="gen"):
        ss["doc_ready"] = kind
        audit.log("문서 생성", f"{kind} 초안 생성(검수 전)")
        st.rerun()
    if ss.get("doc_ready") == kind:
        doc = build(kind, ui.current_births())
        md = to_markdown(doc)
        rv = review.doc_review(kind, md)
        if rv:
            st.success(f"검수 완료: {rv['by']}, {rv['at']}, 기준 {rv['basis']}")
            text = md + f"\n\n> 검수 완료: {rv['by']}, {rv['at']}, 기준 {rv['basis']}"
            review.require_doc(user, kind, md)
            a, b, _ = st.columns([1, 1, 3])
            doc["notice"] += f" · 검수 완료: {rv['by']}, {rv['at']}, 기준 {rv['basis']}"
            a.download_button(".docx", to_docx(doc), f"{kind}.docx", DOCX, key="dl_docx", width="stretch")
            b.download_button(".txt", re.sub(r"[#*>]", "", text).encode("utf-8-sig"), f"{kind}.txt", "text/plain", key="dl_txt", width="stretch")
        else:
            st.warning(f"**{review.DRAFT_MARK}** · 내용을 확인하고 검수 완료를 누르면 내려받을 수 있습니다.", icon=":material/edit_note:")
            if st.button("검수 완료", key="doc_review"):
                review.review_doc(user, kind, md)
                st.rerun()
        with st.container(border=True):
            if not rv:
                st.markdown(f"<span class='tag'>{review.DRAFT_MARK}</span>", unsafe_allow_html=True)
            st.markdown(md)

elif kind in ("착수계", "근로자 설명서"):
    if not reviewed:
        st.warning(f"검수 완료된 건이 없습니다. **착수계 등록·관리** 또는 **금액 산출 계산기**에서 검수를 마치면 만들 수 있습니다({review.DRAFT_MARK}은 생성 불가).", icon=":material/edit_note:")
    else:
        case = st.selectbox("검수 완료된 건", reviewed, format_func=label, key="doc_case")
        st.caption(review.stamp(case))
        if st.button("만들기", type="primary", key="doc_make"):
            ss["doc_file"] = {"id": case["id"], "kind": kind,
                              "data": startup_docs.build_all(user, case)["zip"] if kind == "착수계" else startup_docs.worker_doc(user, case)}
        f = ss.get("doc_file")
        if f and f["id"] == case["id"] and f.get("kind") == kind:
            name = f"착수계_{case['company_name']}_{case['round']}.zip" if kind == "착수계" else f"근로자_설명서_{case['company_name']}.docx"
            st.download_button(f"{name}", f["data"], name, "application/zip" if kind == "착수계" else DOCX, key="doc_dl")

else:  # 재제출 요청 공문
    short = workflow.approved_shortfalls(user)
    if not short:
        st.info("승인된 착수계 가운데 현재 기준에 미달하는 건이 없습니다. 기준 적용·재산출 뒤에 다시 확인하세요.")
    else:
        item = st.selectbox("새 기준 미달 착수계", short, format_func=lambda x: label(x["case"]), key="doc_short")
        c = item["case"]
        if not review.is_valid(c, item["ev"]):
            st.warning(f"**{review.DRAFT_MARK}** · 기준 변경으로 재검수가 필요합니다. 착수계 등록·관리에서 재검수를 마치면 공문을 만들 수 있습니다.", icon=":material/autorenew:")
        else:
            st.caption(review.stamp(c))
            if st.button("재제출 요청 공문 만들기", type="primary", key="doc_resubmit"):
                ss["doc_file"] = {"id": c["id"], "kind": kind, "data": startup_docs.resubmit_doc(user, c, item["items"], rate_values(active_year()))}
        f = ss.get("doc_file")
        if f and f["id"] == c["id"]:
            st.download_button("재제출 요청 공문(.docx)", f["data"], f"재제출요청_{c['company_name']}.docx", DOCX, key="doc_resubmit_dl", type="primary")
        st.dataframe([{"항목": k, "상태": v["상태"], "사유": " / ".join(v["사유"])} for k, v in item["items"].items()], hide_index=True, width="stretch")
