"""근로자·담당자용 설명: 용어 해설, '이 금액이 나온 이유', 근로자용 산출근거 설명서(Word 1쪽).

숫자는 모두 계산 결과(core/calc.py)나 제출 금액에서 가져온다. 실명은 쓰지 않는다.
"""
from __future__ import annotations

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from .calc import standard_inputs, worker_monthly
from .standard import BASE_ITEMS, complete, pct

GLOSSARY = {
    "기본급": "한 달 동안 정해진 시간을 일하고 받는 기본 월급입니다. 쉬는 날(주휴일) 몫도 들어 있습니다.",
    "주휴수당": "일주일에 15시간 이상 일하면, 쉬는 날 하루도 일한 것처럼 돈을 주는 제도입니다.",
    "209시간": "주 40시간에 쉬는 날 하루치(8시간)를 더한 48시간을 한 달(약 4.345주)로 바꾼 시간입니다.",
    "통상임금": "정해진 일을 하면 매달 똑같이 받는 돈입니다. 연장·휴일 수당을 계산하는 기준이 됩니다.",
    "연장근로수당": "하루 8시간이나 주 40시간보다 더 일한 시간에 대해 시급의 1.5배를 받는 돈입니다.",
    "휴일근로수당": "쉬는 날 일한 시간에 대해 받는 돈입니다. 8시간까지는 1.5배, 넘는 시간은 2배입니다.",
    "연장·휴일 가산": "정해진 시간보다 더 일하거나 쉬는 날 일하면 시급에 50%(또는 100%)를 더 얹어 줍니다.",
    "연차수당": "1년에 주어지는 유급 휴가(연차)를 쓰지 못했을 때 그 날수만큼 돈으로 받는 것입니다.",
    "상여금": "기본급과 별도로 1년에 정해진 횟수만큼 나누어 받는 보너스입니다.",
    "퇴직충당금": "나중에 퇴직금을 줄 수 있도록 매달 조금씩 모아 두는 돈입니다(1년 이상 일하면 받습니다).",
    "산재보험": "일하다 다치거나 아플 때 치료비와 생활비를 주는 보험입니다. 보험료는 회사가 모두 냅니다.",
    "국민연금": "나이 들어 일을 그만둔 뒤 매달 연금을 받기 위해 내는 보험료입니다. 회사와 근로자가 반씩 냅니다.",
    "건강보험": "병원비 부담을 줄여 주는 보험입니다. 회사와 근로자가 반씩 냅니다.",
    "장기요양": "나이 들거나 아파서 돌봄이 필요할 때를 위한 보험료로, 건강보험료에 일정 비율을 곱해 냅니다.",
    "고용보험": "일자리를 잃었을 때 실업급여를 받을 수 있게 해 주는 보험입니다.",
    "임금채권보장": "회사가 망해 월급을 못 줄 때 나라가 대신 주는 제도에 회사가 내는 돈입니다.",
    "피복비": "일할 때 입는 근무복을 사는 데 드는 돈입니다.",
    "작업화": "일할 때 신는 작업용 신발(안전화)을 사는 데 드는 돈입니다.",
    "일반관리비": "용역 회사가 사무실·관리 인력 등을 운영하는 데 드는 비용으로, 원가의 9% 이하로 정합니다.",
    "이윤": "용역 회사가 얻는 이익으로, 법에서 정한 10% 이하로 계산합니다.",
    "부가가치세": "물건이나 서비스 값에 붙는 세금으로, 공급가액의 10%입니다.",
    "낙찰률": "입찰에서 정해진 예정가격 대비 실제 계약 금액의 비율입니다. 청소·경비는 89.995% 이상이어야 합니다.",
    "시중노임단가": "정부 조사로 정한 직종별 하루 임금입니다. 단순노무 용역은 최저임금이 아니라 이 금액을 기준으로 합니다.",
    "최저임금": "법으로 정한, 1시간에 최소한 받아야 하는 돈입니다. 이보다 적게 주면 안 됩니다.",
    "원천징수 3.3%": "프리랜서에게 돈을 줄 때 소득세 3%와 지방소득세 0.3%를 미리 떼어 나라에 대신 내는 것입니다.",
}
TERM = {"일반관리비(9%)": "일반관리비", "이윤(10%)": "이윤"}


def term(item: str) -> str:
    return GLOSSARY.get(TERM.get(item, item), "")


def num(x: float, digits: int = 0) -> str:
    if digits:
        return f"{x:,.{digits}f}".rstrip("0").rstrip(".")
    return f"{x:,.0f}"


