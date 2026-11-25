"""보호지침 질의응답. 앱 안에서 지침 원문을 검색해 조항과 함께 그대로 보여 준다.

문장을 새로 만들지 않고 외부 AI API도 쓰지 않는다. 질문 원문은 저장하지 않는다.
"""
from __future__ import annotations

import re
import zipfile
from functools import lru_cache

from lxml import etree
from sklearn.feature_extraction.text import TfidfVectorizer

from .data import source_file

EXAMPLES = ["낙찰하한율이 얼마야?", "수의계약이면 낙찰률 적용해도 돼?", "도급 계약기간은 몇 년 이상이야?",
            "임금명세서는 언제 제출해?", "고용승계 예외 사유는?", "노임단가가 오르면 계약금액을 조정해야 해?"]
MIN_SCORE = 0.08
HEADING = re.compile(r"^([1-8]-[0-9](?:-[0-9])?)\.?\s*(.+)$")
ATTACHMENT = re.compile(r"^【붙임\s*([0-9])】$")
JOSA = ("에서는", "으로는", "이면", "하면", "에는", "에서", "으로", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "에", "도", "로", "만", "와", "과")
STOP = {"얼마", "얼마야", "언제", "어떻게", "무엇", "뭐야", "뭐", "해야", "해도", "돼", "되나", "되나요", "알려줘", "알려", "주세요", "있어", "있나요", "이야", "몇", "년", "이상",
        "이상이야", "사유는", "방법", "추천", "추천해줘", "하나요", "해", "오르면", "적용해도", "조정해야", "제출해", "오늘", "어때", "좀", "그럼", "지금"}
SYNONYMS = {"명세서": "임금지급명세서 분기별 제출", "계약기간": "도급계약 기간 2년 이상 보장", "승계": "고용유지 고용승계 특별한 사정", "하한": "낙찰하한율",
            "오르면": "인상 변경 조정", "조정": "노무비 조정 계약 반영"}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _section_number(name: str) -> int:
    return int(re.search(r"section([0-9]+)\.xml", name).group(1))


@lru_cache(maxsize=1)
def passages() -> tuple[dict, ...]:
    """지침 본문 문단을 조항 제목과 함께 읽는다. 표 안의 문단은 한 번만 쓴다."""
    out, seen = [], set()
    clause, title = "", ""
    with zipfile.ZipFile(source_file("보호지침")) as z:
        names = sorted((n for n in z.namelist() if re.search(r"Contents/section[0-9]+\.xml", n)), key=_section_number)
        for name in names:
            for p in etree.fromstring(z.read(name)).iter("{*}p"):
                if p.find(".//{*}p") is not None:
                    continue
                text = _clean("".join(t.text or "" for t in p.iter("{*}t")))
                if not text:
                    continue
                attached = ATTACHMENT.match(text)
                if attached:
                    clause, title = f"붙임 {attached.group(1)}", ""
                    continue
                if clause.startswith("붙임") and not title:
                    title = text
                    continue
                heading = HEADING.match(text)
                if heading and len(text) <= 40:
                    clause, title = heading.group(1), heading.group(2)
                    continue
                if not clause or len(text) < 15 or text in seen:
                    continue
                seen.add(text)
                out.append({"조항": clause, "제목": title, "원문": text})
    return tuple(out)


@lru_cache(maxsize=1)
def _index():
    docs = [f"{x['제목']} {x['원문']}" for x in passages()]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
    return vectorizer, vectorizer.fit_transform(docs)


def keywords(question: str) -> list[str]:
    out = []
    for word in re.findall(r"[가-힣A-Za-z0-9]+", question):
        if word in STOP:
            continue
        for josa in JOSA:
            if word.endswith(josa) and len(word) - len(josa) >= 2:
                word = word[: -len(josa)]
                break
        if len(word) >= 2 and word not in STOP:
            out.append(word)
    return out


def answer(question: str, top: int = 3) -> dict:
    """관련 원문을 최대 top개 돌려준다. 근거가 약하면 찾지 못했다고 답한다."""
    words = keywords(question)
    if not words:
        return {"found": False, "matches": []}
    expanded = " ".join(words + [v for k, v in SYNONYMS.items() if k in question])
    vectorizer, matrix = _index()
    scores = (matrix @ vectorizer.transform([expanded]).T).toarray().ravel()
    terms = set(words) | {x for k, v in SYNONYMS.items() if k in question for x in v.split()}
    ranked = []
    for i, score in enumerate(scores):
        item = passages()[i]
        haystack = f"{item['제목']} {item['원문']}".replace(" ", "")
        hits = sum(term in haystack for term in terms)
        if not hits or score < MIN_SCORE:
            continue
        title = item["제목"].replace(" ", "")
        title_hits = sum(term in title for term in terms) + ("예외" in question and "예외" in title)
        weight = (1 + 0.15 * min(hits, 4)) * (1 + 0.8 * min(title_hits, 2)) * (0.8 if item["조항"].startswith("붙임") else 1)
        ranked.append((score * weight, i))
    ranked.sort(reverse=True)
    # 가장 관련 있는 조항 top개를 고르고, 조항마다 핵심 문단을 최대 2개 원문 순서로 보여 준다
    chosen: dict[str, list[tuple[float, int]]] = {}
    for score, i in ranked:
        clause = passages()[i]["조항"]
        if clause not in chosen and len(chosen) == top:
            continue
        if len(chosen.setdefault(clause, [])) < 2:
            chosen[clause].append((score, i))
    matches = [{**passages()[i], "관련도": round(float(score), 3)} for group in chosen.values() for score, i in sorted(group, key=lambda x: x[1])]
    return {"found": bool(matches), "matches": matches}
