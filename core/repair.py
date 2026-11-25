"""첨부 엑셀 점검과 수정본 생성.

원칙
- 첨부 파일은 메모리에서만 다루고 디스크에 저장하지 않는다.
- 정답이 하나로 정해지는 항목(수식 복원, 합계 범위, 옛 표기)만 자동 수정한다.
- 국민연금 대상 여부처럼 사람이 판단할 항목은 값을 채우지 않고 표시만 한다.
- 화면과 검토결과에는 실명 대신 사원N을 쓴다.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePath

import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.comments import Comment
from openpyxl.formula.translate import Translator
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import column_index_from_string as col_idx
from openpyxl.utils import get_column_letter as col_name

from .calc import PENSION_EXEMPT, PENSION_MISSING, floor10, pension_status
from .data import load_births, load_contracts, load_employees, rate_values, standards
from .guide import cite
from .validate import CHECK, ERROR, INFO, weekdays, ws_range

MAX_BYTES = 10 * 1024 * 1024
MAX_UNZIPPED = 120 * 1024 * 1024
MAX_ENTRIES = 2000
REVIEW_SHEET = "검토결과"
ERROR_VALUES = {"#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!"}
HOLIDAY_MONTHS = {2026: {2: "설날", 9: "추석"}, 2027: {2: "설날", 9: "추석"}}
FILL = {"fixed": "C6EFCE", ERROR: "FDE2E2", CHECK: "FFF4D6"}
ORDER = {ERROR: 0, CHECK: 1, INFO: 2}
REF = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?")
RRN = re.compile(r"(?<!\d)\d{6}-?[1-4]\d{6}(?!\d)")
PHONE = re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)")


class RepairError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 파일 오류."""


@dataclass
class Edit:
    cell: str
    before: object
    after: object


@dataclass
class Item:
    id: str
    severity: str
    category: str
    sheet: str
    cell: str
    target: str
    problem: str
    basis: str
    action: str
    edits: list[Edit] = field(default_factory=list)
    changes_amount: bool = False

    @property
    def fixable(self) -> bool:
        return bool(self.edits)


@dataclass
class Report:
    digest: str
    filename: str
    sheets: dict[str, str]
    items: list[Item]
    warnings: list[str]

    def count(self, severity: str) -> int:
        return sum(x.severity == severity for x in self.items)

    @property
    def fixable(self) -> list[Item]:
        return [x for x in self.items if x.fixable]

    @property
    def manual(self) -> list[Item]:
        return [x for x in self.items if not x.fixable]


def norm(v) -> str:
    return re.sub(r"\s+", "", str(v)) if v is not None else ""


def is_formula(v) -> bool:
    return isinstance(v, str) and v.startswith("=")


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def guard(raw: bytes, filename: str) -> list[str]:
    """열기 전에 형식과 크기를 검사하고, 수정본에서 사라질 수 있는 요소를 알려 준다."""
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".xls":
        raise RepairError("옛 형식(.xls)은 지원하지 않습니다. Excel에서 .xlsx로 저장한 뒤 다시 첨부해 주세요.")
    if suffix == ".xlsm":
        raise RepairError("매크로 포함 파일(.xlsm)은 매크로가 손상될 수 있어 지원하지 않습니다. .xlsx로 저장해 첨부해 주세요.")
    if suffix != ".xlsx":
        raise RepairError("Excel 통합문서(.xlsx)만 첨부할 수 있습니다.")
    if len(raw) > MAX_BYTES:
        raise RepairError("파일이 10MB를 넘습니다.")
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise RepairError("파일을 열 수 없습니다. 암호가 걸려 있거나 손상된 파일일 수 있습니다.")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
    if "xl/workbook.xml" not in names:
        raise RepairError("Excel 통합문서 구조가 아닙니다.")
    if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise RepairError("압축 해제 크기가 너무 큰 파일이라 처리하지 않습니다.")
    lost = []
    if any(n.startswith("xl/charts/chart") for n in names):
        lost.append("차트")
    if any(n.startswith("xl/pivot") for n in names):
        lost.append("피벗 테이블")
    if any(n.startswith("xl/slicer") for n in names):
        lost.append("슬라이서")
    if any(re.match(r"xl/drawings/drawing\d+\.xml", n) for n in names) and not any(n.startswith("xl/media/") for n in names):
        lost.append("도형")
    return [f"이 파일의 {', '.join(lost)}은(는) 수정본에서 사라지거나 바뀔 수 있습니다. 원본을 함께 보관하세요."] if lost else []


def _load(raw: bytes):
    try:
        return openpyxl.load_workbook(io.BytesIO(raw)), openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    except Exception as e:  # openpyxl은 손상 유형별로 여러 예외를 던진다
        raise RepairError("파일 내용을 읽을 수 없습니다. Excel에서 다시 저장한 뒤 첨부해 주세요.") from e