def why(item: str, result: dict, inputs: dict | None, r: dict) -> str:
    """항목별 '이 금액이 나온 이유'. result는 계산 결과 또는 업체 금액(소계가 없으면 만든다)."""
    p = standard_inputs(**(inputs or {}))
    x = complete({k: v for k, v in result.items() if v is not None}, int(p["headcount"]))
    months, hours = p["months"], p["monthly_hours"]
    amount = x.get(item) or 0
    base = x.get("기본급") or 0
    daily = base / (hours * months) * 8 if base else (p["daily"] or r["market_daily"])
    hourly = daily / 8
    wage = x["임금 소계"]
    if not amount:
        return f"{item}: 제출된 금액이 없습니다. " + ("필수 항목이므로 누락입니다." if item in BASE_ITEMS[:12] else "")
    texts = {
        "기본급": f"기본급(월) {num(base / months)}원 = 시급 {num(hourly, 3)}원(일급 {num(daily)}원 ÷ 8) × {num(hours, 2)}시간. "
                 f"209시간은 주 40시간에 쉬는 날 하루치(주휴 8시간)를 더해 한 달로 바꾼 시간입니다. 1년치는 × {months}월 = {num(amount)}원.",
        "연장근로수당": f"연장근로수당(연) {num(amount)}원 ≈ 시급 {num(hourly, 3)}원 × 1.5배 × 연 {num(amount / (hourly * 1.5), 2)}시간. 정해진 시간보다 더 일한 시간에 50%를 더 줍니다.",
        "휴일근로수당": f"휴일근로수당(연) {num(amount)}원: 쉬는 날 8시간까지는 시급 {num(hourly, 3)}원의 1.5배, 넘는 시간은 2배로 계산했습니다.",
        "연차수당": f"연차수당(연) {num(amount)}원 = 일급 {num(daily)}원 × {num(amount / daily, 2)}일. 쓰지 못한 연차 휴가를 돈으로 받는 것입니다.",
        "상여금": f"상여금(연) {num(amount)}원 = 기본급(연) {num(base)}원 ÷ 12. 한 달 기본급만큼을 1년에 나누어 받습니다.",
        "퇴직충당금": f"퇴직충당금(연) {num(amount)}원 = 임금 소계 {num(wage)}원 ÷ 12. 1년에 한 달치 임금을 퇴직금으로 모아 둡니다.",
        "산재보험": f"산재보험(연) {num(amount)}원 = 임금 소계 {num(wage)}원 × {pct(amount / wage)}. 회사가 모두 냅니다.",
        "국민연금": f"국민연금 회사 부담(연) {num(amount)}원 = 임금 소계 {num(wage)}원 × {pct(amount / wage)}. 근로자도 같은 비율을 냅니다.",
        "건강보험": f"건강보험 회사 부담(연) {num(amount)}원 = 임금 소계 {num(wage)}원 × {pct(amount / wage)}. 근로자도 같은 비율을 냅니다.",
        "장기요양": f"장기요양(연) {num(amount)}원 = 건강보험료 {num(x.get('건강보험') or 0)}원 × {pct(amount / (x.get('건강보험') or amount))}.",
        "고용보험": f"고용보험 회사 부담(연) {num(amount)}원 = 임금 소계 {num(wage)}원 × {pct(amount / wage)}.",
        "임금채권보장": f"임금채권보장(연) {num(amount)}원 = 임금 소계 {num(wage)}원 × {pct(amount / wage)}. 회사만 냅니다.",
        "피복비": f"피복비(연) {num(amount)}원 = 월 {num(amount / months)}원 × {months}월. 근무복 구입비입니다.",
        "작업화": f"작업화(연) {num(amount)}원 = 월 {num(amount / months)}원 × {months}월. 작업용 신발 구입비입니다.",
        "일반관리비(9%)": f"일반관리비(연) {num(amount)}원 = 합계(원가) {num(x['합계(원가)'])}원 × {pct(amount / x['합계(원가)'])}. 회사 운영비이며 9% 이하로 정합니다.",
        "이윤(10%)": f"이윤(연) {num(amount)}원 = (합계 + 일반관리비) {num(x['합계(원가)'] + (x.get('일반관리비(9%)') or 0))}원 × 10% 이하.",
        "부가가치세": f"부가가치세(연) {num(amount)}원 = 공급가액 {num(x['공급가액'])}원 × 10%.",
    }
    return texts.get(item, f"{item} {num(amount)}원")


# ───────────── 근로자용 산출근거 설명서 ─────────────
PAY_NOTE = {"기본급": "정해진 시간(월 209시간, 주휴 포함) 근무의 기본 월급", "연장근로수당": "더 일한 시간 × 시급 × 1.5배",
            "휴일근로수당": "쉬는 날 일한 시간 × 1.5배(8시간 초과 2배)", "연차수당(월 환산)": "못 쓴 연차를 돈으로(연간 금액 ÷ 12)",
            "상여금(월 환산)": "한 달 기본급을 1년에 나누어(÷ 12)"}
