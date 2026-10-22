"""소비 습관 분석기 - 실행: streamlit run app.py"""
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import analysis as an

DATA_DIR = Path(__file__).parent / "data"
NONE_CHOICE = "(선택 안 함)"

st.set_page_config(page_title="소비 습관 분석기", page_icon="💳", layout="wide")


def data_files():
    files = sorted(p for p in DATA_DIR.glob("*.csv"))
    files += sorted(p for p in (DATA_DIR / "오류").glob("*.csv"))
    return {str(p.relative_to(DATA_DIR)).replace("\\", "/"): p for p in files}


def pick_source(label: str, key: str, optional: bool):
    """(파일 이름, bytes) 또는 None. 원본은 읽기만 한다."""
    mode = st.sidebar.radio(label, ["data 폴더에서 선택", "직접 업로드"], key=f"{key}_mode", horizontal=True)
    if mode == "직접 업로드":
        up = st.sidebar.file_uploader(label, type="csv", key=f"{key}_up", label_visibility="collapsed")
        return (up.name, up.getvalue()) if up else None
    files = data_files()
    options = ([NONE_CHOICE] if optional else []) + list(files)
    default = 0 if optional else None
    name = st.sidebar.selectbox(label, options, index=default, key=f"{key}_sel",
                                placeholder="CSV를 선택하세요", label_visibility="collapsed")
    if name is None or name == NONE_CHOICE:
        return None
    return name, files[name].read_bytes()


def show_errors(title: str, errors: list):
    st.error(title)
    rows = [{"CSV 줄 번호": "-" if n is None else n, "이유": why} for n, why in errors]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def won_axis(title="금액(원)"):
    return alt.Axis(title=title, format=",.0f")


