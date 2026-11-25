"""최종 산출물 생성(관리자 검수 완료 후에만). 공단 실제 착수계 양식이 없으므로 일반 양식을 가정한다.

착수신고서(Word) · 투입인력 명단(엑셀) · 인건비 산출내역서(엑셀: 표준 산출서, 정정 내역, 산정기준, 검수 기록) · 임금지급 계획(엑셀)
+ 근로자 설명서(Word), 재제출 요청 공문(Word). 모든 함수는 review.require()를 먼저 통과해야 한다.
금액은 모두 계산 엔진·표준표 값을 그대로 쓴다. 실명·주민번호·연락처 칸은 만들지 않는다.
"""
from __future__ import annotations

import io
import zipfile

import openpyxl
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from openpyxl.styles import Alignment, Font, PatternFill

from . import audit, basis, explain, review
from .calc import STANDARD_JOB
from .case import evaluate
from .data import load_contracts, rate_values
from .docs import build_resubmit, to_docx
from .guide import cite
from .standard import BASE_ITEMS, TOTAL, complete

FORM_NOTE = "일반 양식(가정) · 공단 서식 확정 후 교체"
NAMES = {"착수신고서": "착수신고서.docx", "투입인력 명단": "투입인력_명단.xlsx", "인건비 산출내역서": "인건비_산출내역서.xlsx", "임금지급 계획": "임금지급_계획.xlsx"}
HEAD_FILL = PatternFill("solid", fgColor="DCE6F2")
LABOR_PARTS = {"기본급": ["기본급"], "제수당": ["연장근로수당", "휴일근로수당", "연차수당"], "상여금": ["상여금"], "퇴직충당금": ["퇴직충당금"]}
COLS = ["구분", "항목", "업체 금액", "공단 산정 금액", "차이", "산식", "산정기준·근거", "상태", "오류 정정 필요"]


def quarterly(amounts: dict) -> list[dict]:
    """분기별 1인 지급 예정액. 원 단위로 반올림하고 4분기에 끝수를 모아 연간 합계를 맞춘다."""
    out = []
    for part, keys in LABOR_PARTS.items():
        annual = round(sum(amounts.get(k) or 0 for k in keys))
        q = round(annual / 4)
        out.append({"구분": part, "연간": annual, "분기": [q, q, q, annual - 3 * q]})
    return out


def amounts_for(g: dict) -> dict:
    """산출물에 쓰는 금액: 정정이 반영된 업체 금액, 없으면 공단 산정."""
    return {k: (g["company"].get(k) if g["company"] else None) or g["office"][k] for k in BASE_ITEMS}


def _heads(ws, title: str, stamp: str) -> int:
    ws["A1"], ws["A2"] = FORM_NOTE, stamp
    ws["A1"].font, ws["A2"].font = Font(bold=True, color="8A5A00"), Font(bold=True, color="1F4E8C")
    ws["A3"] = title
    ws["A3"].font = Font(bold=True, size=14)
    return 5


def _header(ws, row: int, heads: list[str]) -> None:
    for j, h in enumerate(heads, 1):
        c = ws.cell(row, j, h)
        c.font, c.fill, c.alignment = Font(bold=True), HEAD_FILL, Alignment(horizontal="center", wrap_text=True)


