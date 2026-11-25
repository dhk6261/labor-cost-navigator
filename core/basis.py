"""산정기준 패널과 기준 버전 관리.

- 패널: 이번 산출에 쓴 기준(적용 연도, 시중노임단가, 최저임금, 보험 요율, 209시간, 일반관리비·이윤 상한, 낙찰률, 지침 조항)을
  단가 파일에서 읽어 표로 만든다. 표준 산출서의 '산정기준·근거' 칸은 이 패널의 번호(기준①…)를 가리킨다.
- 버전: 기준을 적용·수정·되돌릴 때마다 data/기준이력/v{n}.json으로 남긴다. 되돌리기도 새 버전으로 기록한다.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime

from . import audit, rates
from .calc import DEFAULT_AWARD_RATE
from .data import DATA, active_year, load_rates, standards
from .guide import CLAUSES

DIR = DATA / "기준이력"
JUDGE = DATA / "판정기준.json"
CAPS = ("overhead_cap", "profit_cap")
RATE_KEYS = list(rates.REQUIRED)


def _judge() -> dict:
    return json.loads(JUDGE.read_text(encoding="utf-8"))


def _path(n: int):
    return DIR / f"v{n}.json"


def _numbers() -> list[int]:
    if not DIR.exists():
        return []
    return sorted(int(p.stem[1:]) for p in DIR.glob("v*.json") if p.stem[1:].isdigit())


def snapshot() -> dict:
    year = active_year()
    return {"year": year, "items": load_rates(year), "caps": {k: _judge()[k]["value"] for k in CAPS}}


def init() -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    doc = {"version": 1, "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "by": "시스템", "note": "초기 기준(시연 시작 상태)", "changes": [], **snapshot()}
    _path(1).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def versions() -> list[dict]:
    if not _numbers():
        init()
    return [json.loads(_path(n).read_text(encoding="utf-8")) for n in _numbers()]


def current() -> dict:
    return versions()[-1]


def label() -> str:
    c = current()
    return f"v{c['version']} ({c['year']}년 기준, {c['at'][:16]})"


def _fmt(key: str, v) -> str:
    if key in CAPS:
        return f"{v:.0%}"
    return f"{v:,}원" if rates.REQUIRED.get(key) == "money" else f"{v * 100:.3f}".rstrip("0").rstrip(".") + "%"


def diff(old: dict, new: dict) -> list[dict]:
    out = [{"항목": rates.LABELS[k], "이전": _fmt(k, old["items"][k]["value"]), "변경": _fmt(k, new["items"][k]["value"])}
           for k in RATE_KEYS if old["items"][k]["value"] != new["items"][k]["value"]]
    names = {"overhead_cap": "일반관리비율 상한", "profit_cap": "이윤율 상한"}
    out += [{"항목": names[k], "이전": _fmt(k, old["caps"][k]), "변경": _fmt(k, new["caps"][k])} for k in CAPS if old["caps"][k] != new["caps"][k]]
    return out


def save_version(note: str, user=None) -> dict:
    """현재 적용 상태를 새 버전으로 남긴다. 바뀐 값이 없어도 기록한다(출처·고시일 수정 등)."""
    prev = current()
    snap = snapshot()
    doc = {"version": prev["version"] + 1, "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "by": user["name"] if isinstance(user, dict) else (user or "시스템"), "note": note, "changes": diff(prev, snap), **snap}
    _path(doc["version"]).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    text = ", ".join(f"{c['항목']} {c['이전']}→{c['변경']}" for c in doc["changes"]) or "값 변경 없음"
    audit.log("기준 변경", f"v{doc['version']} 저장({note}): {text}", user=user)
    return doc


def set_caps(user, overhead: float, profit: float) -> dict:
    """일반관리비율·이윤율 상한 변경(판정기준.json, 가정값)."""
    for name, v in (("일반관리비율", overhead), ("이윤율", profit)):
        if not 0 < v < 0.5:
            raise ValueError(f"{name} 상한은 0~50% 사이여야 합니다.")
    j = _judge()
    j["overhead_cap"]["value"], j["profit_cap"]["value"] = overhead, profit
    JUDGE.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
    return save_version("일반관리비율·이윤율 상한 변경", user)


def rollback(user, n: int) -> dict:
    """버전 n의 기준으로 되돌린다(새 버전으로 기록)."""
    old = json.loads(_path(n).read_text(encoding="utf-8"))
    doc = {"year": old["year"], "label": f"{old['year']}년(v{n}로 되돌림)", "items": old["items"]}
    rates._write(rates.PUBLISHED, doc)
    rates._write(rates.APPLIED, doc)
    j = _judge()
    for k in CAPS:
        j[k]["value"] = old["caps"][k]
    JUDGE.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
    return save_version(f"v{n}로 되돌림", user)


def reset() -> None:
    """시연 초기화: 버전 이력을 지우고 현재(초기) 기준을 v1로 다시 만든다. 판정 상한도 기본값으로."""
    j = _judge()
    j["overhead_cap"]["value"], j["profit_cap"]["value"] = 0.09, 0.10
    JUDGE.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(DIR, ignore_errors=True)
    init()


def panel(year: int | None = None) -> list[dict]:
    """이번 산출에 쓴 기준. 값은 단가 파일·판정기준 파일에서 읽는다."""
    year = year or active_year()
    it = load_rates(year)
    j = _judge()
    pr = lambda v: f"{v * 100:.3f}".rstrip("0").rstrip(".") + "%"
    src = lambda k: f"{it[k].get('announced', '')} · {it[k].get('source', '')}".strip(" ·")
    rows = [
        ("기준①", "적용 연도·기준 버전", f"{year}년 · {label()}", f"{standards()['years'][str(year)]['label'] if str(year) in standards()['years'] else ''}"),
        ("기준②", "시중노임단가(단순노무, 일급)", f"{it['market_daily']['value']:,}원", src("market_daily") + f" · {rates.status_label(it['market_daily'])}"),
        ("기준③", "최저임금(시급)", f"{it['min_wage']['value']:,}원", src("min_wage")),
        ("기준④", "국민연금(사용자)", pr(it["pension"]["value"]), src("pension")),
        ("기준⑤", "건강보험(사용자)", pr(it["health"]["value"]), src("health")),
        ("기준⑥", "장기요양(건강보험료 대비, 법정)", pr(it["ltc"]["value"]), src("ltc")),
        ("기준⑦", "고용보험(사업주)·산재보험·임금채권보장", f"{pr(it['employment_employer']['value'])} · {pr(it['industrial']['value'])} · {pr(it['wage_claim']['value'])}",
         src("employment_employer")),
        ("기준⑧", "월 소정근로시간", f"{standards()['monthly_hours']}시간", "주 40시간 + 주휴 8시간을 월로 환산(근로기준법 제55조)"),
        ("기준⑨", "일반관리비율·이윤율 상한", f"{j['overhead_cap']['value']:.0%} · {j['profit_cap']['value']:.0%}", "지방계약법 시행규칙 제8조 · 판정기준(가정)"),
        ("기준⑩", "판정 허용 범위(미달·과지급)", f"{j['tolerance']['value']:.0%}", "가정, 공단 기준 확인 후 교체"),
        ("기준⑪", "낙찰률", f"{DEFAULT_AWARD_RATE:.3%}", "지침 5-3 시설분야 단순노무용역 낙찰하한율(계약 가정값)"),
        ("기준⑫", "적용 지침 조항", "5-2 · 5-2-c · 5-3 · 5-5-3 · 6-2-2", CLAUSES["5-2-a"][0] + " 외"),
    ]
    return [{"번호": a, "기준": b, "값": c, "근거·공표일": d} for a, b, c, d in rows]
