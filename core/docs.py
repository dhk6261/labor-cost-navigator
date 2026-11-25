"""재산출 결과로 공문·품의서·분기 보고서 초안을 만든다."""
from __future__ import annotations

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

from .calc import calc_cleaning, calc_payroll, payroll_total
from .compliance import violations
from .data import active_year, load_contracts, load_employees, load_rates, rate_values

KINDS = ["계약 변경 공문", "품의서", "분기 보고서", "착수계", "근로자 설명서", "재제출 요청 공문"]
TEXT_KINDS = KINDS[:3]  # build()로 만드는 문서. 나머지는 제출물을 골라 만든다
TOTAL = "계약 기준금액(천원 미만 절사)"


def won(x: float) -> str:
    return f"{x:,.0f}원"


def context() -> dict:
    r0, r1 = rate_values(2026), rate_values(2027)
    c0, c1 = calc_cleaning(r0), calc_cleaning(r1)
    p0, p1 = calc_payroll(r0), calc_payroll(r1)
    meta = load_rates(2027)
    assumed = [v["name"] for v in meta.values() if isinstance(v, dict) and v["status"] == "가정"]
    pending = [v["name"] for v in meta.values() if isinstance(v, dict) and v["status"] == "잠정"]
    return {
        "r0": r0, "r1": r1, "c0": c0, "c1": c1,
        "clean_before": c0[TOTAL], "clean_after": c1[TOTAL], "clean_diff": c1[TOTAL] - c0[TOTAL],
        "pay_before": payroll_total(p0), "pay_after": payroll_total(p1),
        "pay_diff": payroll_total(p1) - payroll_total(p0),
        "assumed": assumed, "pending": pending, "date": load_contracts()["demo_today"],
    }


def _notice(c: dict) -> str:
    return (f"※ 초안 유의: {', '.join(c['assumed'])}은(는) 공표 전 시연용 가정값이며, "
            f"{', '.join(c['pending'])}은(는) 2027년 고시 전 현행값입니다. 시행 전 확정값으로 재산출하십시오.")


def build(kind: str, births: dict | None = None, params: dict | None = None) -> dict:
    if kind == "분기 보고서":
        return build_report(births, params)
    c = context()
    rate_table = [
        ["구분", "변경 전", "변경 후"],
        ["시중노임단가(일급)", won(c["r0"]["market_daily"]), won(c["r1"]["market_daily"])],
        ["국민연금(사용자)", f"{c['r0']['pension']:.2%}", f"{c['r1']['pension']:.2%}"],
        ["장기요양(건강보험료 대비)", f"{c['r0']['cleaning_ltc']:.2%}", f"{c['r1']['cleaning_ltc']:.2%}"],
        ["청소용역 연간 금액(3인)", won(c["clean_before"]), won(c["clean_after"])],
        ["증감액", "", won(c["clean_diff"])],
    ]
    pay_table = [
        ["구분", "2026년 9월 기준", "2027년 기준 재산출", "증감"],
        ["기간제 월 지급액(9명)", won(c["pay_before"]), won(c["pay_after"]), won(c["pay_diff"])],
    ]
    if kind == "계약 변경 공문":
        body = [
            ("수신", "○○○○ 주식회사 대표이사"), ("제목", "근로자종합복지관 청소용역 계약금액 조정 안내"), ("", ""),
            ("1.", "귀사의 무궁한 발전을 기원합니다."),
            ("2.", f"「공공부문 도급 노동자 보호지침」 5-2(예정가격 등의 산정)에 따라 기준 노임단가 변동분을 노무비에 반영하여 계약금액을 아래와 같이 조정하고자 합니다."),
            ("가.", f"조정 전 금액: {won(c['clean_before'])}"), ("나.", f"조정 후 금액: {won(c['clean_after'])}"),
            ("다.", f"증감액: {won(c['clean_diff'])}"), ("라.", "적용 시기: 2027. 1. 1.(안)"),
            ("3.", "증액된 노무비는 노동자의 임금으로 지급되어야 하며, 변경된 노무비 산출내역을 노동자가 알 수 있도록 공개하여 주시기 바랍니다."),
            ("4.", "분기별 임금지급명세서와 보험료 납입증명서를 제출하여 주시기 바랍니다."),
        ]
        tables = [rate_table]
        found = violations()
        if found:
            body.append(("5.", f"보호지침 점검 결과 위반 {len(found)}건의 내용과 조치는 아래 표와 같습니다."))
            tables.append([["조항", "위반 내용", "근거값", "조치"]] + [[x["조항"], x["점검 내용"], x["근거값"], x["조치"]] for x in found])
    elif kind == "품의서":
        body = [
            ("제목", "2027년 인건비 기준 변경에 따른 계약금액 조정 및 급여 기준 변경 품의"),
            ("1. 목적", "2027년 최저임금·시중노임단가·사회보험 요율 변경을 청소용역 계약과 기간제 급여에 반영하고자 합니다."),
            ("2. 근거", f"공공부문 도급 노동자 보호지침 5-2, 5-5-3, 6-2-2 / 최저임금법"),
            ("3. 주요 내용", f"청소용역 연간 금액을 {won(c['clean_diff'])} 증액하고, 기간제 시급을 {min(e.hourly for e in load_employees()):,}원에서 {c['r1']['min_wage']:,}원으로 조정합니다."),
            ("4. 소요 금액", f"청소용역 연 {won(c['clean_diff'])}, 기간제 월 {won(c['pay_diff'])}(9월 근무실적 기준, 사업주 부담 보험료 별도)"),
            ("5. 행정 사항", "계약상대자 통보, 노무비 산출내역 공개, 분기별 임금 지급 확인"),
        ]
        tables = [rate_table, pay_table]
    else:
        raise ValueError(kind)
    return {"title": kind, "body": body, "tables": tables, "notice": _notice(c), "date": c["date"]}