class Collector:
    def __init__(self, sheet: str, items: list[Item]):
        self.sheet, self.items = sheet, items

    def add(self, severity, category, cell, target, problem, basis, action, edits=(), changes_amount=False):
        self.items.append(Item(f"{len(self.items) + 1:03d}", severity, category, self.sheet, cell, target, problem, basis, action,
                               list(edits), changes_amount))


def sheet_period(ws) -> tuple[int | None, int | None]:
    text = " ".join(str(ws.cell(r, c).value or "") for r in range(1, 3) for c in range(1, 4))
    m = re.search(r"(20\d{2})\s*\.\s*(\d{1,2})", ws.title)
    if m:
        return int(m.group(1)), int(m.group(2))
    y = re.search(r"(20\d{2})\s*년?", f"{ws.title} {text}")
    mon = re.search(r"(?<!\d)(\d{1,2})\s*월", text)
    return (int(y.group(1)) if y else None), (int(mon.group(1)) if mon else None)


def referenced_columns(formula: str, row: int) -> set[int]:
    cols: set[int] = set()
    for a, r1, b, r2 in REF.findall(formula):
        low, high = int(r1), int(r2 or r1)
        if low <= row <= high:
            first, last = col_idx(a), col_idx(b or a)
            cols.update(range(first, last + 1))
    return cols


# ---------------------------------------------------------------- 공통 검사
def scan_error_values(ws, v, c: Collector) -> None:
    for row in ws.iter_rows():
        for cell in row:
            shown = v[cell.coordinate].value
            if shown in ERROR_VALUES or (is_formula(cell.value) and "#REF!" in cell.value):
                c.add(ERROR, "수식 오류값", cell.coordinate, f"행 {cell.row}", f"셀이 오류값({shown or '#REF!'})을 냅니다.",
                      "참조가 끊겼거나 계산할 수 없는 수식", "참조 셀을 확인해 수식을 다시 연결")


def consensus(ws, col: int, rows: list[int]):
    """열의 다수 수식을 상대참조 기준으로 찾아 (기준 수식, 기준 셀)을 돌려준다."""
    forms = {}
    for r in rows:
        value = ws.cell(r, col).value
        if is_formula(value):
            origin = f"{col_name(col)}{r}"
            forms[r] = Translator(value, origin=origin).translate_formula(f"{col_name(col)}5000")
    if len(forms) < 3 or len(forms) / len(rows) < 0.7:
        return None
    best, n = Counter(forms.values()).most_common(1)[0]
    return (best, f"{col_name(col)}5000") if n / len(rows) >= 0.7 else None


def check_formula_columns(ws, rows, skip, label, c: Collector, autofix: bool) -> None:
    for col in range(1, ws.max_column + 1):
        if col in skip:
            continue
        found = consensus(ws, col, rows)
        if not found:
            continue
        base, origin = found
        for r in rows:
            ref = f"{col_name(col)}{r}"
            value = ws[ref].value
            expected = Translator(base, origin=origin).translate_formula(ref)
            current = Translator(value, origin=ref).translate_formula(origin) if is_formula(value) else None
            if current == base or isinstance(ws[ref], MergedCell):
                continue
            state = "다른 수식이 입력" if is_formula(value) else "값이 직접 입력" if value is not None else "공란"
            edits = [Edit(ref, value, expected)] if autofix else []
            c.add(ERROR if autofix else CHECK, "수식 누락·불일치", ref, label(r), f"같은 열의 다른 행과 달리 {state}되어 있습니다.",
                  f"같은 열 표준 수식 {expected}", f"{expected}로 복원" if autofix else "같은 열 수식과 비교해 확인", edits, True)


