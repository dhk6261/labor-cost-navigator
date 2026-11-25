"""AI 문서 인식 모듈(시연판). 앱 안에서만 동작하며 파일 내용은 밖으로 나가지 않는다. 외부 AI API 구현은 만들지 않는다.

- 인터페이스: Extractor.extract(raw, filename) -> Extraction(fields=[Field...])
  Field = {이름, 값, 단위, 위치(시트·셀 또는 쪽·줄), 원문, 확신도, 종류(항목/정보), 방식}
- 기본 구현 RuleExtractor: 표 구조 인식(머리글 행 찾기) + 규칙 + 문자열 유사도(difflib, core/mapping.py).
- [실제 도입 시 연결 지점] 공단 내부망에 설치한 모델을 같은 인터페이스로 만들어 REGISTRY에 등록한다.
- 추출기는 파일에서 '값과 위치'만 꺼낸다. 금액 계산은 core/calc.py가 한다.
- 실명·주민번호·연락처·계좌 등 개인정보 열은 값을 읽지 않고 버린다.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePath
from typing import Protocol

from .mapping import match
from .repair import MAX_BYTES, RepairError, _load, guard
from .standard import BASE_ITEMS, LEGAL_ITEMS

RATE_ITEMS = set(LEGAL_ITEMS) | {"일반관리비(9%)", "이윤(10%)", "부가가치세"}

SUPPORTED = (".xlsx", ".csv", ".docx", ".pdf")
ITEM_HEAD = re.compile(r"(항목|비목|내역|품명)")
AMOUNT_HEAD = re.compile(r"금액")
PII_HEAD = re.compile(r"(성명|이름|주민|생년월일|연락처|전화|휴대|핸드폰|계좌|주소|이메일|e-?mail)", re.I)
NUM = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")
ITEM, INFO = "항목", "정보"
META = [  # (이름, 정규식, 단위, 확신도)
    ("계약명", re.compile(r"계약(?:명)?\s*[:：]\s*([^·/\n]+?)\s*(?:[·/]|$)"), "", 0.95),
    ("업체명", re.compile(r"(?:업체명|상호)\s*[:：]\s*([^·/\n]+?)\s*(?:[·/]|$)"), "", 0.95),
    ("업체명", re.compile(r"(가상(?:업체|기업)[A-Z])"), "", 0.9),
    ("인원", re.compile(r"인원\s*[:：]?\s*(\d+)\s*명"), "명", 0.95),
    ("직종", re.compile(r"직종\s*[:：]\s*([^·/\n]+?)\s*(?:[·/]|$)"), "", 0.95),
    ("월 근무시간", re.compile(r"월\s*근무\s*시간\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)"), "시간", 0.95),
    ("월 근무시간", re.compile(r"(\d{2,3}(?:\.\d+)?)\s*(?:h|시간)\s*[×x*]\s*12"), "시간", 0.9),
    ("근무일수", re.compile(r"근무\s*일수\s*[:：]?\s*(\d{1,2})"), "일", 0.95),
    ("일급", re.compile(r"일급\s*[:：]?\s*(\d{1,3}(?:,\d{3})+|\d{5,6})\s*원"), "원", 0.95),
    ("일급", re.compile(r"(\d{1,3}(?:,\d{3})+|\d{5,6})\s*원?\s*/\s*8"), "원", 0.9),
    ("시급", re.compile(r"시급\s*[:：]?\s*(\d{1,3}(?:,\d{3})+|\d{4,5})\s*원"), "원", 0.95),
]


@dataclass
class Field:
    이름: str
    값: object
    단위: str
    위치: str
    원문: str
    확신도: float
    종류: str = ITEM
    방식: str = ""

    @property
    def key(self) -> str:
        return f"{self.종류}|{self.위치}|{self.이름}"


@dataclass
class Extraction:
    fields: list[Field] = field(default_factory=list)
    pii_dropped: int = 0
    warnings: list[str] = field(default_factory=list)
    source: str = ""

    def as_dict(self) -> dict:
        return {"fields": [asdict(f) | {"key": f.key} for f in self.fields], "pii_dropped": self.pii_dropped, "warnings": self.warnings, "source": self.source}


class Extractor(Protocol):
    name: str

    def extract(self, raw: bytes, filename: str) -> Extraction: ...


def normalize(text, unit_hint: str = "") -> tuple[float | None, str]:
    """'1,234천원', '99,310', '99,310원', '13.14%', 1234 → (값, 단위)."""
    if isinstance(text, bool) or text is None:
        return None, ""
    if isinstance(text, (int, float)):
        scale = 1000 if "천원" in unit_hint else 10000 if "만원" in unit_hint else 1
        return float(text) * scale, "원" if scale > 1 or "원" in unit_hint else ""
    t = str(text).strip().replace(" ", "")
    m = NUM.search(t)
    if not m:
        return None, ""
    v = float(m.group().replace(",", ""))
    rest = t[m.end():]
    if rest.startswith("%"):
        return round(v / 100, 10), "%"
    if rest.startswith("천원") or ("천원" in unit_hint and not rest.startswith("원")):
        return v * 1000, "원"
    if rest.startswith("만원") or ("만원" in unit_hint and not rest.startswith("원")):
        return v * 10000, "원"
    return v, "원" if rest.startswith("원") or "원" in unit_hint else ""


# ───────────── 파일 → 격자(행·칸 + 위치) ─────────────
Cell = tuple[str | float | int | None, str]   # (값, 위치)
Grid = tuple[str, list[list[Cell]]]           # (이름, 행 목록)


def _grids_xlsx(raw: bytes, filename: str, warn: list[str]) -> list[Grid]:
    warn += guard(raw, filename)
    _, wb = _load(raw)
    return [(ws.title, [[(c.value, f"{ws.title}!{c.coordinate}") for c in row] for row in ws.iter_rows()]) for ws in wb.worksheets]


def _grids_csv(raw: bytes) -> list[Grid]:
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RepairError("CSV 글자 인코딩을 읽을 수 없습니다(UTF-8 또는 CP949로 저장해 주세요).")
    rows = list(csv.reader(io.StringIO(text)))
    return [("CSV", [[(v, f"{i + 1}행 {j + 1}열") for j, v in enumerate(row)] for i, row in enumerate(rows)])]


def _grids_docx(raw: bytes) -> list[Grid]:
    from docx import Document
    try:
        d = Document(io.BytesIO(raw))
    except Exception as e:  # python-docx는 손상 유형별로 여러 예외를 던진다
        raise RepairError("Word 파일을 읽을 수 없습니다.") from e
    grids = [("본문", [[(p.text, f"본문 {i + 1}문단")] for i, p in enumerate(d.paragraphs) if p.text.strip()])]
    for t, table in enumerate(d.tables, 1):
        grids.append((f"표{t}", [[(c.text, f"표{t} {i + 1}행 {j + 1}열") for j, c in enumerate(row.cells)] for i, row in enumerate(table.rows)]))
    return grids


def _grids_pdf(raw: bytes) -> list[Grid]:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [p.extract_text() or "" for p in reader.pages]
    except Exception as e:  # pypdf는 손상 유형별로 여러 예외를 던진다
        raise RepairError("PDF 파일을 읽을 수 없습니다.") from e
    if not "".join(pages).strip():
        raise RepairError("PDF에 글자(텍스트)가 없습니다. 스캔 이미지 PDF는 지원하지 않습니다(OCR은 향후 확장).")
    rows = []
    for pno, text in enumerate(pages, 1):
        for lno, line in enumerate(text.splitlines(), 1):
            if line.strip():
                rows.append([(cell, f"{pno}쪽 {lno}줄") for cell in re.split(r"\s{2,}", line.strip())])
    return [("PDF", rows)]


# ───────────── 규칙 추출기 ─────────────
class RuleExtractor:
    """표 머리글 찾기 → 항목명 연결(사전 → 유사도) → 핵심 값 추출 → 숫자·단위 정규화."""
    name = "rule"

    def extract(self, raw: bytes, filename: str) -> Extraction:
        suffix = PurePath(filename).suffix.lower()
        if suffix not in SUPPORTED:
            raise RepairError(f"지원하는 파일은 {', '.join(SUPPORTED)} 입니다.")
        if len(raw) > MAX_BYTES:
            raise RepairError("파일이 10MB를 넘습니다.")
        out = Extraction(source=suffix[1:])
        grids = {".xlsx": lambda: _grids_xlsx(raw, filename, out.warnings), ".csv": lambda: _grids_csv(raw),
                 ".docx": lambda: _grids_docx(raw), ".pdf": lambda: _grids_pdf(raw)}[suffix]()
        found_table = False
        self._pii: set[str] = set()   # 개인정보 열의 칸 위치(값은 읽지 않음)
        for _, rows in grids:
            table = self._table(rows, out)
            found_table = found_table or table
        self._meta(grids, out)
        if not found_table:
            raise RepairError("'항목(비목·내역)'과 '금액' 머리글이 있는 표를 찾지 못했습니다. 산출내역서 양식을 확인해 주세요.")
        return out

    def _table(self, rows: list[list[Cell]], out: Extraction) -> bool:
        for r0, row in enumerate(rows[:40]):
            texts = {j: str(v).strip() for j, (v, _) in enumerate(row) if isinstance(v, str) and v.strip()}
            item_cols = [j for j, t in texts.items() if ITEM_HEAD.search(t) and not PII_HEAD.search(t)]
            amount_cols = [j for j, t in texts.items() if AMOUNT_HEAD.search(t)]
            if item_cols and amount_cols:
                break
        else:
            return False
        amount_col, unit_hint = amount_cols[0], texts[amount_cols[0]]
        pii = [j for j, t in texts.items() if PII_HEAD.search(t)]
        out.pii_dropped += len(pii)
        body = rows[r0 + 1:]

        def cell(r, j):
            return r[j] if j < len(r) else (None, "")

        def filled(j):
            return sum(1 for r in body if isinstance(cell(r, j)[0], str) and cell(r, j)[0].strip() and normalize(cell(r, amount_col)[0], unit_hint)[0] is not None)

        self._pii |= {cell(r, j)[1] for r in body for j in pii}

        item_col = max(item_cols, key=filled)
        for r in body:
            label, _ = cell(r, item_col)
            value, pos = cell(r, amount_col)
            amount, _unit = normalize(value, unit_hint)
            if not isinstance(label, str) or not label.strip() or amount is None:
                continue
            m = match(label)
            if m["방식"] == "소계":
                continue
            out.fields.append(Field(m["항목"] or f"미분류:{label.strip()}", amount, "원", pos, label.strip(), m["확신도"], ITEM, m["방식"]))
            for j, (v, p) in enumerate(r):  # 같은 행의 요율(산출근거) — 개인정보 열은 읽지 않음
                if j in pii or j in (item_col, amount_col) or not isinstance(v, str) or "%" not in v or m["항목"] not in RATE_ITEMS:
                    continue
                rate, unit = normalize(re.findall(r"[\d.]+\s*%", v)[-1] if re.findall(r"[\d.]+\s*%", v) else v)
                if unit == "%":
                    out.fields.append(Field(f"적용 요율:{m['항목']}", rate, "%", p, v.strip(), 0.9, INFO, "규칙"))
        return True

    def _meta(self, grids: list[Grid], out: Extraction) -> None:
        pii_pos = self._pii
        seen: set[str] = set()
        for _, rows in grids:
            for row in rows:
                for v, pos in row:
                    if not isinstance(v, str) or pos in pii_pos:
                        continue
                    for name, rx, unit, conf in META:
                        if name in seen:
                            continue
                        m = rx.search(v)
                        if m:
                            text = m.group(1).strip()
                            value = normalize(text)[0] if unit in ("명", "시간", "일", "원") else text
                            if value is None or value == "":
                                continue
                            out.fields.append(Field(name, value, unit, pos, v.strip()[:60], conf, INFO, "규칙"))
                            seen.add(name)


REGISTRY: dict[str, Extractor] = {"rule": RuleExtractor()}


def get(name: str = "rule") -> Extractor:
    return REGISTRY[name]


def extract(raw: bytes, filename: str, extractor: str = "rule") -> dict:
    return get(extractor).extract(raw, filename).as_dict()


def summarize(fields: list[dict], default_headcount: int = 3) -> dict:
    """추출 필드 → 산출 입력과 업체 금액. {inputs, amounts, conf, unmapped, duplicates, meta}."""
    amounts, conf, dup, unmapped, meta = {}, {}, {}, [], {}
    for f in fields:
        if f["종류"] == INFO:
            meta.setdefault(f["이름"], f["값"])
            continue
        if f["이름"].startswith("제외:"):
            continue
        if f["이름"].startswith("미분류:"):
            unmapped.append({"원문": f["원문"], "금액": f["값"]})
            continue
        if f["이름"] not in BASE_ITEMS:
            continue
        amounts[f["이름"]] = amounts.get(f["이름"], 0) + f["값"]
        dup[f["이름"]] = dup.get(f["이름"], 0) + 1
        prev = conf.get(f["이름"], (1.0, f["원문"]))
        conf[f["이름"]] = (min(prev[0], f["확신도"]), f["원문"] if f["확신도"] <= prev[0] else prev[1])
    inputs = {"headcount": int(meta.get("인원") or default_headcount)}
    if meta.get("월 근무시간"):
        inputs["monthly_hours"] = float(meta["월 근무시간"])
    if meta.get("근무일수"):
        inputs["work_days"] = int(meta["근무일수"])
    if meta.get("일급"):
        inputs["daily"] = float(meta["일급"])
    elif meta.get("시급"):
        inputs["daily"] = float(meta["시급"]) * 8
    if meta.get("직종"):
        inputs["job"] = meta["직종"]
    return {"inputs": inputs, "amounts": amounts, "conf": conf, "unmapped": unmapped, "duplicates": {k: v for k, v in dup.items() if v > 1}, "meta": meta}