def build_report(births: dict | None = None, params: dict | None = None) -> dict:
    """이번 분기 보고서: 검증 결과·근태 확인·보호지침·총인건비(참고)."""
    from .anomaly import duplicates, enrich, payslip_check
    from .budget_cap import CapError, evaluate
    from .validate import CHECK, ERROR, pension_summary, run_validation

    e = enrich()
    found = run_validation(active_year(), births=births)
    pension = pension_summary(births)
    found_rules = violations()
    try:
        cap = evaluate()
        cap_text = f"(참고) 2027년 한도 {won(cap['한도'])}, 예상 {won(cap['예상액'])}, 사용률 {cap['사용률']:.1%}. 인상률과 산정 범위는 가정값입니다."
    except CapError:
        cap_text = "(참고) 총인건비 기준 파일을 확인하세요."
    body = [
        ("제목", "2026년 4분기 인건비 산출·관리 보고서"),
        ("1. 검증 결과", f"실제 엑셀에서 오류 {sum(x.severity == ERROR for x in found)}건, 확인 필요 {sum(x.severity == CHECK for x in found)}건을 찾았습니다. 국민연금 판정(가상 생년월일 기준): 대상·공제 누락 {pension['누락']}건, 연령 제외 {pension['제외']}건."),
        ("2. 근태 확인", f"중복 입력 {len(duplicates(e))}건, 분기 임금명세서 미달 {(payslip_check(e)['확인 결과'] == '미달').sum()}명(지침 6-2-2)."),
        ("3. 보호지침", f"위반 {len(found_rules)}건: " + (", ".join(x["조항"] for x in found_rules) or "없음")),
        ("4. 총인건비", cap_text),
    ]
    from .startup import DRAFT, all_cases

    tables = []
    rows = [[x["contract"]["name"], x["company_name"], x["round"], x["status"]] + [str(x["counts"][k]) for k in ("누락", "미달", "과지급", "확인 필요")]
            for x in all_cases() if x["status"] != DRAFT]
    if rows:
        body.append(("5. 착수계 등록", f"등록 {len(rows)}건(등록됨 {sum(r[3] == '등록됨' for r in rows)}, 승인 {sum(r[3] == '승인' for r in rows)}, 보완 요청 {sum(r[3] == '보완 요청' for r in rows)})."))
        tables.append([["계약", "기업", "버전", "상태", "누락", "미달", "과지급", "확인 필요"]] + rows)
    notice = "※ 초안 유의: 근태·생년월일·착수계 등록물·총인건비 기준은 시연용 가상 데이터이며, 국민연금 외 검증 결과와 청소용역·기간제 9월 금액만 실제 자료 기준입니다."
    return {"title": "분기 인건비 산출·관리 보고서", "body": body, "tables": tables, "notice": notice, "date": load_contracts()["demo_today"]}