# ---------------------------------------------------------------- 급여대장
def find_payroll(ws) -> dict | None:
    header, name_col = None, None
    for r in range(1, min(ws.max_row, 20) + 1):
        for cl in range(1, min(ws.max_column, 10) + 1):
            if norm(ws.cell(r, cl).value) in ("성명", "이름", "사원명", "직원명"):
                header, name_col = r, cl
                break
        if header:
            break
    if not header:
        return None
    first = header + 1
    while first <= ws.max_row and ws.cell(first, name_col).value in (None, ""):
        first += 1
    labels = {cl: "".join(norm(ws.cell(r, cl).value) for r in range(header, first)) for cl in range(1, ws.max_column + 1)}
    def pick(*patterns):
        for p in patterns:
            for cl, t in labels.items():
                if re.search(p, t):
                    return cl
        return None
    net = pick("실수령")
    gross = pick(r"계\(A\)", "지급합?계", "총지급", "급여합?계")
    deduct = pick(r"계\(B\)", "공제(액)?합?계")
    if not net or not gross or not deduct:
        return None
    ded = {"건강보험": pick("건강"), "장기요양": pick("장기요양"), "국민연금": pick("국민연금"), "고용보험": pick("고용보험"),
           "산재보험": pick("산재"), "소득세": pick("^소득세", "근로소득세"), "지방소득세": pick("지방소득세", "지방세")}
    ded = {k: v for k, v in ded.items() if v and v != deduct}
    rows, total = [], None
    r = first
    while r <= ws.max_row:
        name = norm(ws.cell(r, name_col).value)
        if not name:
            break
        if name in ("합계", "총계", "계", "소계"):
            total = r
            break
        rows.append(r)
        r += 1
    if len(rows) < 2:
        return None
    hourly = pick("노임단가", "^시급", "기본시급")
    holiday = pick("명절")
    return {"name": name_col, "rows": rows, "total": total, "net": net, "gross": gross, "deduct": deduct, "ded": ded, "hourly": hourly, "holiday": holiday}