# st.metric 은 값이 칸보다 길면 '...' 으로 잘리므로, 잘리지 않고 줄바꿈되게 한다.
st.markdown(
    """
    <style>
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] > div,
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] > div,
    [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] > div {
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: normal !important;
        word-break: keep-all;
    }
    [data-testid="stMetricValue"] { font-size: clamp(1.3rem, 2.2vw, 2.25rem); line-height: 1.2; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("💳 소비 습관 분석기")
st.sidebar.header("1. 파일")
expense_src = pick_source("지출 CSV", "exp", optional=False)
budget_src = pick_source("월별 예산 CSV (선택)", "bud", optional=True)

if expense_src is None:
    st.info("왼쪽에서 지출 CSV를 선택하세요. 지출 내역을 읽어 월·카테고리별로 보여 드립니다.")
    st.stop()

file_name, raw = expense_src
parsed = an.parse_expenses(raw)

if parsed.status == "error":
    show_errors(f"{file_name}: 분석을 멈췄습니다. 아래 문제를 고친 뒤 다시 선택하세요.", parsed.errors)
    st.stop()
if parsed.status == "empty":
    st.warning(f"{file_name}: 거래 없음 - 머리글만 있고 지출 내역이 없습니다.")
    st.stop()

df = parsed.df
months = an.months_of(df)

# 이전 선택이 새 파일에 없으면 가장 최근 달로 되돌린다.
if st.session_state.get("month") not in months:
    st.session_state["month"] = months[-1]
if st.session_state.get("category") not in ["전체"] + an.CATEGORIES:
    st.session_state["category"] = "전체"

st.sidebar.header("2. 조회 범위")
month = st.sidebar.selectbox("월", months, key="month")
category = st.sidebar.selectbox("카테고리", ["전체"] + an.CATEGORIES, key="category")

sub = an.select_range(df, month, category)
scope = f"{month} · {category}"

st.caption(f"📄 {file_name} · 정상 거래 {len(df):,}건")

# ---- 월 전체 예산 현황 (카테고리와 무관) ----
st.subheader(f"월 전체 예산 현황 · {month}")
budgets, budget_errors = {}, []
if budget_src:
    budgets, budget_errors = an.parse_budget(budget_src[1])
if budget_errors:
    show_errors(f"{budget_src[0]}: 예산 파일 오류 - 예산 계산만 멈추고 지출 분석은 계속합니다.", budget_errors)
elif budget_src is None:
    st.info("월별 예산 CSV를 고르면 예산 대비 사용 현황이 여기에 표시됩니다.")
else:
    bs = an.budget_status(budgets, df, month)
    c = st.columns(4)
    if not bs.registered:
        c[0].metric("월 예산", "예산 미등록")
        c[1].metric("월 전체 지출", an.format_won(bs.spent))
        c[2].metric("남은 예산", "-")
        c[3].metric("사용률", "-")
    else:
        c[0].metric("월 예산", an.format_won(bs.budget))
        c[1].metric("월 전체 지출", an.format_won(bs.spent))
        if bs.over:
            c[2].metric("초과액", an.format_won(-bs.remaining), "초과", delta_color="inverse")
        else:
            c[2].metric("남은 예산", an.format_won(bs.remaining), "남음")
        c[3].metric("사용률", bs.rate_text)
        if bs.budget > 0:
            st.progress(min(bs.rate_ratio, 1.0))
            if bs.over:
                st.error(f"예산을 {an.format_won(-bs.remaining)} 초과했습니다 (사용률 {bs.rate_text}).")

# ---- 선택 범위 ----
st.subheader(f"선택 범위 · {scope}")
m = st.columns(2)
m[0].metric("거래 건수", f"{len(sub):,}건")
m[1].metric("총지출", an.format_won(int(sub["금액_원"].sum())))

if sub.empty:
    st.info("선택한 조건의 지출이 없습니다.")
else:
    left, right = st.columns(2)

    cat = an.category_totals(sub)
    with left:
        st.markdown("**카테고리별 지출**")
        bar = alt.Chart(cat).mark_bar().encode(
            x=alt.X("카테고리:N", sort=cat["카테고리"].tolist(), axis=alt.Axis(labelAngle=0)),
            y=alt.Y("금액_원:Q", axis=won_axis()),
            tooltip=["카테고리", alt.Tooltip("금액_원:Q", title="금액(원)", format=",.0f")],
        )
        st.altair_chart(bar, width="stretch")
        if category != "전체":
            st.caption("카테고리를 비교하려면 '전체'를 선택하세요.")

    daily = an.daily_totals(sub, month)
    with right:
        st.markdown("**일별 지출 추이**")
        line = alt.Chart(daily).mark_bar().encode(
            x=alt.X("일자:T", axis=alt.Axis(title="날짜", format="%m-%d")),
            y=alt.Y("금액_원:Q", axis=won_axis()),
            tooltip=[alt.Tooltip("일자:T", title="날짜", format="%Y-%m-%d"),
                     alt.Tooltip("금액_원:Q", title="금액(원)", format=",.0f")],
        )
        st.altair_chart(line, width="stretch")

# ---- 월별 추이 (참고) ----
st.markdown("**월별 총지출 추이** (전체 카테고리)")
mt = an.monthly_totals(df)
mt["선택"] = mt["월"] == month
trend = alt.Chart(mt).mark_bar().encode(
    x=alt.X("월:N", axis=alt.Axis(labelAngle=0)),
    y=alt.Y("금액_원:Q", axis=won_axis()),
    color=alt.Color("선택:N", legend=None, scale=alt.Scale(domain=[True, False], range=["#2563eb", "#9ca3af"])),
    tooltip=["월", alt.Tooltip("금액_원:Q", title="금액(원)", format=",.0f")],
)
st.altair_chart(trend, width="stretch")

# ---- 거래 표 ----
if not sub.empty:
    st.markdown("**거래 내역**")
    view = sub[["일자", "카테고리", "사용처", "금액_원"]].copy()
    view["일자"] = view["일자"].map(lambda d: d.strftime("%Y-%m-%d"))
    view["금액"] = view["금액_원"].map(an.format_won)
    st.dataframe(view[["일자", "카테고리", "사용처", "금액"]], hide_index=True, width="stretch")
