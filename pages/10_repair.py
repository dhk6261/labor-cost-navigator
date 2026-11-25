from pathlib import PurePath

import pandas as pd
import streamlit as st

from core import auth, audit, ui
from core.data import source_file
from core.repair import RepairError, analyze, build_fixed, demo_error_file
from core.validate import CHECK, ERROR, INFO

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STYLE = {ERROR: ui.RED, CHECK: ui.AMBER}
SAMPLES = {"직접 첨부": None, "샘플: 청소용역 산출내역": "청소용역", "샘플: 기간제 급여": "기간제", "샘플: 오류 주입 급여(시연용)": "demo"}

user = ui.guard(auth.ADMIN)
ui.page("엑셀 점검 · 수정본", "엑셀을 첨부하면 문제 위치와 이유를 설명하고, 고칠 항목을 골라 수정본을 내려받습니다.")
st.caption("첨부 파일은 서버에 저장하지 않고 이 화면에서만 처리합니다. 첨부한 원본은 바뀌지 않습니다.")

choice = st.segmented_control("자료 선택", list(SAMPLES), default="직접 첨부", key="repair_source") or "직접 첨부"
raw, filename = None, None
if SAMPLES[choice] is None:
    uploaded = st.file_uploader("Excel 파일(.xlsx, 10MB 이하)", type=["xlsx"], key="repair_file")
    if uploaded:
        raw, filename = uploaded.getvalue(), uploaded.name
elif SAMPLES[choice] == "demo":
    raw, filename = demo_error_file(), "기간제_오류주입_시연용.xlsx"
    st.warning("원본 사본에 오류 3건(AD9, U10, Y13)을 넣은 시연용 파일입니다.", icon=":material/science:")
else:
    path = source_file(SAMPLES[choice])
    raw, filename = path.read_bytes(), path.name

if raw is None:
    st.info("급여대장과 용역 산출내역은 항목별로 정밀 검사하고, 그 밖의 표는 수식 오류와 수식 불일치를 검사합니다.")
    st.stop()

births = ui.current_births()
cache_key = ((filename, hash(raw)) if SAMPLES[choice] != "demo" else ("demo",)) + (tuple(sorted(births.items())),)
if st.session_state.get("repair_key") != cache_key:
    try:
        report = analyze(raw, filename, births)
    except RepairError as e:
        st.session_state.pop("repair_key", None)
        st.error(str(e))
        st.stop()
    st.session_state["repair_key"], st.session_state["repair_report"] = cache_key, report
    st.session_state["repair_raw"] = raw
    st.session_state.pop("repair_table", None)
    audit.log("엑셀 점검", f"파일 {report.digest}: 오류 {report.count(ERROR)}, 확인 필요 {report.count(CHECK)}, 자동 수정 가능 {len(report.fixable)}")
report = st.session_state["repair_report"]
raw = st.session_state["repair_raw"]

m = st.columns(4)
m[0].metric("오류", report.count(ERROR))
m[1].metric("확인 필요", report.count(CHECK))
m[2].metric("참고", report.count(INFO))
m[3].metric("자동 수정 가능", f"{len(report.fixable)}건")
st.caption("인식 결과: " + " / ".join(f"{k}: {v}" for k, v in report.sheets.items()))
for w in report.warnings:
    st.warning(w, icon=":material/warning:")
if not report.items:
    st.success("검사 규칙에서 발견된 문제가 없습니다.")
    st.stop()



def place(x) -> str:
    """시트가 하나면 셀 주소만 보여 준다."""
    return x.cell if len(report.sheets) == 1 else f"{x.sheet}!{x.cell}"


selected: set[str] = set()
if report.fixable:
    st.subheader("자동으로 고칠 수 있는 항목")
    st.caption("수정본에 반영할 항목만 체크하세요. **금액 변경** 표시 항목은 합계나 계약금액이 달라질 수 있습니다.")
    table = pd.DataFrame([{"적용": True, "심각도": x.severity, "위치": place(x), "대상": x.target, "금액 변경": "예" if x.changes_amount else "-",
                           "수정 내용": x.action, "id": x.id} for x in report.fixable])
    edited = st.data_editor(table, hide_index=True, width="stretch", key="repair_table", disabled=[c for c in table.columns if c != "적용"],
                            column_config={"id": None, "적용": st.column_config.CheckboxColumn(width="small"),
                                           "심각도": st.column_config.TextColumn(width="small"), "금액 변경": st.column_config.TextColumn(width="small"),
                                           "수정 내용": st.column_config.TextColumn(width="large")})
    selected = set(edited.loc[edited["적용"], "id"])
    with st.expander("왜 문제인지, 수정 전후 자세히 보기", expanded=True):
        detail = pd.DataFrame([{"위치": place(x), "왜 문제인가": x.problem, "근거": x.basis,
                                "수정 전": "\n".join("(공란)" if e.before is None else str(e.before) for e in x.edits),
                                "수정 후": "\n".join(str(e.after) for e in x.edits)} for x in report.fixable])
        st.table(detail.style.hide(axis="index"))

if report.manual:
    st.subheader("담당자 확인이 필요한 항목")
    st.caption("판단이 필요한 값은 임의로 채우지 않습니다. 수정본에 색과 메모로 표시합니다.")
    groups: dict[tuple, list] = {}
    for x in report.manual:
        groups.setdefault((x.severity, x.category, x.problem, x.basis, x.action), []).append(x)
    manual = pd.DataFrame([{"심각도": k[0], "위치": ", ".join(place(x) for x in v), "대상": ", ".join(dict.fromkeys(x.target for x in v)),
                            "왜 문제인가": k[2], "근거": k[3], "권장 조치": k[4]} for k, v in groups.items()])
    st.table(manual.style.map(lambda s: STYLE.get(s, "") + ";white-space:nowrap" if s in STYLE else "", subset=["심각도"]).hide(axis="index"))

st.subheader("수정본 내려받기")
mark = st.checkbox("수정한 칸은 초록색, 확인할 칸은 빨강·노랑과 메모로 표시", value=True, key="repair_mark")
fixed, applied = build_fixed(raw, report, selected, mark)
stem = PurePath(filename).stem


def on_download(count: int, digest: str) -> None:
    audit.log("수정본 생성", f"파일 {digest}: {count}건 반영")


st.download_button(f"수정본 내려받기 ({applied}건 반영)", fixed, f"{stem}_수정본.xlsx", XLSX, type="primary", key="repair_download",
                   on_click=on_download, args=(applied, report.digest))
st.caption("수정본 마지막의 ‘검토결과’ 시트에 모든 항목의 수정 전후가 기록됩니다. 금액은 Excel에서 파일을 열 때 자동으로 다시 계산됩니다.")