def check_payroll(ws, v, t: dict, c: Collector, births: dict | None = None) -> None:
    rows, G, D, N = t["rows"], t["gross"], t["deduct"], t["net"]
    g, d, n = col_name(G), col_name(D), col_name(N)
    ded_cols = sorted(t["ded"].values())
    # 지급 항목은 합계 오른쪽(원본 양식) 또는 왼쪽(시급 다음부터)에 올 수 있다
    pay_cols = [cl for cl in range(G + 1, D) if cl not in ded_cols] if G < D else []
    if not pay_cols:
        pay_cols = list(range((t["hourly"] or t["name"]) + 1, G))
    alias = {}
    for i, r in enumerate(rows):
        raw = norm(ws.cell(r, t["name"]).value)
        alias[r] = raw if re.fullmatch(r"사원\d+", raw) else f"사원{i + 1}"

    for r in rows:
        who = alias[r]
        # 실수령액
        ref, value, expected = f"{n}{r}", ws[f"{n}{r}"].value, f"={g}{r}-{d}{r}"
        if not (is_formula(value) and value.replace("$", "") == expected):
            state = "공란" if value is None else "수식이 아닌 고정값" if not is_formula(value) else "표준과 다른 수식"
            c.add(ERROR, "실수령액 수식 누락", ref, who, f"실수령액이 {state}입니다. 급여가 바뀌어도 금액이 따라 바뀌지 않습니다.",
                  "급여대장 산식: 실수령액 = 지급 계(A) - 공제 계(B)", f"{expected}로 복원", [Edit(ref, value, expected)], True)
        # 공제 합계
        if ded_cols:
            ref, value = f"{d}{r}", ws[f"{d}{r}"].value
            expected = f"=SUM({col_name(ded_cols[0])}{r}:{col_name(ded_cols[-1])}{r})"
            refs = referenced_columns(value, r) if is_formula(value) else set()
            missing = [k for k, cl in t["ded"].items() if cl not in refs]
            if missing:
                detail = f"{', '.join(missing)}이(가) 합계에서 빠져 있습니다." if is_formula(value) else "공제 합계가 수식이 아닙니다."
                c.add(ERROR, "공제 미차감", ref, who, detail + " 실수령액이 과다 계산될 수 있습니다.",
                      "급여대장 산식: 공제 계(B) = 각 공제 항목의 합", f"{expected}로 수정", [Edit(ref, value, expected)], True)
        # 지급 합계
        if len(pay_cols) >= 2:
            ref, value = f"{g}{r}", ws[f"{g}{r}"].value
            expected = f"=SUM({col_name(pay_cols[0])}{r}:{col_name(pay_cols[-1])}{r})"
            refs = referenced_columns(value, r) if is_formula(value) else set()
            used = [cl for cl in pay_cols if ws.cell(r, cl).value not in (None, "")]
            if not is_formula(value) or any(cl not in refs for cl in used):
                c.add(ERROR, "지급 합계 오류", ref, who, "지급 합계가 수식이 아니거나 일부 지급 항목을 빠뜨립니다.",
                      "급여대장 산식: 지급 계(A) = 각 지급 항목의 합", f"{expected}로 수정", [Edit(ref, value, expected)], True)

    # 가상 생년월일은 원본 급여대장과 같은 직원 행에만 쓴다(다른 기관 파일에 잘못 적용 방지)
    births = load_births() if births is None else births
    today = load_contracts()["demo_today"]
    known = {e.name: e for e in load_employees()}
    tax_cell = t["ded"].get("소득세")

    def source_person(row: int):
        person = known.get(norm(ws.cell(row, t["name"]).value))
        return person if person and tax_cell and ws.cell(row, tax_cell).value == person.income_tax else None

    pension_law = "국민연금법상 사업장가입자는 18세 이상 60세 미만. " + cite("6-2-2")
    if t["ded"].get("국민연금"):
        for r in rows:
            person = source_person(r)
            cell_value = ws.cell(r, t["ded"]["국민연금"]).value
            if person and cell_value not in (None, "", 0) and pension_status(True, births.get(person.name), today)[0] == PENSION_EXEMPT:
                age = pension_status(True, births.get(person.name), today)[1]
                c.add(CHECK, "국민연금 연령 확인", f"{col_name(t['ded']['국민연금'])}{r}", alias[r], f"만 {age}세(가상 생년월일)인데 국민연금을 공제하고 있습니다.",
                      pension_law, "임의계속가입 여부 확인")

    # 법정 공제 공란 (산재보험은 사업주 전액 부담이라 공란이 정상)
    for label in ("건강보험", "장기요양", "고용보험", "국민연금"):
        cl = t["ded"].get(label)
        if not cl:
            continue
        filled = [ws.cell(r, cl).value for r in rows if ws.cell(r, cl).value not in (None, "", 0)]
        hint = f"같은 표의 공제액은 {Counter(filled).most_common(1)[0][0]:,}원입니다. " if filled and is_number(filled[0]) else ""
        for r in rows:
            if ws.cell(r, cl).value in (None, "", 0):
                ref = f"{col_name(cl)}{r}"
                if label == "국민연금":
                    person = source_person(r)
                    status, age = pension_status(False, births.get(person.name), today) if person else (None, None)
                    if status == PENSION_MISSING:
                        c.add(ERROR, "보험 대상자 누락", ref, alias[r], f"만 {age}세(가상 생년월일)인데 국민연금 공제가 없습니다. {hint}", pension_law, "취득신고 및 소급 공제 검토")
                    elif status == PENSION_EXEMPT:
                        c.add(INFO, "국민연금 연령 제외", ref, alias[r], f"만 {age}세(가상 생년월일)라 의무가입 대상이 아니며 공란이 정상입니다.", pension_law, "조치 없음")
                    else:
                        c.add(CHECK, "보험 대상자 누락", ref, alias[r], f"국민연금 공제가 공란입니다. {hint}생년월일이 없으면 대상 여부를 확정할 수 없습니다.",
                              pension_law, "생년월일 확인 후 대상이면 공제액 입력·소급 검토")
                else:
                    c.add(ERROR, "법정 항목 공란", ref, alias[r], f"{label} 공제가 공란입니다. {hint}", "4대 사회보험 관계 법령. " + cite("6-2-2"), f"보수월액을 확인해 {label} 공제액 입력")

    # 지방소득세 = 소득세 × 10%, 10원 미만 버림 (판단이 필요해 자동 수정하지 않음)
    tax_col, local_col = t["ded"].get("소득세"), t["ded"].get("지방소득세")
    if tax_col and local_col:
        rate = standards()["local_income_tax_rate"]
        for r in rows:
            tax, local = ws.cell(r, tax_col).value, ws.cell(r, local_col).value
            if is_number(tax) and tax and is_number(local) and local != floor10(tax * rate):
                due = floor10(tax * rate)
                c.add(CHECK, "지방소득세 불일치", f"{col_name(local_col)}{r}", alias[r],
                      f"소득세 {tax:,}원의 10%(10원 미만 버림)는 {due:,}원인데 입력값은 {local:,}원으로 {local - due:+,}원 차이입니다.",
                      "지방세법상 개인지방소득세(근로소득 특별징수)는 소득세의 10%", "간이세액표·원천징수 내역과 대조")

    # 합계 행
    if t["total"]:
        for cl in range(G, ws.max_column + 1):
            ref = f"{col_name(cl)}{t['total']}"
            value = ws[ref].value
            if value is None or isinstance(ws[ref], MergedCell) or not any(is_number(ws.cell(r, cl).value) or is_formula(ws.cell(r, cl).value) for r in rows):
                continue
            L = col_name(cl)
            expected = f"=SUM({L}{rows[0]}:{L}{rows[-1]})"
            if norm(value).replace("$", "").upper() != expected:
                c.add(ERROR, "합계 범위 오류", ref, "합계", "합계가 전체 직원 행을 포함하지 않거나 수식이 아닙니다.", "합계 = 첫 직원 행부터 마지막 직원 행까지", f"{expected}로 수정", [Edit(ref, value, expected)], True)

    skip = {G, D, N, t["name"]}
    check_formula_columns(ws, rows, skip, lambda r: alias[r], c, autofix=True)

    # 최저임금
    year, month = sheet_period(ws)
    if t["hourly"] and year in (2026, 2027):
        floor = rate_values(year)["min_wage"]
        L = col_name(t["hourly"])
        low = [r for r in rows if is_number(ws.cell(r, t["hourly"]).value) and ws.cell(r, t["hourly"]).value < floor]
        for r in low:
            c.add(ERROR, "최저임금 미달", f"{L}{r}", alias[r], f"시급 {ws.cell(r, t['hourly']).value:,}원이 {year}년 최저임금 {floor:,}원보다 낮습니다.",
                  "최저임금법. " + cite("5-2-c"), f"시급을 {floor:,}원 이상으로 변경")
        if year == 2026 and not low:
            nxt = rate_values(2027)["min_wage"]
            soon = [r for r in rows if is_number(ws.cell(r, t["hourly"]).value) and ws.cell(r, t["hourly"]).value < nxt]
            if soon:
                c.add(INFO, "내년 단가 주의", f"{L}{soon[0]}:{L}{soon[-1]}", f"{len(soon)}명", f"이번 달은 적법하지만 2027년 최저임금 {nxt:,}원보다는 낮습니다.",
                      "고용노동부 2026.8.5 고시", "2027년 1월 급여부터 시급 인상")

    # 산출근거 표
    size = len(rows)
    for r_ in range(rows[-1] + 1, ws.max_row + 1):
        for cl in range(1, ws.max_column + 1):
            text = norm(ws.cell(r_, cl).value)
            if text == "잔여연차":
                area = [ws.cell(r_ + k, x).value for k in range(1, size + 1) for x in (cl - 2, cl - 1, cl, cl + 1)]
                if not any(x not in (None, "") for x in area):
                    c.add(CHECK, "법정 항목 공란", f"{col_name(cl - 2)}{r_ + 1}:{col_name(cl + 1)}{r_ + size}", "전원", "연가보상비 산출표가 비어 있어 연가보상비가 0원으로 계산됩니다.",
                          "근로기준법 제60조(연차 유급휴가)", "연차 사용 내역 입력 또는 해당 없음 기재")
            if text == "내역":
                area = [ws.cell(r_ + k, x).value for k in range(1, size + 1) for x in (cl - 1, cl)]
                if not any(x not in (None, "") for x in area):
                    c.add(CHECK, "법정 항목 공란", f"{col_name(cl - 1)}{r_ + 1}:{col_name(cl)}{r_ + size}", "전원", "유급휴일의 날짜와 사유가 비어 있습니다.",
                          "급여대장 '유급휴일' 산출근거", "휴일 날짜와 사유 기재")
            m = re.fullmatch(r"월기본급\((\d{1,2})\)", text)
            if m and year and t["hourly"]:
                mon = int(m.group(1))
                limit = weekdays(year, mon)
                for k, base_row in enumerate(rows):
                    value = ws.cell(r_ + 1 + k, cl).value
                    wage = ws.cell(base_row, t["hourly"]).value
                    if is_number(value) and is_number(wage) and value / (wage * 8) > limit + 1e-6:
                        c.add(CHECK, "근무일수 이상", f"{col_name(cl)}{r_ + 1 + k}", alias[base_row],
                              f"{mon}월 기본급 {value:,}원은 {value / (wage * 8):.0f}일분인데 {year}년 {mon}월 평일은 {limit}일입니다. 상여금 평균에 영향을 줍니다.",
                              "산출근거 '상여금: 3개월 간 기본급 평균*0.5'", "해당 월 근무 실적과 대조")

    # 명절 달
    if t["holiday"] and year in HOLIDAY_MONTHS and month in HOLIDAY_MONTHS[year]:
        L = col_name(t["holiday"])
        if not any(ws.cell(r, t["holiday"]).value for r in rows):
            c.add(CHECK, "법정 항목 공란", f"{L}{rows[0]}:{L}{rows[-1]}", "전원", f"{HOLIDAY_MONTHS[year][month]}이 있는 달인데 명절휴가비가 공란입니다. 지급 대상이 아니면 정상입니다.",
                  "내부 보수규정 확인 사항(법정 의무 항목 아님)", "지급 규정 확인")


