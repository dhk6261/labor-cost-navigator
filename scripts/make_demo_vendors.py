"""시연용 가상 업체 산출내역 2건을 data/demo_vendors/에 만든다. 원본 엑셀(data/source/)은 건드리지 않는다.

금액은 계산 엔진(core/calc.py, 2026 기준값)에서 만들고, 양식·항목명·열 위치를 업체마다 다르게 한다.
- 가상업체A: 항목명만 다르고 내용은 공단 기준 충족(승인 가능한 제출물): 법정 장기요양 요율, 임금채권보장 포함
- 가상업체B: 항목 B열·금액 E열, 비목 묶음 머리글, 기본급을 옛 일급 90,085원으로 계산, 연차수당 누락, 피복비 두 번 계상(과지급), '작업용품', '성명' 열
- 가상업체C: 텍스트 PDF 한 장(관리자 단독 시연용, 계정 없는 업체). 정상 항목 위주에 일반관리비 10%(상한 9% 초과, 과지급) 1건
가상업체A 파일은 승인 가능한 자료로 확정되어 있으므로, 이미 있으면 다시 만들지 않는다(내용 보존).
실행: .venv\\Scripts\\python.exe scripts\\make_demo_vendors.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.calc import calc_standard  # noqa: E402
from core.data import DATA, rate_values  # noqa: E402

OUT = DATA / "demo_vendors"
OLD_DAILY = 90085  # 2024년 6월 노임단가(원본 산출내역 F7의 옛 표기)
NOTE = "※ 시연용 가상 데이터 (실제 업체 자료 아님)"


def rebuild(items: dict, r: dict, ltc: float) -> dict:
    """업체가 자기 금액으로 아래 항목을 다시 계산한 것처럼 만든다(원 단위 반올림)."""
    wage_keys = [k for k in ("기본급", "연장근로수당", "휴일근로수당", "연차수당", "상여금") if k in items]
    out = {k: round(items[k]) for k in wage_keys}
    wage = sum(items[k] for k in wage_keys)
    out["퇴직충당금"] = round(wage / 12)
    out["산재보험"] = math.floor(wage * r["industrial"])
    out["국민연금"] = math.floor(wage * r["pension"])
    out["건강보험"] = math.floor(wage * r["health"])
    out["장기요양"] = math.floor(out["건강보험"] * ltc)
    out["고용보험"] = math.floor(wage * r["employment_employer"])
    out["임금채권보장"] = math.floor(wage * r["wage_claim"])
    out["피복비"], out["작업화"] = 9500 * 12, 4200 * 12
    return out


def finish(x: dict, drop: set[str], extra_uniform: bool = False, overhead: float = 0.09) -> dict:
    for k in drop:
        x.pop(k, None)
    labor = sum(x.get(k, 0) for k in ("기본급", "연장근로수당", "휴일근로수당", "연차수당", "상여금", "퇴직충당금"))
    legal = sum(x.get(k, 0) for k in ("산재보험", "국민연금", "건강보험", "장기요양", "고용보험", "임금채권보장"))
    cost = labor + legal + x["피복비"] * (2 if extra_uniform else 1) + x["작업화"]
    x["일반관리비"] = round(cost * overhead)
    x["이윤"] = round((cost + x["일반관리비"]) * 0.10)
    supply = cost + x["일반관리비"] + x["이윤"]
    x["부가가치세"] = round(supply * 0.10)
    x["_소계"] = {"인건비": labor, "4대보험": legal, "원가": cost, "공급가액": supply, "총계": supply + x["부가가치세"]}
    return x


def vendor_a(r: dict) -> openpyxl.Workbook:
    x = finish(rebuild(calc_standard({}, r), r, ltc=r["ltc"]), drop=set())
    names = [("인건비", "기본급여", "기본급", "시중노임단가 95,767원/8×209h×12월"), ("", "시간외수당", "연장근로수당", "시급×150%×연 94.67h"),
             ("", "휴일수당", "휴일근로수당", "시급×150%/200%"), ("", "연차휴가수당", "연차수당", "일급×11일"), ("", "정기상여", "상여금", "기본급÷12"),
             ("", "퇴직적립금", "퇴직충당금", "임금÷12"), ("", "소계", "_인건비", ""),
             ("4대보험", "산재보험료", "산재보험", "임금×0.86%"), ("", "국민연금(사업주)", "국민연금", "임금×4.75%"), ("", "건강보험료", "건강보험", "임금×3.595%"),
             ("", "노인장기요양보험", "장기요양", "건강보험료×13.14%"), ("", "고용보험료", "고용보험", "임금×1.75%"),
             ("", "임금채권보장보험료", "임금채권보장", "임금×0.09%"), ("", "소계", "_4대보험", ""),
             ("경비", "피복비", "피복비", "9,500원×12월"), ("", "안전화", "작업화", "4,200원×12월"), ("", "합계", "_원가", ""),
             ("", "일반관리비", "일반관리비", "합계×9%"), ("", "기업이윤", "이윤", "(합계+관리비)×10%"), ("", "공급가액", "_공급가액", ""),
             ("", "부가가치세", "부가가치세", "공급가액×10%"), ("", "총계(1인)", "_총계", "")]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "산출내역(가상업체A)"
    ws["A1"] = f"{NOTE} 가상업체A 근로자종합복지관 청소용역 산출내역"
    ws["A1"].font = Font(bold=True, color="B42318")
    for j, h in enumerate(["구분", "항목", "산출근거", "금액(1인·연간, 원)", "비고"], 1):
        ws.cell(3, j, h).font = Font(bold=True)
    for i, (group, label, key, basis) in enumerate(names, 4):
        value = x["_소계"][key[1:]] if key.startswith("_") else x[key]
        ws.cell(i, 1, group)
        ws.cell(i, 2, label)
        ws.cell(i, 3, basis)
        ws.cell(i, 4, value).number_format = "#,##0"
    for col, w in zip("ABCDE", (10, 18, 30, 20, 16)):
        ws.column_dimensions[col].width = w
    return wb


def vendor_b(r: dict) -> openpyxl.Workbook:
    base = calc_standard({"daily": OLD_DAILY}, r)
    base.pop("연차수당")
    x = finish(rebuild(base, r, ltc=r["cleaning_ltc"]), drop=set(), extra_uniform=True)
    rows = [("Ⅰ. 노무비", None, None, None), (None, "기본급", "90,085원/8×209시간×12월", "기본급"), (None, "연장근로수당", "시급×1.5×연 94.67시간", "연장근로수당"),
            (None, "휴일근로수당", "시급×1.5×16h + 시급×2×2h", "휴일근로수당"), (None, "상여금", "기본급의 100%", "상여금"), (None, "퇴직급여충당금", "노무비÷12", "퇴직충당금"),
            ("Ⅱ. 법정부담금", None, None, None), (None, "산재보험료", "임금×0.86%", "산재보험"), (None, "국민연금", "임금×4.75%", "국민연금"),
            (None, "건강보험료", "임금×3.595%", "건강보험"), (None, "장기요양보험료", "건강보험료×12.95%", "장기요양"), (None, "고용보험료", "임금×1.75%", "고용보험"),
            (None, "임금채권보장보험료", "임금×0.09%", "임금채권보장"),
            ("Ⅲ. 경비", None, None, None), (None, "피복비", "연 2착", "피복비"), (None, "피복비(추가 계상)", "하계 근무복", "피복비"),
            (None, "작업용품", "연 2회", "작업화"),
            (None, "일반관리비", "원가×9%", "일반관리비"), (None, "이윤", "(원가+관리비)×10%", "이윤"), (None, "부가가치세", "10%", "부가가치세"),
            ("합  계", None, None, "_총계")]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "인건비산출(B)"
    ws["A1"] = f"{NOTE} 가상업체B 인건비 산출내역서"
    ws["A1"].font = Font(bold=True, color="B42318")
    ws["A2"] = "계약: 가상 시설 청소용역(시연용) · 단위: 원(1인·연간)"
    heads = ["비목", "세부 내역", "산출 근거", "성명", "금액(원)"]
    for j, h in enumerate(heads, 1):
        ws.cell(4, j, h).font = Font(bold=True)
    fill = PatternFill("solid", fgColor="EEF3FA")
    for i, (group, label, basis, key) in enumerate(rows, 5):
        if group:
            ws.cell(i, 1, group).font = Font(bold=True)
            for j in range(1, 6):
                ws.cell(i, j).fill = fill
        if label:
            ws.cell(i, 2, label)
            ws.cell(i, 3, basis)
        if key:
            ws.cell(i, 5, x["_소계"]["총계"] if key == "_총계" else x[key]).number_format = "#,##0"
    for i, n in ((6, "가상인물1"), (7, "가상인물2"), (8, "가상인물3")):  # 개인정보 열 버림 확인용(가상 이름)
        ws.cell(i, 4, n)
    for col, w in zip("ABCDE", (16, 18, 26, 12, 16)):
        ws.column_dimensions[col].width = w
    return wb


def vendor_c(r: dict, path: Path) -> None:
    """텍스트 PDF 한 장. 2명, 일반관리비만 10%(상한 9% 초과)."""
    from scripts.textpdf import write_pdf
    x = finish(rebuild(calc_standard({"headcount": 2}, r), r, ltc=r["ltc"]), drop=set(), overhead=0.10)
    names = [("기본급", "기본급"), ("연장근로수당", "연장근로수당"), ("휴일근로수당", "휴일근로수당"), ("연차수당", "연차수당"), ("상여금", "상여금"),
             ("퇴직충당금", "퇴직충당금"), ("산재보험료", "산재보험"), ("국민연금", "국민연금"), ("건강보험료", "건강보험"), ("장기요양보험료", "장기요양"),
             ("고용보험료", "고용보험"), ("임금채권보장보험료", "임금채권보장"), ("피복비", "피복비"), ("작업화", "작업화"), ("일반관리비", "일반관리비"),
             ("이윤", "이윤"), ("부가가치세", "부가가치세")]
    basis = {"기본급": "95,767원/8×209시간×12월", "일반관리비": "원가×10%", "이윤": "(원가+관리비)×10%", "부가가치세": "공급가액×10%",
             "산재보험료": "임금×0.86%", "국민연금": "임금×4.75%", "건강보험료": "임금×3.595%", "장기요양보험료": "건강보험료×13.14%",
             "고용보험료": "임금×1.75%", "임금채권보장보험료": "임금×0.09%"}
    lines = [f"{NOTE} 가상업체C 인건비 산출내역", "계약명: 가상 시설 청소용역(관리자 단독 시연)", "인원: 2명 · 직종: 청소원(단순노무) · 단위: 원(1인·연간)", "",
             "항목  산출근거  금액(원)"]
    lines += [f"{label}  {basis.get(label, '-')}  {x[key]:,}" for label, key in names]
    lines += [f"총계(1인)  -  {x['_소계']['총계']:,}"]
    write_pdf(path, lines)


def main() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    r = rate_values(2026)
    paths = []
    a = OUT / "가상업체A_산출내역.xlsx"
    if not a.exists():  # 승인 가능한 자료: 있으면 그대로 둔다
        wb = vendor_a(r)
        wb.properties.title = "시연용 가상 데이터"
        wb.save(a)
    paths.append(a)
    b = vendor_b(r)
    b.properties.title = "시연용 가상 데이터"
    b.save(OUT / "가상업체B_산출내역.xlsx")
    paths.append(OUT / "가상업체B_산출내역.xlsx")
    vendor_c(r, OUT / "가상업체C_산출내역.pdf")
    paths.append(OUT / "가상업체C_산출내역.pdf")
    return paths


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for p in main():
        print("생성:", p.relative_to(ROOT))