def _xlsx(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _doc() -> Document:
    d = Document()
    st = d.styles["Normal"]
    st.font.name = "Malgun Gothic"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    return d


def startup_report(case: dict, ev: dict, stamp: str) -> bytes:
    d = _doc()
    d.add_paragraph(FORM_NOTE)
    d.add_paragraph().add_run(stamp).bold = True
    h = d.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = h.add_run("착 수 신 고 서")
    run.bold, run.font.size = True, Pt(20)
    c = case["contract"]
    total = sum(complete(amounts_for(g), int(g["inputs"]["headcount"]))[TOTAL] for g in ev["groups"])
    people = sum(int(g["inputs"]["headcount"]) for g in ev["groups"])
    rows = [("계약명", c["name"]), ("계약번호", c["no"]), ("업체명", case["company_name"]), ("계약기간", f"{c['start']} ~ {c['end']}(가정)"),
            ("계약금액", f"{total:,.0f}원(검수 완료 산출 기준금액, 낙찰률 적용 전)"), ("착수일", f"{c['start_date']}"), ("투입 인원", f"{people}명"),
            ("현장 책임 직위", c.get("manager") or "업체 지정"), ("산출 회차", case["round"])]
    t = d.add_table(rows=len(rows), cols=2)
    t.style = "Table Grid"
    for i, (k, v) in enumerate(rows):
        t.cell(i, 0).text, t.cell(i, 1).text = k, v
        t.cell(i, 0).paragraphs[0].runs[0].bold = True
    d.add_paragraph()
    d.add_paragraph("위 용역의 착수를 신고합니다. 투입인력 명단, 인건비 산출내역서, 임금지급 계획을 붙임으로 제출합니다.")
    d.add_paragraph("붙임: 1. 투입인력 명단  2. 인건비 산출내역서  3. 임금지급 계획  각 1부")
    d.add_paragraph(f"{load_contracts()['demo_today']}")
    d.add_paragraph(f"신고인: {case['company_name']} 대표 (인)          발주기관: ○○시설관리공단 이사장 귀하")
    d.add_paragraph("※ 시연용 가상 데이터. 개인정보(실명·주민등록번호·연락처)는 착수계 단계에서 받지 않습니다.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def staff_list(case: dict, ev: dict, stamp: str) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "투입인력 명단"
    row = _heads(ws, f"투입인력 명단 · {case['contract']['name']}", stamp)
    _header(ws, row, ["연번", "표시명", "직종", "근무형태", "월 근무시간", "투입 예정일"])
    n = 0
    for g in ev["groups"]:
        p = g["inputs"]
        for _ in range(int(p["headcount"])):
            n += 1
            for j, v in enumerate([n, f"투입인력{n}", p.get("job", STANDARD_JOB), "전일" if p["monthly_hours"] >= 209 else "단시간", p["monthly_hours"],
                                   str(case["contract"]["start_date"])], 1):
                ws.cell(row + n, j, v)
    ws.cell(row + n + 2, 1, "※ 실명·주민등록번호·연락처는 받지 않습니다(개인정보 최소화). 실제 배치 인원 확인은 업체가 별도 관리합니다.")
    for col, w in zip("ABCDEF", (6, 12, 18, 10, 12, 14)):
        ws.column_dimensions[col].width = w
    return _xlsx(wb)


def cost_sheet(case: dict, ev: dict, stamp: str) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for gi, g in enumerate(ev["groups"]):
        ws = wb.create_sheet(f"산출내역서{gi + 1}"[:31])
        row = _heads(ws, f"인건비 산출내역서(공단 표준 양식) · {case['contract']['name']} · {g['label']} · {case['round']}", stamp)
        _header(ws, row, COLS)
        for i, x in enumerate(g["rows"], row + 1):
            for j, k in enumerate(COLS, 1):
                v = x[k]
                cell = ws.cell(i, j, round(v) if isinstance(v, float) else v)
                if k in ("업체 금액", "공단 산정 금액", "차이"):
                    cell.number_format = "#,##0"
                if x["소계"]:
                    cell.font = Font(bold=True)
        for col, w in zip("ABCDEFGHI", (10, 26, 16, 16, 12, 40, 50, 9, 18)):
            ws.column_dimensions[col].width = w
    s = wb.create_sheet("정정 내역")
    _header(s, 1, ["항목", "처리", "고친 값", "사유", "처리자", "시각"])
    for i, (k, c) in enumerate((case.get("corrections") or {}).items(), 2):
        for j, v in enumerate([k.split(":", 1)[1], c["처리"], c.get("값"), c.get("사유"), c["by"], c["at"]], 1):
            s.cell(i, j, v)
    s = wb.create_sheet("산정기준")
    _header(s, 1, ["번호", "기준", "값", "근거·공표일"])
    for i, x in enumerate(basis.panel(ev["year"]), 2):
        for j, k in enumerate(("번호", "기준", "값", "근거·공표일"), 1):
            s.cell(i, j, x[k])
    s.column_dimensions["B"].width, s.column_dimensions["C"].width, s.column_dimensions["D"].width = 30, 30, 70
    s = wb.create_sheet("검수 기록")
    rv = case["review"]
    for i, (k, v) in enumerate([("검수자", rv["by"]), ("검수 시각", rv["at"]), ("기준 버전", rv["basis"]), ("정정 요약", rv["summary"])]
                               + [(f"체크 {n + 1}", f"☑ {c}") for n, c in enumerate(rv["checks"])], 1):
        s.cell(i, 1, k).font = Font(bold=True)
        s.cell(i, 2, v)
    s.column_dimensions["A"].width, s.column_dimensions["B"].width = 14, 70
    return _xlsx(wb)


def pay_plan(case: dict, ev: dict, stamp: str) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "임금지급 계획"
    row = _heads(ws, f"분기별 임금지급 계획(1인) · {case['contract']['name']}", stamp)
    ws.cell(row - 1, 1, "근거: " + cite("6-2-2"))
    _header(ws, row, ["분기", "구분", "산정액(지급 예정)", "실제 지급액(업체 기재)", "산정액 이상 여부", "직종"])
    r = row + 1
    total = 0
    for g in ev["groups"]:
        plan = quarterly(amounts_for(g))
        total += sum(p["연간"] for p in plan)
        for q in range(4):
            for part in plan:
                ws.cell(r, 1, f"{q + 1}분기")
                ws.cell(r, 2, part["구분"])
                ws.cell(r, 3, part["분기"][q]).number_format = "#,##0"
                ws.cell(r, 5, f'=IF(D{r}="","",IF(D{r}>=C{r},"이상","미달"))')
                ws.cell(r, 6, g["label"])
                r += 1
    ws.cell(r, 2, "연간 합계").font = Font(bold=True)
    ws.cell(r, 3, total).number_format = "#,##0"
    ws.cell(r + 2, 1, "※ 업체는 분기마다 D열에 실제 지급액을 적고 임금지급명세서·보험료 납입증명서와 함께 제출합니다. 미달이면 차액 지급을 확인합니다.")
    for col, w in zip("ABCDEF", (8, 12, 18, 22, 16, 24)):
        ws.column_dimensions[col].width = w
    return _xlsx(wb)


def _log(user, case: dict, text: str) -> None:
    audit.log("착수계 생성" if "4종" in text else "문서 생성", text, user=user, company=case["company_name"], round_=case["round"])


def build_all(user: dict, case: dict) -> dict:
    """{서류명: bytes, 'zip': bytes}. 관리자 검수 완료 후에만 만든다."""
    review.require(user, case, "착수계 4종")
    ev = evaluate(case)
    stamp = review.stamp(case)
    files = {"착수신고서": startup_report(case, ev, stamp), "투입인력 명단": staff_list(case, ev, stamp),
             "인건비 산출내역서": cost_sheet(case, ev, stamp), "임금지급 계획": pay_plan(case, ev, stamp)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, data in files.items():
            z.writestr(NAMES[k], data)
    _log(user, case, f"{case['company_name']} {case['round']}, 서류 4종, 검수자 {case['review']['by']}")
    return {**files, "zip": buf.getvalue()}


def build_cost_sheet(user: dict, case: dict) -> bytes:
    review.require(user, case, "인건비 산출내역서")
    data = cost_sheet(case, evaluate(case), review.stamp(case))
    _log(user, case, f"인건비 산출내역서({case['company_name']} {case['round']}), 검수자 {case['review']['by']}")
    return data


def worker_doc(user: dict, case: dict, gi: int = 0) -> bytes:
    """근로자용 산출근거 설명서(A4 한 장). 검수 완료 후에만."""
    review.require(user, case, "근로자 설명서")
    ev = evaluate(case)
    g = ev["groups"][gi]
    p = g["inputs"]
    info = {"계약": case["contract"]["name"], "직종": p.get("job", STANDARD_JOB), "근무형태": "전일" if p["monthly_hours"] >= 209 else "단시간",
            "월 근무시간": f"{p['monthly_hours']:g}", "inputs": p, "notice": f"시연용 가상 데이터 · 실명 없이 직종·근무형태 기준 · {review.stamp(case)}"}
    data = explain.worker_docx(amounts_for(g), rate_values(ev["year"]), info)
    _log(user, case, f"근로자 설명서({case['company_name']} {case['round']})")
    return data


def resubmit_doc(user: dict, case: dict, items: dict, values: dict) -> bytes:
    """승인된 착수계가 새 기준에 미달할 때 재제출 요청 공문. 재검수 완료 후에만."""
    review.require(user, case, "재제출 요청 공문")
    doc = build_resubmit({"sub": {"vendor": case["company_name"], "version": case["version"], "approved_at": case.get("approved_at", "")},
                          "contract": case["contract"], "items": items}, values)
    doc["notice"] += f" · {review.stamp(case)}"
    _log(user, case, f"재제출 요청 공문({case['company_name']} {case['round']})")
    return to_docx(doc)