# ---------------------------------------------------------------- 원가 산출내역
def find_cost(ws) -> dict | None:
    labels = {}
    for r in range(1, ws.max_row + 1):
        for cl in (3, 2, 1):
            text = norm(ws.cell(r, cl).value)
            if text and len(text) > 1:
                labels[r] = (cl, text)
                break
    joined = " ".join(t for _, t in labels.values())
    if not all(k in joined for k in ("기본급", "일반관리비", "이윤", "부가가치세")):
        return None
    amount = None
    for r in range(1, 10):
        for cl in range(1, ws.max_column + 1):
            if "금액" in norm(ws.cell(r, cl).value):
                amount = cl
                break
        if amount:
            break
    return {"labels": labels, "amount": amount or 4} if labels else None


def _replace_row(ws, row: int, pairs) -> list[Edit]:
    edits = []
    for cl in range(1, ws.max_column + 1):
        cell = ws.cell(row, cl)
        if isinstance(cell, MergedCell) or not isinstance(cell.value, str):
            continue
        after = cell.value
        for old, new in pairs:
            after = after.replace(old, new)
        if after != cell.value:
            edits.append(Edit(cell.coordinate, cell.value, after))
    return edits


def check_cost(ws, v, t: dict, c: Collector) -> None:
    labels, A = t["labels"], t["amount"]
    a = col_name(A)
    year, _ = sheet_period(ws)

    # 시중노임단가 입력칸
    daily, daily_cell = None, None
    for row in ws.iter_rows():
        for cell in row:
            if norm(cell.value) == "일급" and cell.column > 1 and is_number(ws.cell(cell.row, cell.column - 1).value):
                daily, daily_cell = ws.cell(cell.row, cell.column - 1).value, ws.cell(cell.row, cell.column - 1)
    if daily:
        stale_text = f"{daily:,}"
        for row in ws.iter_rows():
            for cell in row:
                if not isinstance(cell.value, str) or is_formula(cell.value) or isinstance(cell, MergedCell):
                    continue
                for m in re.finditer(r"(?<![\d,])(\d{2,3},\d{3})원", cell.value):
                    number = int(m.group(1).replace(",", ""))
                    if 70_000 <= number <= 150_000 and number != daily:
                        after = cell.value.replace(m.group(1), stale_text)
                        c.add(ERROR, "옛 단가 잔존", cell.coordinate, f"행 {cell.row}", f"설명에 옛 일급 {m.group(1)}원이 남아 있습니다. 실제 입력 단가는 {stale_text}원입니다.",
                              cite("붙임4-유의"), f"설명을 {stale_text}원으로 수정", [Edit(cell.coordinate, cell.value, after)])
                        break
    survey_daily = rate_values(2026)["market_daily"]
    if daily == survey_daily:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and not isinstance(cell, MergedCell) and "노임단가" in cell.value and "2024년" in cell.value:
                    after = re.sub(r"2024년\s*6월", "2026년 상반기", cell.value)
                    after = re.sub(r"24년\s*10월\s*적용", "2026년 하반기 적용", after)
                    c.add(ERROR, "옛 날짜 잔존", cell.coordinate, "노임단가 표기", f"{survey_daily:,}원은 2026년 상반기 조사 단가인데 2024년으로 표기되어 있습니다.",
                          f"지침 5-2: “2026년 상반기 조사 : {survey_daily:,}원(일급) → 2026년 하반기 적용”", "출처와 적용 시기 수정", [Edit(cell.coordinate, cell.value, after)])

    prev = None
    for r, (_, text) in sorted(labels.items()):
        value = ws[f"{a}{r}"].value
        if "소계" in text:
            m = re.fullmatch(rf"=SUM\({a}(\d+):{a}(\d+)\)", str(value).replace("$", "").upper()) if is_formula(value) else None
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                want_start = prev + 1 if prev else start
                if start != want_start or end != r - 1:
                    omitted = [labels[x][1] for x in range(want_start, r) if x in labels and not start <= x <= end]
                    expected = f"=SUM({a}{want_start}:{a}{r - 1})"
                    extra = f" {', '.join(omitted)} 행이 빠져 있습니다." if omitted else ""
                    c.add(ERROR, "수식 범위 오류", f"{a}{r}", text, f"소계 범위가 구간과 맞지 않습니다.{extra} 값이 입력되면 총액에서 누락됩니다.",
                          cite("5-5-3"), f"{expected}로 수정", [Edit(f"{a}{r}", value, expected)], True)
            prev = r
        if not is_formula(value):
            continue
        rate = re.search(r"\*\s*([\d.]+)%", value)
        pct = float(rate.group(1)) if rate else None
        if pct is None:
            rate = re.search(r"\*\s*(0\.\d+)", value)
            pct = float(rate.group(1)) * 100 if rate else None
        for key, limit, law in (("일반관리비", 9, "국가계약법 시행규칙 제8조(9% 이하)"), ("이윤", 10, "국가계약법 시행규칙 제8조(10% 이하)")):
            if key in text and pct is not None and pct > limit:
                c.add(ERROR, "요율 한도 초과", f"{a}{r}", key, f"{key} 요율 {pct:g}%가 한도 {limit}%를 넘습니다.", law, f"{limit}% 이하로 수정")
        if "부가가치세" in text and pct is not None and abs(pct - 10) > 1e-9:
            c.add(ERROR, "요율 오류", f"{a}{r}", "부가가치세", f"부가가치세율이 {pct:g}%입니다.", "부가가치세법", "10%로 수정")

    for r, (_, text) in labels.items():
        row_text = " ".join(str(ws.cell(r, x).value or "") for x in range(1, ws.max_column + 1))
        if "장기요양" in text and ("12.95" in row_text or "0.1295" in row_text):
            if year is not None and year < 2026:
                continue
            if year is None:
                c.add(CHECK, "옛 단가 잔존", f"{a}{r}", "장기요양", f"장기요양 요율이 12.95%입니다. 파일 연도를 알 수 없어 2026년({rate_values(2026)['ltc']:.2%})·2027년({rate_values(2027)['ltc']:.2%}) 중 적용 요율을 확인해야 합니다.", cite("붙임4-요양"), "적용 연도의 요율 확인")
            else:
                target = rate_values(2026 if year == 2026 else 2027)["ltc"]
                edits = _replace_row(ws, r, [("12.95", f"{target * 100:.2f}"), ("0.1295", f"{target:.4f}".rstrip("0"))])
                c.add(ERROR, "옛 단가 잔존", f"{a}{r}", "장기요양", f"장기요양 요율이 옛 값 12.95%입니다. {min(year, 2027)}년 요율은 건강보험료의 {target:.2%}이며 금액이 과소 계상됩니다.",
                      cite("붙임4-요양"), f"요율을 {target:.2%}로 수정(총액이 바뀜)", edits, True)
        if "이윤" in text and "(인+복후+경)" in row_text:
            edits = _replace_row(ws, r, [("(인+복후+경)", "(인+복후+경+일반관리비)")])
            c.add(INFO, "산출근거 불일치", edits[0].cell, "이윤", "실제 수식은 일반관리비를 포함하지만 설명에는 빠져 있습니다.", cite("붙임4-이윤"), "설명 문구 수정", edits)
        old = re.search(r"고시\s*제(20\d{2})-", row_text)
        if old and int(old.group(1)) < 2025:
            cell = next(ws.cell(r, x) for x in range(1, ws.max_column + 1) if "고시" in str(ws.cell(r, x).value or ""))
            c.add(CHECK, "옛 날짜 잔존", cell.coordinate, text, f"{old.group(1)}년 고시를 근거로 적었습니다.", "붙임 4: “2026년도 사업종류별 산재보험요율”", "최신 고시의 요율과 번호 확인")
        if "연차" in text and "*11일" in row_text:
            c.add(CHECK, "법정 항목 확인", f"{a}{r}", "연차수당", "연차를 11일로 계상했습니다. 지침 예시는 15일이며, 근속 1년 미만 전제라면 11일이 맞습니다.", cite("붙임4-연차"), "근속 구성을 확인해 일수 결정")
        if "건강보험" in text and "시행령 제36조" in row_text:
            cell = next(ws.cell(r, x) for x in range(1, ws.max_column + 1) if "시행령" in str(ws.cell(r, x).value or ""))
            c.add(INFO, "옛 근거 잔존", cell.coordinate, "건강보험", "시행령 조문이 지침 붙임 4(제44조)와 다릅니다.", "붙임 4 건강보험료 관련규정", "조문 확인 후 수정")