def build_resubmit(item: dict, values: dict) -> dict:
    """승인된 착수계 산출내역이 새 기준에 미달할 때 업체에 보내는 재제출 요청 공문. item은 workflow.approved_shortfalls()의 한 건."""
    sub, c = item["sub"], item["contract"]
    body = [
        ("수신", f"{sub['vendor']} 대표"), ("제목", f"{c['name']} 인건비 산출내역 재제출 요청"), ("", ""),
        ("1.", "귀사의 무궁한 발전을 기원합니다."),
        ("2.", f"귀사가 제출하여 승인된 산출내역(v{sub['version']}, 승인 {sub.get('approved_at', '')[:10]})이 새로 적용되는 기준(시중노임단가 {values['market_daily']:,}원, 최저임금 {values['min_wage']:,}원 등)에 아래와 같이 미달합니다."),
        ("3.", "「공공부문 도급 노동자 보호지침」 5-2(예정가격 등의 산정)에 따라 노무비를 조정하고자 하니, 새 기준으로 산출내역을 고쳐 새 버전으로 재제출하여 주시기 바랍니다. 승인된 기존 버전은 이력으로 보존됩니다."),
        ("4.", "재등록은 인건비 내비게이터 '착수계 등록·관리' 화면에서 '새 버전 만들기'로 하실 수 있습니다."),
    ]
    table = [["항목", "상태", "사유"]] + [[k, v["상태"], " / ".join(v["사유"])] for k, v in item["items"].items()]
    notice = "※ 초안 유의: 업체·계약·제출물은 시연용 가상 데이터이며, 2027년 시중노임단가는 공표 전 가정값일 수 있습니다."
    return {"title": "재제출 요청 공문", "body": body, "tables": [table], "notice": notice, "date": load_contracts()["demo_today"]}


def to_markdown(doc: dict) -> str:
    blocks = [f"### {doc['title']} (초안)", f"작성일: {doc['date']} · 문서번호: ○○○-0000"]
    blocks += [f"**{a}** {b}" for a, b in doc["body"] if a or b]
    for t in doc["tables"]:
        rows = ["| " + " | ".join(t[0]) + " |", "|" + "---|" * len(t[0])]
        rows += ["| " + " | ".join(row) + " |" for row in t[1:]]
        blocks.append("\n".join(rows))
    blocks.append(f"> {doc['notice']}")
    return "\n\n".join(blocks)


def to_docx(doc: dict) -> bytes:
    d = Document()
    st = d.styles["Normal"]
    st.font.name = "Malgun Gothic"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    h = d.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = h.add_run(f"{doc['title']} (초안)")
    run.bold = True
    run.font.size = Pt(18)
    d.add_paragraph(f"문서번호: ○○○-0000    작성일: {doc['date']}")
    for a, b in doc["body"]:
        if a or b:
            p = d.add_paragraph()
            p.add_run(f"{a} ").bold = True
            p.add_run(b)
    for t in doc["tables"]:
        tb = d.add_table(rows=len(t), cols=len(t[0]))
        tb.style = "Table Grid"
        for i, row in enumerate(t):
            for j, val in enumerate(row):
                tb.cell(i, j).text = val
                if i == 0:
                    tb.cell(i, j).paragraphs[0].runs[0].bold = True
        d.add_paragraph()
    d.add_paragraph(doc["notice"])
    d.add_paragraph("담당 ○○○     팀장 ○○○     부서장 ○○○")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