DEDUCT_NOTE = {"국민연금": "노후 연금, 회사와 반씩 부담", "건강보험": "병원비 보험, 회사와 반씩 부담",
               "장기요양": "건강보험료 × 법정 비율", "고용보험": "실업급여 보험"}
MAX_TABLES, MAX_PARAGRAPHS = 4, 14   # 1쪽 분량 상한(테스트에서 확인)


def worker_sheet(x: dict, r: dict, info: dict) -> dict:
    """설명서 내용(문서와 화면이 함께 쓴다). info: 계약, 직종, 근무형태, 월 근무시간."""
    p = standard_inputs(**info.get("inputs", {}))
    m = worker_monthly(x, r, p["months"])
    daily = x["기본급"] / (p["monthly_hours"] * p["months"]) * 8
    checks = [("시중노임단가 이상", daily >= r["market_daily"] - 0.5, f"일급 {num(daily)}원 / 기준 {r['market_daily']:,}원"),
              ("최저임금 이상", daily / 8 >= r["min_wage"], f"시급 {num(daily / 8)}원 / 최저임금 {r['min_wage']:,}원")]
    return {"monthly": m, "checks": checks, "daily": daily, "info": info}


def worker_docx(x: dict, r: dict, info: dict) -> bytes:
    s = worker_sheet(x, r, info)
    m = s["monthly"]
    d = Document()
    sec = d.sections[0]
    sec.top_margin = sec.bottom_margin = Cm(1.4)
    sec.left_margin = sec.right_margin = Cm(1.6)
    st = d.styles["Normal"]
    st.font.name = "Malgun Gothic"
    st.font.size = Pt(9)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    st.paragraph_format.space_after = Pt(2)

    def para(text: str, bold: bool = False, size: float | None = None, center: bool = False):
        p = d.add_paragraph()
        run = p.add_run(text)
        run.bold = bold
        if size:
            run.font.size = Pt(size)
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        return p

    def table(rows: list[list[str]], widths: list[float]):
        t = d.add_table(rows=len(rows), cols=len(rows[0]))
        t.style = "Table Grid"
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                cell = t.cell(i, j)
                cell.width = Cm(widths[j])
                cell.text = val
                if i == 0:
                    cell.paragraphs[0].runs[0].bold = True
        return t

    para("근로자용 인건비 산출근거 설명서", bold=True, size=14, center=True)
    para(f"{info.get('notice', '시연용 가상 데이터 · 실명 없이 직종·근무형태 기준으로 작성')}", center=True)
    table([["계약", info["계약"], "직종", info["직종"]], ["근무형태", info["근무형태"], "월 근무시간", f"{info['월 근무시간']}시간(주휴 포함)"]], [2.2, 6.5, 2.2, 6.5])
    para("1. 받는 돈(1인·월 기준)", bold=True)
    table([["항목", "금액", "이 금액이 나온 이유"]] + [[k, f"{num(v)}원", PAY_NOTE[k]] for k, v in m["pay"].items()]
          + [["합계(세전)", f"{num(m['월 임금'])}원", "위 항목의 합"]], [3.6, 3.0, 10.8])
    para(f"※ 퇴직충당금 월 {num(m['퇴직충당금(월 적립)'])}원은 회사가 따로 모아 두었다가 1년 이상 일하고 퇴직할 때 퇴직금으로 지급합니다.")
    para("2. 빠지는 돈(근로자 부담)", bold=True)
    table([["항목", "금액(월)", "이유"]] + [[k, f"{num(v)}원", f"{DEDUCT_NOTE[k]} ({pct(r['ltc']) if k == '장기요양' else pct(r[{'국민연금': 'pension', '건강보험': 'health', '고용보험': 'employment_worker'}[k]])})"]
                                         for k, v in m["deduct"].items()]
          + [["소득세·지방소득세", "개인별 상이", "국세청 간이세액표에 따라 회사가 떼어 대신 냅니다(가족 수 등에 따라 다름)"]], [3.6, 3.0, 10.8])
    para("3. 기준 이상인지 확인", bold=True)
    for name, ok, detail in s["checks"]:
        para(f"{'✔' if ok else '✘'} {name}: {'예' if ok else '아니오(확인 필요)'} · {detail}")
    para("4. 문의처: 소속 업체 담당자 ____________ / 발주기관(공단) 담당 부서 ____________", bold=True)
    para("※ 금액은 산출내역서(계약 기준) 값이며, 실제 지급액은 근무 실적에 따라 달라질 수 있습니다. 분기별 임금지급명세서로 확인합니다(보호지침 6-2-2).")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