# ---------------------------------------------------------------- 분석·수정본
def scan_pii(wb) -> dict[str, int]:
    found = {"주민등록번호": 0, "전화번호": 0}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and not value.startswith("="):
                    found["주민등록번호"] += len(RRN.findall(value))
                    found["전화번호"] += len(PHONE.findall(value))
    return found


def analyze(raw: bytes, filename: str, births: dict | None = None) -> Report:
    warnings = guard(raw, filename)
    wf, wv = _load(raw)
    items: list[Item] = []
    kinds: dict[str, str] = {}
    for ws in wf.worksheets:
        if ws.title == REVIEW_SHEET:
            continue
        v = wv[ws.title]
        c = Collector(ws.title, items)
        scan_error_values(ws, v, c)
        payroll = find_payroll(ws)
        cost = None if payroll else find_cost(ws)
        if payroll:
            kinds[ws.title] = f"급여대장 ({len(payroll['rows'])}명)"
            check_payroll(ws, v, payroll, c, births)
        elif cost:
            kinds[ws.title] = "용역 원가 산출내역"
            check_cost(ws, v, cost, c)
        else:
            kinds[ws.title] = "일반 표 (기본 검사)"
            rows = list(range(1, ws.max_row + 1))
            for col in range(1, ws.max_column + 1):
                filled = [r for r in rows if ws.cell(r, col).value is not None]
                formula_rows = [r for r in filled if is_formula(ws.cell(r, col).value)]
                if len(formula_rows) >= 3:
                    span = [r for r in filled if formula_rows[0] <= r <= formula_rows[-1]]
                    check_formula_columns(ws, span, set(range(1, ws.max_column + 1)) - {col}, lambda r: f"행 {r}", c, autofix=False)
    pii = scan_pii(wf)
    if any(pii.values()):
        text = ", ".join(f"{k} {n}건" for k, n in pii.items() if n)
        warnings.append(f"개인정보로 보이는 값이 있습니다({text}). 화면에는 표시하지 않지만 수정본에는 그대로 남으니 외부 공유에 주의하세요.")
    items.sort(key=lambda x: (ORDER[x.severity], x.sheet))
    for i, x in enumerate(items, 1):
        x.id = f"{i:03d}"
    return Report(hashlib.sha256(raw).hexdigest()[:12], filename, kinds, items, warnings)


