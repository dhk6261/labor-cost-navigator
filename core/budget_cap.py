"""총인건비 한도(참고 기능). 기준값은 data/총인건비_기준.json의 시연용 가정값이다.

예상액 = 2026년 직영 실적(가정) × (1+호봉 상승률) + 2026년 기간제 실적(가정) × 2027 급여 재산출 비율
       + (직영+기간제) × 사업주 4대보험 요율 변화분
[실제 도입 시 연결 지점] load_config()의 인상률을 행정안전부 지방공기업 예산편성기준 값으로 교체한다.
"""
from __future__ import annotations

import json

from .calc import calc_payroll, employer_insurance_rate, payroll_total
from .data import DATA, rate_values

CONFIG = DATA / "총인건비_기준.json"
WARN_LEVEL = 0.97
NORMAL, CAUTION, OVER = "정상", "주의", "초과"
YEAR = 2027


class CapError(ValueError):
    """기준 파일 문제."""


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        base, rate = float(cfg["base_total"]["value"]), float(cfg["rate"]["value"])
        int(cfg["base_year"])
        direct, temp = float(cfg["base_actual"]["직영"]), float(cfg["base_actual"]["기간제"])
        step = float(cfg["step"]["value"])
        scope, exclude = cfg["scope"], cfg["exclude"]["value"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise CapError(f"총인건비_기준.json을 읽을 수 없습니다: {type(e).__name__}") from e
    if base <= 0 or direct <= 0 or temp <= 0 or not -0.2 <= rate <= 0.5 or not 0 <= step <= 0.2 or not isinstance(exclude, list) or not scope.get("value"):
        raise CapError("총인건비_기준.json의 값 범위를 확인하세요(기준액·실적 양수, 인상률 -20~50%, 호봉 0~20%)")
    return cfg


def level_of(usage: float) -> str:
    return OVER if usage > 1 else CAUTION if usage >= WARN_LEVEL else NORMAL


def expected_2027(cfg: dict, values: dict | None = None) -> float:
    """2027년 직영+기간제 예상액(가정값 기반 참고치)."""
    r0, r1 = rate_values(2026), values or rate_values(YEAR)
    direct = cfg["base_actual"]["직영"] * (1 + cfg["step"]["value"])
    temp = cfg["base_actual"]["기간제"] * payroll_total(calc_payroll(r1)) / payroll_total(calc_payroll(r0))
    wages = direct + temp
    return wages + wages * (employer_insurance_rate(r1) - employer_insurance_rate(r0))


def evaluate(values: dict | None = None) -> dict:
    """2027년 한도·예상액·사용률."""
    cfg = load_config()
    limit = cfg["base_total"]["value"] * (1 + cfg["rate"]["value"]) ** (YEAR - cfg["base_year"])
    expected = expected_2027(cfg, values)
    usage = expected / limit
    return {"config": cfg, "연도": YEAR, "한도": limit, "예상액": expected, "여유액": limit - expected, "사용률": usage, "상태": level_of(usage)}
