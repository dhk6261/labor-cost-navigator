import pandas as pd
import streamlit as st

from core import auth, audit, ui

user = ui.guard(auth.ADMIN)
ui.page("이력 로그", "기업·관리자의 로그인, 등록, 수정, 보완 요청, 승인, 파일 업로드, 추출, 정정, 검수, 문서 생성, 기준 변경 기록을 시각·사용자·업체·회차와 함께 남깁니다.")
rows = audit.read_log()
if not rows:
    st.info("아직 기록이 없습니다.")
    st.stop()
df = pd.DataFrame(rows, columns=audit.FIELDS)
c = st.columns(4)
c[0].metric("전체 기록", f"{len(df)}건")
c[1].metric("등록 · 승인 · 보완 요청", f"{(df['기능'] == '착수계 등록').sum()} · {(df['기능'] == '승인').sum()} · {(df['기능'] == '보완 요청').sum()}")
c[2].metric("문서 생성", f"{df['기능'].isin(['문서 생성', '착수계 생성']).sum()}건")
c[3].metric("최근 기록", df.iloc[0]["시각"][5:16])

f = st.columns(5)
filters = {}
for col, field in zip(f, ("기능", "사용자", "역할", "업체", "회차")):
    options = sorted(x for x in df[field].unique() if x)
    filters[field] = col.multiselect(field, options, key=f"log_{field}")
view = df
for field, pick in filters.items():
    if pick:
        view = view[view[field].isin(pick)]
st.dataframe(view, hide_index=True, width="stretch", height=480)
a, b, _ = st.columns([1, 1, 3])
a.download_button("CSV 다운로드", view.to_csv(index=False).encode("utf-8-sig"), "history.csv", "text/csv", width="stretch", key="log_csv")
b.button("리허설 기록 비우기", on_click=audit.clear_log, width="stretch", key="clear_log")