def _target(ws, ref: str):
    cell = ws[ref]
    if isinstance(cell, MergedCell):
        for rng in ws.merged_cells.ranges:
            if ref in rng:
                return ws.cell(rng.min_row, rng.min_col)
    return cell


def _note(cell, text: str) -> None:
    old = f"{cell.comment.text}\n" if cell.comment else ""
    note = Comment(f"{old}[인건비 내비게이터] {text}", "인건비 내비게이터")
    note.width, note.height = 320, 130
    cell.comment = note


def _text(ws, row: int, col: int, value) -> None:
    """수식처럼 보이는 문자열도 글자로만 저장한다."""
    cell = ws.cell(row, col)
    cell.value = "" if value is None else str(value)
    cell.data_type = "s"
    cell.alignment = Alignment(wrap_text=True, vertical="top")


def build_fixed(raw: bytes, report: Report, selected: set[str], mark: bool = True) -> tuple[bytes, int]:
    wb = openpyxl.load_workbook(io.BytesIO(raw))
    applied: set[str] = set()
    for x in report.items:
        ws = wb[x.sheet]
        if x.id in selected and x.fixable and all(ws[e.cell].value == e.before for e in x.edits):
            for e in x.edits:
                cell = _target(ws, e.cell)
                cell.value = e.after
                if mark:
                    cell.fill = PatternFill("solid", fgColor=FILL["fixed"])
                    _note(cell, f"수정: {x.problem}")
            applied.add(x.id)
        elif mark and x.severity in FILL:
            cells = ws_range(x.cell)
            for ref in cells[:200]:
                _target(ws, ref).fill = PatternFill("solid", fgColor=FILL[x.severity])
            _note(_target(ws, cells[0]), f"{x.severity}: {x.problem} / 조치: {x.action}")

    name = REVIEW_SHEET
    n = 2
    while name in wb.sheetnames:
        name, n = f"{REVIEW_SHEET}{n}", n + 1
    rs = wb.create_sheet(name)
    head = ["상태", "심각도", "시트", "셀", "대상", "문제", "근거", "권장 조치", "수정 전", "수정 후"]
    for j, h in enumerate(head, 1):
        cell = rs.cell(1, j, h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365F")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for i, x in enumerate(report.items, 2):
        state = "수정 완료" if x.id in applied else "자동 수정 미적용" if x.fixable else "담당자 확인"
        before = "\n".join(str(e.before if e.before is not None else "(공란)") for e in x.edits)
        after = "\n".join(str(e.after) for e in x.edits)
        for j, value in enumerate((state, x.severity, x.sheet, x.cell, x.target, x.problem, x.basis, x.action, before, after), 1):
            _text(rs, i, j, value)
        rs.cell(i, 1).fill = PatternFill("solid", fgColor=FILL["fixed"] if x.id in applied else FILL[CHECK])
    for j, width in enumerate((14, 10, 22, 12, 14, 52, 42, 32, 30, 30), 1):
        rs.column_dimensions[col_name(j)].width = width
    rs.freeze_panes = "A2"
    if report.items:
        rs.auto_filter.ref = f"A1:J{len(report.items) + 1}"
    wb.calculation.fullCalcOnLoad = True
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), len(applied)


def demo_error_file() -> bytes:
    """시연용: 기간제 원본 사본에 오류 3건을 넣은 파일을 메모리에서 만든다."""
    from .data import source_file
    wb = openpyxl.load_workbook(source_file("기간제"))
    ws = wb.worksheets[0]
    ws["AD9"] = 3022660
    ws["U10"] = "=SUM(V10:AA10)"
    ws["Y13"] = None
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
