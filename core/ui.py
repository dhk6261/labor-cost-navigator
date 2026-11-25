"""화면 공통 요소."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import audit, auth, basis, calculator, mapping, rates, review, startup, virtual
from .data import DATA, active_year, default_births, load_births, save_births
from .validate import run_validation

INK, SUB, LINE, NAVY, BLUE = "#1E2124", "#5A6472", "#D6DBE3", "#0F2B52", "#0B50D0"
RED = "background-color:#FDECEC;color:#B42318;font-weight:700"
ORANGE = "background-color:#FFF0E3;color:#9A3412;font-weight:700"
AMBER = "background-color:#FFF7DB;color:#7A5200;font-weight:600"
PURPLE = "background-color:#F1EAFD;color:#6B21A8;font-weight:700"
GRAY = "background-color:#F1F3F5;color:#6B7280;font-style:italic"
STATUS_STYLE = {"미달": RED, "누락": ORANGE, "과지급": PURPLE, "확인 필요": AMBER, "보완 요청": RED, "등록됨": AMBER,
                "재검수 필요": RED, "기준 변경으로 재검수 필요": RED, "검수 대기": AMBER}
TONE = {"미달": "red", "누락": "orange", "과지급": "violet", "확인 필요": "yellow", "보완 요청": "red", "등록됨": "blue", "임시저장": "gray",
        "승인": "green", "검수 완료": "green", "검수 대기": "yellow", "재검수 필요": "red", "기준 변경으로 재검수 필요": "red", "산출": "blue"}
SECTIONS = {"대시보드": "현황", "착수계 등록·관리": "착수계·산출", "금액 산출 계산기": "착수계·산출", "오류·근거 검증": "산출·검증",
            "엑셀 점검 · 수정본": "산출·검증", "유형별 산출 · 근태": "산출·검증", "기준 관리 · 재산출": "산출·검증", "보호지침 점검": "산출·검증",
            "문서 초안 생성": "업무 지원", "이력 로그": "업무 지원"}
ORG = "○○시설관리공단"
SYSTEM = "인건비 산출·관리시스템"

CSS = """<style>
:root{--ink:#1E2124;--sub:#5A6472;--line:#D6DBE3;--navy:#0F2B52;--blue:#0B50D0;--bg:#F4F6F9}
header[data-testid="stHeader"]{background:transparent;height:2.2rem}
.block-container{padding-top:1.1rem;padding-bottom:3rem;max-width:1380px}
h1{font-size:1.6rem!important;font-weight:800!important;letter-spacing:-.02em;color:var(--ink);padding:.15rem 0 .55rem!important;
   border-bottom:2px solid var(--ink);margin-bottom:.9rem!important}
h2,h3{letter-spacing:-.01em;font-weight:700!important;color:var(--ink)}
h3{font-size:1.18rem!important;padding-top:.6rem!important}
h4{font-size:1.02rem!important;font-weight:700!important;color:var(--ink);border-left:4px solid var(--blue);padding:.05rem 0 .05rem .55rem!important;margin:1.1rem 0 .5rem!important}
h5{font-size:.95rem!important;font-weight:700!important;color:var(--navy)}
[data-testid="stCaptionContainer"]{color:var(--sub)}
/* 상단 기관 바·경로 */
.gov-top{display:flex;justify-content:space-between;align-items:center;background:var(--navy);color:#fff;border-radius:4px;padding:9px 16px;margin-bottom:8px;font-size:.84rem}
.gov-top .org{display:flex;align-items:center;gap:10px;font-weight:700;letter-spacing:-.01em}
.gov-top .org small{font-weight:400;color:#B9C8DE;margin-left:2px}
.gov-top .meta{display:flex;gap:14px;color:#D5E0EF}
.gov-top .meta b{color:#fff;font-weight:700}
.gov-top .demo{background:#F5B700;color:#1E2124;border-radius:3px;padding:1px 7px;font-weight:800;font-size:.74rem}
.crumb{color:var(--sub);font-size:.82rem;margin:2px 0 4px}
.crumb b{color:var(--ink);font-weight:700}
.page-desc{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:4px;padding:10px 14px;color:#3A4350;font-size:.9rem;margin:-2px 0 14px;line-height:1.55}
.page-desc code{background:#EEF1F6;padding:0 4px;border-radius:3px;font-size:.84rem}
/* 카드·지표 */
[data-testid="stMetric"]{background:#fff;border:1px solid var(--line);border-top:3px solid var(--blue);border-radius:4px;padding:12px 14px}
[data-testid="stMetricLabel"]{color:var(--sub);font-weight:600}
[data-testid="stMetricValue"]{font-size:1.5rem;font-weight:800;color:var(--ink)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:4px 0 14px}
.kpi{background:#fff;border:1px solid var(--line);border-top:3px solid var(--blue);border-radius:4px;padding:11px 14px}
.kpi .l{color:var(--sub);font-size:.8rem;font-weight:600}
.kpi .v{font-size:1.55rem;font-weight:800;color:var(--ink);line-height:1.25;margin-top:2px}
.kpi .v small{font-size:.85rem;font-weight:600;color:var(--sub);margin-left:2px}
.kpi .s{color:var(--sub);font-size:.76rem;margin-top:2px}
.kpi.red{border-top-color:#C62828}.kpi.orange{border-top-color:#C2410C}.kpi.violet{border-top-color:#6B21A8}
.kpi.yellow{border-top-color:#D4A106}.kpi.green{border-top-color:#1B7F4B}.kpi.navy{border-top-color:var(--navy)}
.kpi.red .v{color:#B42318}.kpi.orange .v{color:#9A3412}.kpi.violet .v{color:#6B21A8}.kpi.yellow .v{color:#7A5200}
/* 상태 표시 */
.pill{display:inline-block;border-radius:3px;padding:1px 8px;font-size:.78rem;font-weight:700;border:1px solid transparent;margin-right:4px;vertical-align:middle}
.pill.blue{background:#E8F0FE;color:#0B50D0;border-color:#C5D8FB}.pill.red{background:#FDECEC;color:#B42318;border-color:#F6C9C9}
.pill.orange{background:#FFF0E3;color:#9A3412;border-color:#FAD3B4}.pill.violet{background:#F1EAFD;color:#6B21A8;border-color:#DCCBF7}
.pill.yellow{background:#FFF7DB;color:#7A5200;border-color:#F3DF9D}.pill.green{background:#E7F5EE;color:#1B7F4B;border-color:#BFE3CF}
.pill.gray{background:#F1F3F5;color:#4B5563;border-color:#DDE1E6}
.tag{display:inline-block;background:#FFF7DB;color:#7A5200;border:1px solid #F3DF9D;border-radius:3px;padding:1px 8px;font-size:.76rem;font-weight:700;margin-bottom:6px}
/* 업무 흐름 */
.flow{display:flex;gap:0;margin:2px 0 16px;background:#fff;border:1px solid var(--line);border-radius:4px;overflow:hidden}
.flow div{flex:1;padding:10px 12px;font-size:.84rem;color:var(--sub);border-right:1px solid var(--line);position:relative}
.flow div:last-child{border-right:none}
.flow div b{display:block;color:var(--ink);font-size:.9rem;margin-bottom:1px}
.flow div i{font-style:normal;display:inline-block;background:var(--navy);color:#fff;border-radius:50%;width:20px;height:20px;text-align:center;line-height:20px;font-size:.72rem;font-weight:800;margin-right:6px}
.notice{background:#fff;border:1px solid var(--line);border-radius:4px;padding:0}
.notice .h{background:#EEF2F8;border-bottom:1px solid var(--line);padding:8px 14px;font-weight:700;font-size:.9rem;color:var(--ink)}
.notice ul{margin:0;padding:8px 14px 10px 30px;font-size:.86rem;color:#3A4350;line-height:1.75}
/* 기본 위젯 다듬기 */
[data-testid="stExpander"] details{background:#fff;border-radius:4px}
[data-testid="stExpander"] summary{font-weight:600}
[data-testid="stVerticalBlockBorderWrapper"],[data-testid="stLayoutWrapper"]>div[style*="border"]{background:#fff}
[data-testid="stDataFrame"]{border-radius:4px}
.stButton button,.stDownloadButton button,[data-testid="stFormSubmitButton"] button{font-weight:600}
[data-baseweb="tab-list"]{border-bottom:1px solid var(--line)}
[data-baseweb="tab"]{font-weight:600}
[data-testid="stAlert"]{border-radius:4px}
/* 사이드바 */
[data-testid="stSidebar"] .sb-brand{display:flex;gap:10px;align-items:center;padding:4px 2px 12px;border-bottom:1px solid #2A4C7E;margin-bottom:10px}
[data-testid="stSidebar"] .sb-brand .t{font-weight:800;color:#fff;font-size:1rem;line-height:1.25}
[data-testid="stSidebar"] .sb-brand .s{color:#9FB4D3;font-size:.74rem}
[data-testid="stSidebarLogo"]{height:3.2rem!important;max-width:100%!important;width:auto!important}
[data-testid="stSidebarHeader"]{padding-bottom:.4rem;border-bottom:1px solid #2A4C7E;margin-bottom:.4rem}
[data-testid="stSidebar"] .sb-user{background:#173A69;border:1px solid #2A4C7E;border-radius:4px;padding:9px 11px;margin-bottom:8px;font-size:.84rem;color:#E6ECF5}
[data-testid="stSidebar"] .sb-user b{color:#fff;font-size:.92rem}
[data-testid="stSidebar"] .sb-user span{display:inline-block;background:#3D86FF;color:#fff;border-radius:3px;padding:0 6px;font-size:.72rem;font-weight:700;margin-left:4px}
[data-testid="stSidebar"] .sb-label{color:#9FB4D3;font-size:.74rem;font-weight:700;letter-spacing:.04em;margin:10px 0 4px}
/* 하단 */
.gov-foot{margin-top:36px;padding:14px 4px 0;border-top:1px solid var(--line);color:#7A8494;font-size:.76rem;line-height:1.6}
/* 로그인 */
.login-hero{background:linear-gradient(120deg,#0F2B52 0%,#173A69 60%,#1F4E8C 100%);color:#fff;border-radius:6px;padding:26px 28px;margin:6px 0 18px}
.login-hero .k{color:#9CC3FF;font-size:.82rem;font-weight:700;letter-spacing:.06em}
.login-hero h2{color:#fff!important;font-size:1.6rem!important;margin:.25rem 0 .35rem!important;padding:0!important;border:none!important}
.login-hero p{color:#D5E0EF;margin:0;font-size:.92rem;line-height:1.6}
</style>"""

EMBLEM = ("<svg width='30' height='30' viewBox='0 0 32 32' aria-hidden='true'><rect x='1' y='1' width='30' height='30' rx='5' fill='#3D86FF'/>"
          "<path d='M8 21h16M10 21v-7l6-4 6 4v7' stroke='#fff' stroke-width='2.2' fill='none' stroke-linejoin='round'/>"
          "<circle cx='16' cy='16.5' r='1.9' fill='#fff'/></svg>")


def _md(text: str) -> str:
    """간단한 마크다운(**굵게**, `코드`)을 HTML로."""
    import html
    import re
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def won(x) -> str:
    return "-" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:,.0f}원"


def top_bar() -> None:
    u = user()
    try:
        ver = basis.current()["version"]
    except Exception:  # 기준 이력이 아직 없을 때(첫 실행)도 화면은 그린다
        ver = 1
    who = f"<span><b>{u['name']}</b> · {auth.ROLE_LABEL[u['role']]}</span>" if u else "<span>로그인 전</span>"
    from .data import load_contracts
    st.markdown(f"<div class='gov-top'><div class='org'>{EMBLEM}<span>{ORG} <small>{SYSTEM}</small></span><span class='demo'>시연판</span></div>"
                f"<div class='meta'><span>기준일 <b>{load_contracts()['demo_today']}</b></span><span>적용 기준 <b>{active_year()}년 · v{ver}</b></span>{who}</div></div>",
                unsafe_allow_html=True)


def page(title: str, caption: str = "") -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    top_bar()
    section = SECTIONS.get(title)
    st.markdown(f"<div class='crumb'>홈 › {section + ' › ' if section else ''}<b>{title}</b></div>", unsafe_allow_html=True)
    st.title(title)
    if caption:
        st.markdown(f"<div class='page-desc'>{_md(caption)}</div>", unsafe_allow_html=True)


def pill(text: str, tone: str | None = None) -> str:
    return f"<span class='pill {tone or TONE.get(text, 'gray')}'>{text}</span>"


def kpis(items: list[tuple]) -> None:
    """(이름, 값, 단위, 보조 설명, 색) 카드 줄."""
    cards = "".join(f"<div class='kpi {tone}'><div class='l'>{l}</div><div class='v'>{v}<small>{u}</small></div><div class='s'>{s}</div></div>"
                    for l, v, u, s, tone in items)
    st.markdown(f"<div class='kpis'>{cards}</div>", unsafe_allow_html=True)


def flow(steps: list[tuple[str, str]]) -> None:
    st.markdown("<div class='flow'>" + "".join(f"<div><b><i>{i + 1}</i>{t}</b>{d}</div>" for i, (t, d) in enumerate(steps)) + "</div>",
                unsafe_allow_html=True)


def virtual_tag(text: str = "시연용 가상 데이터") -> None:
    st.markdown(f"<span class='tag'>{text}</span>", unsafe_allow_html=True)


def sidebar_brand() -> None:
    """사이드바 맨 위(메뉴 위) 로고. 그림 파일은 data/brand/(인터넷 없이 표시)."""
    st.logo(str(DATA / "brand" / "logo.svg"), size="large", icon_image=str(DATA / "brand" / "icon.svg"))
    st.markdown(CSS, unsafe_allow_html=True)


def sidebar_user(u: dict) -> None:
    st.markdown(f"<div class='sb-user'><b>{u['name']}</b><span>{auth.ROLE_LABEL[u['role']]}</span></div>", unsafe_allow_html=True)


def sidebar_label(text: str) -> None:
    st.markdown(f"<div class='sb-label'>{text}</div>", unsafe_allow_html=True)


def footer() -> None:
    st.markdown(f"<div class='gov-foot'>{ORG} {SYSTEM} · 시연판(가상 데이터 포함) · AI 문서 인식은 시스템 내부에서만 동작하며 파일은 외부로 전송되지 않습니다.<br>"
                "최종 산출물은 담당 관리자 검수 후에만 생성됩니다 · 계산 기준: 연도별 기준값·판정기준(가정) · 문의: 계약관리 담당 부서</div>", unsafe_allow_html=True)


def user() -> dict | None:
    return auth.current_user(st.session_state)


def guard(role: str | None = None) -> dict:
    """화면 입구 확인. 메뉴를 거치지 않고 페이지 파일이 바로 실행되어도 로그인·역할을 다시 확인한다(데이터 권한은 core에서 한 번 더 막는다)."""
    from streamlit.runtime.pages_manager import PagesManager
    if PagesManager.uses_pages_directory and not user():
        # 서버를 켠 뒤 첫 요청이 페이지 주소로 바로 들어오면 Streamlit이 옛 pages 폴더 방식으로 이 파일만 실행한다(새 세션이라 로그인 전).
        # 한 번만 끄고 다시 실행하면 app.py(메뉴·로그인·사이드바)부터 정상 실행된다.
        PagesManager.uses_pages_directory = False
        st.rerun()
    u = user()
    audit.set_actor(u)
    if not u or (role and u["role"] != role):
        st.markdown(CSS, unsafe_allow_html=True)
        st.warning("로그인이 필요하거나 이 화면을 볼 권한이 없습니다. 왼쪽 메뉴에서 로그인 화면으로 이동하세요.", icon=":material/lock:")
        if u:
            auth.deny(u, f"화면 접근 거부: {role} 전용")
        st.stop()
    return u


def safe_detect() -> tuple[list[dict], str | None]:
    try:
        return rates.detect_changes(), None
    except rates.RateError as e:
        return [], "공표단가.json 값 오류\n\n" + "\n".join(f"- {x}" for x in e.errors)
    except (ValueError, KeyError, OSError) as e:
        return [], f"공표단가.json을 읽을 수 없습니다: {type(e).__name__}"


@st.cache_data(show_spinner=False)
def _validated(year: int, demo: bool, births: tuple, stamp: float):
    return run_validation(year, demo, dict(births))


def current_births() -> dict:
    """화면에서 고친 값이 있으면 그 값, 없으면 저장된 가상 생년월일."""
    return st.session_state.get("birth_edits") or load_births()


def findings(demo: bool = False):
    stamp = (DATA / "적용단가.json").stat().st_mtime + (DATA / "contracts.yaml").stat().st_mtime
    return _validated(active_year(), demo, tuple(sorted(current_births().items())), stamp)


def log_on_change(key: str, feature: str, content: str) -> None:
    """같은 결과를 반복 기록하지 않는다. 첫 표시는 기록하지 않아 초기화 후 이력이 비어 있게 한다."""
    slot = f"logsig_{key}"
    previous = st.session_state.get(slot)
    st.session_state[slot] = content
    if previous is not None and previous != content:
        audit.log(feature, content)


def _fmt(v, sign: bool = False) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "없음"
    return f"{v:+,.0f}" if sign else f"{v:,.0f}"


def standard_table(rows: list[dict], show_reason: bool = True) -> None:
    """표준 산출서 표: 누락 주황 · 미달 빨강 · 과지급 보라 · 확인 필요 노랑, 소계 굵게, 오류 정정 필요 ☑."""
    df = pd.DataFrame(rows)
    sub = df["소계"].tolist()
    office_only = all(v is None or (isinstance(v, float) and pd.isna(v)) for v in df["업체 금액"])
    drop = ["소계"] + ([] if show_reason else ["사유"]) + (["업체 금액", "차이", "오류 정정 필요"] if office_only else [])
    view = df.drop(columns=drop)
    for col in ("업체 금액", "공단 산정 금액"):
        if col in view:
            view[col] = [_fmt(v) for v in df[col]]
    if "차이" in view:
        view["차이"] = [("" if v is None or pd.isna(v) else _fmt(v, True)) for v in df["차이"]]

    def style(frame):
        out = pd.DataFrame("", index=frame.index, columns=frame.columns)
        cols = [c for c in ("항목", "업체 금액", "차이", "상태") if c in frame]
        for i in frame.index:
            s = STATUS_STYLE.get(frame.loc[i, "상태"], "")
            if s:
                out.loc[i, cols] = s
            if not office_only:
                if frame.loc[i, "업체 금액"] == "없음" and not sub[i]:
                    out.loc[i, "업체 금액"] = GRAY
                mark = str(frame.loc[i, "오류 정정 필요"])
                if mark.startswith("☑"):
                    out.loc[i, "오류 정정 필요"] = RED
                elif mark.startswith("처리됨"):
                    out.loc[i, "오류 정정 필요"] = "color:#1B7F4B;font-weight:700"
            if sub[i]:
                out.loc[i, :] = "font-weight:700;background-color:#EEF3FA"
        return out

    st.dataframe(view.style.apply(style, axis=None), hide_index=True, width="stretch", height=min(38 + 35 * len(view), 990),
                 column_config={"업체 금액": st.column_config.TextColumn("업체 금액(1인·연간)"), "공단 산정 금액": st.column_config.TextColumn("금액(1인·연간)" if office_only else "공단 산정(1인·연간)"),
                                "산정기준·근거": st.column_config.TextColumn(width="large"), "산식": st.column_config.TextColumn(width="medium"),
                                "사유": st.column_config.TextColumn(width="large")})


def simple_table(rows: list[dict]) -> None:
    """근로 유형(프리랜서·아르바이트) 표: 구분 | 항목 | 금액 | 산식 | 적용 기준·근거 | 상태 | 사유."""
    df = pd.DataFrame(rows)
    sub = df["소계"].tolist()
    view = df.drop(columns=["소계"])
    view["금액"] = [_fmt(v) for v in df["금액"]]

    def style(frame):
        out = pd.DataFrame("", index=frame.index, columns=frame.columns)
        for i in frame.index:
            s = STATUS_STYLE.get(frame.loc[i, "상태"], "")
            if s:
                out.loc[i, ["항목", "금액", "상태"]] = s
            if sub[i]:
                out.loc[i, :] = "font-weight:700;background-color:#EEF3FA"
        return out

    st.dataframe(view.style.apply(style, axis=None), hide_index=True, width="stretch")


def counts_line(c: dict, pending: int | None = None) -> str:
    """표 안 요약 문구(색은 표 스타일이 담당)."""
    text = f"누락 {c['누락']} · 미달 {c['미달']} · 과지급 {c['과지급']} · 확인 필요 {c['확인 필요']}"
    return text + (f" · ☑ 정정 대기 {pending}" if pending is not None else "")


def badges(ev: dict) -> None:
    """요약 배지: 누락·미달·과지급·확인 필요·정정 대기."""
    c = ev["counts"]
    kpis([("누락", c["누락"], "건", "필수 항목 없음·0원", "orange"), ("미달", c["미달"], "건", "공단 산정보다 1% 넘게 적음", "red"),
          ("과지급", c["과지급"], "건", "많음·상한 초과·중복", "violet"), ("확인 필요", c["확인 필요"], "건", "확신도 낮음·옛 요율", "yellow"),
          ("오류 정정 대기", len(ev["pending"]), "건", "☑ 처리 전", "navy")])


def basis_panel(year: int | None = None, expanded: bool = True) -> None:
    """이번 산출에 쓴 기준(산정기준 패널)."""
    with st.expander(f"산정기준 패널 · {basis.label()}", expanded=expanded, icon=":material/rule:"):
        st.dataframe(pd.DataFrame(basis.panel(year)), hide_index=True, width="stretch")
        st.caption("표준 산출서의 '산정기준·근거' 칸 번호(기준②…)가 이 표의 행을 가리킵니다. 판정 허용 범위·상한은 가정값입니다(data/판정기준.json).")


def review_state(case: dict, ev: dict) -> str:
    s = review.state(case, ev)
    if s == review.RECHECK and case.get("recheck"):
        return "기준 변경으로 재검수 필요"
    return s


def correction_box(user: dict, case: dict, ev: dict, key_prefix: str) -> None:
    """오류 정정 필요(☑) 행 처리: 정정 완료(값 수정) 또는 정정 불필요(사유)."""
    if not ev["pending"]:
        st.success("오류 정정 대기 항목이 없습니다.")
        return
    st.markdown(f"##### ☑ 오류 정정 필요 {len(ev['pending'])}건")
    for key in ev["pending"]:
        gi, item = int(key.split(":")[0][1:]), key.split(":", 1)[1]
        g = ev["groups"][gi]
        info = g["check"]["items"][item]
        with st.container(border=True):
            a, b, c, d = st.columns([2.2, 1.2, 2.2, 1])
            a.markdown(f"**{item}** · {info['상태']}" + (f" · {g['label']}" if len(ev["groups"]) > 1 else ""))
            a.caption(" / ".join(info["사유"]))
            locked = bool(case.get("locked"))
            mode = b.radio("처리", ["정정 완료", "정정 불필요"], key=f"{key_prefix}_mode_{key}", label_visibility="collapsed",
                           index=1 if locked else 0, disabled=locked)
            if mode == "정정 완료":
                value = c.number_input("고친 값(원)", 0, 10**10, int(round(g["office"][item])), key=f"{key_prefix}_val_{key}")
                reason = ""
            else:
                value, reason = None, c.text_input("사유", key=f"{key_prefix}_why_{key}")
            if d.button("처리", key=f"{key_prefix}_do_{key}", disabled=mode == "정정 불필요" and not reason.strip()):
                try:
                    review.correct(user, case, key, mode, value, reason)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def review_box(user: dict, case: dict, ev: dict, key_prefix: str) -> bool:
    """검수 체크리스트. 모두 체크해야 '검수 완료'가 켜진다. 반환: 검수 완료 여부."""
    if review.is_valid(case, ev):
        st.success(f"{review.stamp(case)} · {case['review']['summary']}")
        return True
    if case.get("review"):
        st.warning("검수 후 값이나 기준이 바뀌어 검수가 풀렸습니다. 다시 검수하세요.", icon=":material/autorenew:")
    st.markdown("##### 사람 검수 체크리스트")
    checks = {c: st.checkbox(c, key=f"{key_prefix}_chk_{i}") for i, c in enumerate(review.CHECKLIST)}
    if ev["pending"]:
        st.caption(f"오류 정정 대기 {len(ev['pending'])}건을 먼저 처리해야 검수를 마칠 수 있습니다.")
    if ev["unconfirmed"]:
        st.caption(f"확신도 낮은 추출값 {len(ev['unconfirmed'])}개를 먼저 확인해야 합니다.")
    ready = all(checks.values()) and not ev["pending"] and not ev["unconfirmed"]
    if st.button("검수 완료", type="primary", key=f"{key_prefix}_done", disabled=not ready):
        try:
            review.complete(user, case, checks)
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    return False


RESET_KEYS = ("qa_result", "birth_edits", "birth_editor", "demo", "rate_sig", "rate_saved", "scenario_step", "scenario", "sev", "who", "seed",
              auth.SESSION_KEY)
RESET_PREFIXES = ("repair_", "s_", "logsig_", "st_", "reg_", "calc_", "w_", "type_", "doc_", "log_", "f_", "rv_", "cr_")


def reset_demo() -> None:
    """기준(버전 이력 포함), 생년월일, 등록물(B의 v1만), 계산기 회차, 정정·검수 기록, 추출 보조값, 세션 로그인, 이력 로그를 처음 상태로."""
    rates.reset()
    basis.reset()
    save_births(default_births())
    virtual.ensure(force=True)
    auth.clear_companies()
    calculator.clear()
    startup.seed_demo()
    mapping.clear_overrides()
    review.clear_docs()
    audit.clear_log()
    audit.STATE.unlink(missing_ok=True)
    for k in list(st.session_state.keys()):
        if k in RESET_KEYS or str(k).startswith(RESET_PREFIXES):
            del st.session_state[k]
    st.cache_data.clear()


@st.fragment(run_every=3)
def watch_rates() -> None:
    """공표단가.json이 바뀌면 전체 화면을 다시 그린다."""
    sig = str(safe_detect())
    if st.session_state.setdefault("rate_sig", sig) != sig:
        st.session_state["rate_sig"] = sig
        st.rerun(scope="app")


def login_page() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    top_bar()
    st.markdown(f"<div class='login-hero'><div class='k'>{ORG} · 업무지원시스템</div><h2>{SYSTEM}</h2>"
                "<p>기업이 등록한 착수계와 업체 산출내역을 시스템 내부 AI가 읽어 공단 표준 양식으로 산출·검증하고,<br>"
                "담당 관리자 검수를 거쳐 착수계 서류까지 만듭니다.</p></div>", unsafe_allow_html=True)
    st.title("인건비 내비게이터 로그인")
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### 로그인")
            with st.form("login_form", border=False):
                uid = st.text_input("아이디", key="f_login_id", placeholder="아이디를 입력하세요")
                pw = st.text_input("비밀번호", type="password", key="f_login_pw", placeholder="비밀번호를 입력하세요")
                ok = st.form_submit_button("로그인", type="primary", width="stretch")
            if ok:
                if auth.sign_in(st.session_state, uid, pw):
                    st.rerun()
                st.error("아이디 또는 비밀번호가 맞지 않습니다.", icon=":material/error:")
            st.caption("회원가입 기능은 없습니다. 실제 도입 시 공단 통합인증(SSO 등)으로 교체합니다.")
    with right:
        st.markdown("<div class='notice'><div class='h'>시연 계정 안내</div></div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(auth.demo_accounts()), hide_index=True, width="stretch")
        st.markdown(f"<div class='notice'><div class='h'>공지사항</div><ul>"
                    f"<li>시연 계정 비밀번호는 모두 <b>{auth.DEMO_PASSWORD}</b>이며, 파일에는 솔트 해시만 저장합니다.</li>"
                    "<li>관리자 계정 하나만으로도 처음부터 끝까지 작업할 수 있습니다.</li>"
                    "<li>왼쪽 메뉴의 <b>시연 시나리오</b>는 필요한 계정 전환을 자동으로 합니다.</li>"
                    "<li>화면의 기업·계약·파일은 시연용 가상 데이터입니다.</li></ul></div>", unsafe_allow_html=True)
