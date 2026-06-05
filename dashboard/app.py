"""
dashboard/app.py - Auto-Trader 모니터링 대시보드

실행: streamlit run dashboard/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import datetime, date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from dashboard.data import (
    load_trades, load_today_trades, load_pool_cache, load_pool_cache_us,
    get_factor_data, load_research, load_runner_log,
    load_regime, load_regime_history,
    compute_portfolio_curve, compute_stats, per_code_stats,
    load_portfolio_snapshots, load_trailing_stops,
)

# ── 페이지 기본 설정 ──────────────────────────────────────────
st.set_page_config(
    page_title="Auto-Trader",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 공통 CSS ─────────────────────────────────────────────────
st.markdown("""
<style>
/* 메트릭 카드 */
[data-testid="metric-container"] {
    background: #1A1F2E;
    border: 1px solid #2A3050;
    border-radius: 10px;
    padding: 14px 18px;
}
/* 사이드바 */
section[data-testid="stSidebar"] {
    background: #111827;
}
/* 테이블 헤더 */
thead tr th { background: #1A1F2E !important; }
/* 양수 손익 색 */
.profit-pos { color: #00D4AA; font-weight: 600; }
.profit-neg { color: #FF6B6B; font-weight: 600; }
/* 상태 뱃지 */
.badge-bull { background:#003322; color:#00D4AA; padding:4px 10px; border-radius:12px; font-size:0.85rem; }
.badge-bear { background:#330000; color:#FF6B6B; padding:4px 10px; border-radius:12px; font-size:0.85rem; }
.badge-grey { background:#222; color:#aaa; padding:4px 10px; border-radius:12px; font-size:0.85rem; }
/* 구분선 */
hr { border-color: #2A3050 !important; }
</style>
""", unsafe_allow_html=True)


# ── 색상 팔레트 ────────────────────────────────────────────────
GREEN = "#00D4AA"
RED   = "#FF6B6B"
BLUE  = "#4C8DFF"
GREY  = "#6B7280"


# ── 사이드바 네비게이션 ───────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 Auto-Trader")
    st.markdown(f"<small style='color:#888'>업데이트: {datetime.now().strftime('%H:%M:%S')}</small>",
                unsafe_allow_html=True)
    st.markdown("---")
    page = st.radio(
        "화면 선택",
        ["📊 메인 대시보드", "📈 분석", "📋 거래 이력", "📜 로그 & 캐시"],
        label_visibility="collapsed",
    )
    st.markdown("---")

    # 자동 새로고침 (메인 페이지만)
    if page == "📊 메인 대시보드":
        interval = st.selectbox("자동 새로고침", [30, 60, 120, 300], index=1,
                                 format_func=lambda x: f"{x}초")
        st_autorefresh(interval=interval * 1000, key="main_refresh")
        st.caption(f"⏱ {interval}초마다 갱신")

    st.markdown("---")
    # 풀 캐시 상태
    pool = load_pool_cache()
    pool_date = pool.get("date", "-")
    pool_codes = pool.get("pool", [])
    st.markdown(f"**후보 풀** `{pool_date}`")
    st.markdown(f"KR: {len(pool_codes)}종목")
    pool_us = load_pool_cache_us()
    pool_us_codes = pool_us.get("pool", [])
    st.markdown(f"US: {len(pool_us_codes)}종목")


# ══════════════════════════════════════════════════════════════
# 📊 메인 대시보드
# ══════════════════════════════════════════════════════════════
if page == "📊 메인 대시보드":

    st.title("📊 대시보드")

    trades_all   = load_trades(days=90)
    trades_today = load_today_trades()
    stats        = compute_stats(trades_all)
    pool_data    = pool.get("universe_data", [])
    regime       = load_regime()

    # ── 상단 메트릭 ────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)

    total_pnl  = stats["total_pnl"]
    win_rate   = stats.get("win_rate", 0)
    sell_cnt   = stats.get("sell_count", 0)

    col1.metric("💰 누적 실현손익", f"₩{total_pnl:+,.0f}",
                delta=f"매도 {sell_cnt}건" if sell_cnt else "거래 없음")
    col2.metric("🎯 승률", f"{win_rate:.1f}%",
                delta=f"전체 {sell_cnt}건 중 {int(sell_cnt*win_rate/100) if sell_cnt else 0}승")
    col3.metric("📅 오늘 거래", f"{len(trades_today)}건",
                delta=f"매수 {sum(1 for t in trades_today if t['action']=='BUY')} / "
                      f"매도 {sum(1 for t in trades_today if t['action']=='SELL')}")
    col4.metric("🗂 후보 풀", f"KR {len(pool_codes)}  US {len(pool_us_codes)}",
                delta=pool_date)

    # 시장 국면
    if regime:
        r_label = "🐂 BULL" if regime.get("is_bull") else "🐻 BEAR"
        r_delta = f"KOSPI {regime.get('kospi',0):,.0f} | SMA200 {regime.get('sma200',0):,.0f} ({regime.get('gap_pct',0):+.1f}%)"
        col5.metric("📡 시장 국면", r_label, delta=r_delta,
                    delta_color="normal" if regime.get("is_bull") else "inverse")
    else:
        col5.metric("📡 시장 국면", "데이터 없음", delta="장 시작 후 업데이트")

    st.markdown("---")

    # ── 2열 레이아웃 ───────────────────────────────────────────
    left, right = st.columns([3, 2])

    # 왼쪽: 팩터 상위 종목 (후보 풀)
    with left:
        st.subheader("🏆 팩터 상위 후보 풀")
        if pool_data:
            df_pool = pd.DataFrame(pool_data)
            cols_show = ["name", "code", "sector", "factor_score",
                         "ret_1m", "ret_3m", "ret_6m", "pos_52w", "vol_ratio"]
            cols_show = [c for c in cols_show if c in df_pool.columns]
            df_show = df_pool[cols_show].head(15).copy()
            df_show.columns = ["종목", "코드", "섹터", "팩터점수",
                                "1M%", "3M%", "6M%", "52주위치", "거래량비"][:len(cols_show)]

            # 팩터점수 컬러 스타일링
            def color_score(val):
                if isinstance(val, float) and val > 0.6:
                    return f"color: {GREEN}"
                elif isinstance(val, float) and val < 0.4:
                    return f"color: {RED}"
                return ""

            st.dataframe(
                df_show.style.map(color_score, subset=["팩터점수"] if "팩터점수" in df_show.columns else [])
                             .format({"팩터점수": "{:.3f}", "1M%": "{:+.1f}",
                                      "3M%": "{:+.1f}", "6M%": "{:+.1f}",
                                      "52주위치": "{:.0f}", "거래량비": "{:.2f}"},
                                     na_rep="-"),
                use_container_width=True,
                height=400,
            )
        else:
            st.info("아직 후보 풀 데이터가 없습니다. 장 시작 후 pool_cache.json이 생성됩니다.")

    # 오른쪽: 오늘 거래 + 리서치
    with right:
        st.subheader("📋 오늘의 거래")
        if trades_today:
            for t in reversed(trades_today[-8:]):
                action   = t["action"]
                emoji    = "🟢" if action == "BUY" else "🔴"
                pnl_str  = ""
                if action == "SELL" and t.get("profit_pct"):
                    pct = float(t["profit_pct"])
                    clr = GREEN if pct >= 0 else RED
                    pnl_str = f" | <span style='color:{clr}'>{pct:+.2f}%</span>"
                st.markdown(
                    f"{emoji} **{t['name']}** {int(t['price']):,}원 × {t['qty']}주"
                    f"<br><small style='color:#888'>{t['datetime'][11:16]}  {t.get('reason','')[:30]}</small>"
                    f"{pnl_str}",
                    unsafe_allow_html=True,
                )
                st.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
        else:
            st.info("오늘 거래 없음")

        # 글로벌 리서치
        st.subheader("🌐 글로벌 IB 리서치")
        research = load_research()
        if research.get("content"):
            st.markdown(f"<small style='color:#888'>📅 {research.get('date','-')}</small>",
                        unsafe_allow_html=True)
            st.markdown(
                f"<div style='background:#1A1F2E; border-radius:8px; padding:12px; "
                f"font-size:0.85rem; line-height:1.6; color:#DADADA'>"
                f"{research['content'].replace(chr(10), '<br>')}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("리서치 캐시 없음 (매일 장 시작 시 수집)")

    # ── 하단: 간략 수익 요약 바 ────────────────────────────────
    st.markdown("---")
    code_stats = per_code_stats(trades_all)
    if code_stats:
        st.subheader("💹 종목별 손익 요약")
        df_cs = pd.DataFrame(code_stats[:12])
        fig = px.bar(
            df_cs, x="name", y="pnl",
            color="pnl",
            color_continuous_scale=[[0, RED], [0.5, "#555"], [1, GREEN]],
            color_continuous_midpoint=0,
            labels={"name": "", "pnl": "손익(원)"},
            text=df_cs["avg_pct"].apply(lambda x: f"{x:+.1f}%"),
            height=220,
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False, coloraxis_showscale=False,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(tickfont=dict(size=11)),
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════
# 📈 분석
# ══════════════════════════════════════════════════════════════
elif page == "📈 분석":

    st.title("📈 분석")

    trades_all = load_trades(days=180)
    pool_data  = get_factor_data()

    tab1, tab2, tab3, tab4 = st.tabs(["팩터 스코어", "포트폴리오 커브", "섹터 분포", "시장 국면"])

    # ── 탭1: 팩터 스코어 ──────────────────────────────────────
    with tab1:
        if pool_data:
            df = pd.DataFrame(pool_data)

            # 팩터 점수 수평 바 차트 (상위 20개)
            df_top = df.sort_values("factor_score", ascending=False).head(20).copy()
            df_top["color"] = df_top["factor_score"].apply(
                lambda x: GREEN if x > 0.6 else (GREY if x > 0.4 else RED)
            )
            pool_set = set(pool.get("pool", []))
            df_top["in_pool"] = df_top["code"].apply(lambda c: "★ " if c in pool_set else "")
            df_top["label"]   = df_top["in_pool"] + df_top["name"] + " (" + df_top["code"] + ")"

            fig = go.Figure(go.Bar(
                y=df_top["label"],
                x=df_top["factor_score"],
                orientation="h",
                marker_color=df_top["color"].tolist(),
                text=df_top["factor_score"].apply(lambda x: f"{x:.3f}"),
                textposition="outside",
            ))
            fig.update_layout(
                title="팩터 점수 Top 20  (★ = 최종 후보 풀 선정)",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(autorange="reversed"),
                height=600,
                margin=dict(l=0, r=80, t=40, b=0),
                xaxis=dict(range=[0, 1.15]),
            )
            st.plotly_chart(fig, use_container_width=True)

            # 개별 팩터 상세 (레이더 비교)
            st.subheader("종목 비교 레이더")
            factor_cols = [c for c in ["ret_1m", "ret_3m", "ret_6m", "vol_ratio", "pos_52w"]
                           if c in df.columns]
            if factor_cols and len(df) > 0:
                top5 = df_top["code"].head(5).tolist()
                sel  = st.multiselect("종목 선택 (최대 5)", df["code"].tolist(),
                                       default=top5[:3],
                                       format_func=lambda c: df.set_index("code")["name"].get(c, c))
                if sel:
                    radar_df = df[df["code"].isin(sel)].copy()
                    # 각 팩터를 0~1 정규화
                    for col in factor_cols:
                        mn, mx = radar_df[col].min(), radar_df[col].max()
                        radar_df[col] = (radar_df[col] - mn) / (mx - mn + 1e-9)

                    fig_r = go.Figure()
                    cats  = factor_cols + [factor_cols[0]]
                    colors_radar = [GREEN, BLUE, "#FFD700", "#FF8C00", "#C77DFF"]
                    for i, (_, row) in enumerate(radar_df.iterrows()):
                        vals = [row[c] for c in factor_cols] + [row[factor_cols[0]]]
                        fig_r.add_trace(go.Scatterpolar(
                            r=vals, theta=cats,
                            fill="toself", name=row["name"],
                            line=dict(color=colors_radar[i % len(colors_radar)]),
                            opacity=0.7,
                        ))
                    fig_r.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        polar=dict(bgcolor="rgba(26,31,46,0.8)"),
                        height=400,
                    )
                    st.plotly_chart(fig_r, use_container_width=True)
        else:
            st.info("pool_cache.json에 universe_data가 없습니다.")

    # ── 탭2: 포트폴리오 커브 ──────────────────────────────────
    with tab2:
        snapshots = load_portfolio_snapshots()

        # ── 실제 자산 커브 (스냅샷 기반) ──────────────────────
        if snapshots:
            st.subheader("📸 실제 자산 커브 (일별 잔고)")
            df_snap = pd.DataFrame(snapshots)
            fig_s = go.Figure()
            fig_s.add_trace(go.Scatter(
                x=df_snap["date"], y=df_snap["total_krw"],
                mode="lines+markers",
                line=dict(color=BLUE, width=2),
                fill="tozeroy",
                fillcolor="rgba(76,141,255,0.08)",
                name="총 자산 (KRW)",
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "총 자산: ₩%{y:,.0f}<extra></extra>"
                ),
            ))
            if "kr_stock_value" in df_snap.columns:
                fig_s.add_trace(go.Scatter(
                    x=df_snap["date"], y=df_snap["kr_stock_value"],
                    mode="lines",
                    line=dict(color=GREEN, width=1, dash="dot"),
                    name="KR 주식",
                ))
            if "us_stock_value_krw" in df_snap.columns:
                fig_s.add_trace(go.Scatter(
                    x=df_snap["date"], y=df_snap["us_stock_value_krw"],
                    mode="lines",
                    line=dict(color="#FFD700", width=1, dash="dot"),
                    name="US 주식 (KRW 환산)",
                ))
            # 첫 스냅샷 기준선
            base_val = df_snap["total_krw"].iloc[0]
            fig_s.add_hline(y=base_val, line_dash="dot", line_color=GREY, opacity=0.4)
            fig_s.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(gridcolor="#2A3050"),
                yaxis=dict(gridcolor="#2A3050", tickformat=",.0f"),
                height=350,
                margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(bgcolor="rgba(0,0,0,0)"),
            )
            st.plotly_chart(fig_s, use_container_width=True)

            # 최신 vs 최초 비교
            first_val = df_snap["total_krw"].iloc[0]
            last_val  = df_snap["total_krw"].iloc[-1]
            ret_pct   = (last_val - first_val) / first_val * 100 if first_val else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("최초 자산",   f"₩{first_val:,.0f}")
            c2.metric("현재 자산",   f"₩{last_val:,.0f}",
                      delta=f"{ret_pct:+.2f}%",
                      delta_color="normal" if ret_pct >= 0 else "inverse")
            c3.metric("기록 기간",   f"{len(df_snap)}일")
            st.markdown("---")
        else:
            st.info("스냅샷 없음 — 매일 16:00 자동 저장됩니다.")

        # ── 실현 손익 커브 (거래 기반) ────────────────────────
        st.subheader("💰 실현 손익 커브 (매도 기준)")
        col_cfg, _ = st.columns([1, 3])
        with col_cfg:
            init_cap = st.number_input("초기 자본 (원)", value=5_000_000,
                                       step=500_000, format="%d")

        if trades_all:
            curve    = compute_portfolio_curve(trades_all, init_cap)
            df_curve = pd.DataFrame(curve)

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_curve["date"], y=df_curve["value"],
                mode="lines+markers",
                line=dict(color=GREEN, width=2),
                fill="tozeroy",
                fillcolor="rgba(0,212,170,0.08)",
                name="누적 실현손익",
                hovertemplate="<b>%{x}</b><br>₩%{y:,.0f}<extra></extra>",
            ))
            sells_df = df_curve[
                df_curve["profit_pct"].notna() if "profit_pct" in df_curve.columns
                else pd.Series([False] * len(df_curve))
            ].copy() if "profit_pct" in df_curve.columns else pd.DataFrame()
            if not sells_df.empty:
                colors_dot = [GREEN if v >= 0 else RED for v in sells_df["profit_pct"]]
                fig.add_trace(go.Scatter(
                    x=sells_df["date"], y=sells_df["value"],
                    mode="markers",
                    marker=dict(color=colors_dot, size=10, symbol="diamond"),
                    name="매도 시점",
                    hovertemplate="<b>%{x}</b><br>%{customdata}<extra></extra>",
                    customdata=[f"{r.get('name','')} {r.get('profit_pct',0):+.2f}%"
                                for _, r in sells_df.iterrows()],
                ))
            fig.add_hline(y=init_cap, line_dash="dot", line_color=GREY, opacity=0.5)
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(gridcolor="#2A3050"),
                yaxis=dict(gridcolor="#2A3050", tickformat=",.0f"),
                height=350,
                margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(bgcolor="rgba(0,0,0,0)"),
            )
            st.plotly_chart(fig, use_container_width=True)

            stats_c = compute_stats(trades_all)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("총 거래",   f"{stats_c['total_trades']}건")
            c2.metric("승률",       f"{stats_c['win_rate']:.1f}%")
            c3.metric("평균 수익",  f"{stats_c['avg_profit']:+.2f}%")
            c4.metric("평균 손실",  f"{stats_c['avg_loss']:+.2f}%")
            if stats_c.get("best_trade"):
                b = stats_c["best_trade"]
                w = stats_c["worst_trade"]
                c1, c2 = st.columns(2)
                c1.success(f"🏆 최고: {b['name']} {float(b['profit_pct']):+.2f}%  ({b['date']})")
                c2.error(f"💀 최악: {w['name']} {float(w['profit_pct']):+.2f}%  ({w['date']})")
        else:
            st.info("거래 이력이 없습니다.")

        # ── 트레일링 스탑 현황 ────────────────────────────────
        st.markdown("---")
        st.subheader("🛡 트레일링 스탑 현황")
        ts_data = load_trailing_stops()
        if ts_data:
            rows = []
            for code, d in ts_data.items():
                peak  = d.get("peak", 0)
                buy_p = d.get("buy_price", 0)
                stop  = peak * 0.95
                rows.append({
                    "코드": code,
                    "매수가": f"{buy_p:,.0f}",
                    "최고가": f"{peak:,.0f}",
                    "스탑가 (-5%)": f"{stop:,.0f}",
                    "매수일": d.get("buy_date", "-"),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("현재 트레일링 스탑 추적 종목 없음")

    # ── 탭4: 시장 국면 이력 ───────────────────────────────────
    with tab4:
        regime_hist = load_regime_history()
        if regime_hist:
            df_r = pd.DataFrame(regime_hist)
            cur  = load_regime()
            bull = cur.get("is_bull", True)
            label = "🐂 BULL" if bull else "🐻 BEAR"
            gap   = cur.get("gap_pct", 0)
            color = GREEN if bull else RED
            st.markdown(
                f"<h3>현재 국면: <span style='color:{color}'>{label}</span> "
                f"<small style='font-size:0.9rem; color:#888'>KOSPI {cur.get('kospi',0):,.0f} vs SMA200 {cur.get('sma200',0):,.0f} ({gap:+.1f}%)</small></h3>",
                unsafe_allow_html=True,
            )
            if "gap_pct" in df_r.columns:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_r["updated_at"], y=df_r["gap_pct"],
                    mode="lines+markers",
                    line=dict(color=BLUE, width=2),
                    fill="tozeroy",
                    fillcolor="rgba(76,141,255,0.1)",
                    name="KOSPI vs SMA200 괴리율(%)",
                ))
                fig.add_hline(y=0, line_dash="dash", line_color=RED, opacity=0.6)
                fig.update_layout(
                    title="KODEX200 vs SMA200 괴리율 이력 (양수=Bull, 음수=Bear)",
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(gridcolor="#2A3050"),
                    yaxis=dict(gridcolor="#2A3050", ticksuffix="%"),
                    height=350,
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                df_r[["updated_at","regime","kospi","sma200","gap_pct"]].sort_values("updated_at", ascending=False),
                use_container_width=True, height=300,
            )
        else:
            st.info("regime_cache.json 없음. 장 시작 후 자동 수집됩니다.")

    # ── 탭3: 섹터 분포 ────────────────────────────────────────
    with tab3:
        if pool_data:
            df = pd.DataFrame(pool_data)
            if "sector" in df.columns:
                # 후보 풀 섹터 분포
                pool_df = df[df["code"].isin(pool.get("pool", []))]
                sector_cnt = pool_df["sector"].value_counts().reset_index()
                sector_cnt.columns = ["섹터", "종목수"]

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("#### 후보 풀 섹터 분포")
                    fig_pie = px.pie(
                        sector_cnt, names="섹터", values="종목수",
                        color_discrete_sequence=px.colors.qualitative.Set3,
                        hole=0.45,
                    )
                    fig_pie.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        height=350,
                        showlegend=True,
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)

                with c2:
                    st.markdown("#### 섹터별 팩터 평균")
                    if "factor_score" in df.columns:
                        sec_score = (df.groupby("sector")["factor_score"]
                                       .mean().sort_values(ascending=False)
                                       .reset_index())
                        sec_score.columns = ["섹터", "평균팩터점수"]
                        fig_bar = px.bar(
                            sec_score, x="평균팩터점수", y="섹터",
                            orientation="h",
                            color="평균팩터점수",
                            color_continuous_scale=[[0, RED], [1, GREEN]],
                            height=350,
                        )
                        fig_bar.update_layout(
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            coloraxis_showscale=False,
                            yaxis=dict(autorange="reversed"),
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("pool_cache.json에 데이터가 없습니다.")


# ══════════════════════════════════════════════════════════════
# 📋 거래 이력
# ══════════════════════════════════════════════════════════════
elif page == "📋 거래 이력":

    st.title("📋 거래 이력")

    # 필터 바
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        days_filter = st.selectbox("기간", [7, 30, 60, 90, 180, 365], index=2,
                                    format_func=lambda x: f"최근 {x}일")
    with f2:
        action_filter = st.multiselect("구분", ["BUY", "SELL"], default=["BUY", "SELL"])
    with f3:
        mode_filter = st.multiselect("모드", ["brain", "brain_us", "regime_adaptive",
                                               "momentum", "dual_momentum", "unknown"],
                                      default=[])
    with f4:
        code_filter = st.text_input("종목코드 검색", "")

    trades = load_trades(days=days_filter)

    # 필터 적용
    if action_filter:
        trades = [t for t in trades if t["action"] in action_filter]
    if mode_filter:
        trades = [t for t in trades if t.get("mode", "") in mode_filter]
    if code_filter:
        trades = [t for t in trades if code_filter.upper() in t.get("code", "").upper()
                  or code_filter in t.get("name", "")]

    st.markdown(f"**{len(trades)}건** 조회됨")

    if trades:
        df = pd.DataFrame(trades)

        # 컬럼 포매팅
        display_cols = ["datetime", "action", "name", "code", "price",
                        "qty", "amount", "profit_pct", "profit_amount", "reason", "mode"]
        display_cols = [c for c in display_cols if c in df.columns]
        df_disp = df[display_cols].copy()
        df_disp.rename(columns={
            "datetime": "일시", "action": "구분", "name": "종목명", "code": "코드",
            "price": "가격", "qty": "수량", "amount": "금액",
            "profit_pct": "손익%", "profit_amount": "손익액",
            "reason": "사유", "mode": "모드",
        }, inplace=True)

        def row_style(row):
            if row.get("구분") == "BUY":
                return ["background-color: rgba(76,141,255,0.07)"] * len(row)
            elif row.get("구분") == "SELL":
                pnl = row.get("손익%")
                try:
                    if float(pnl) >= 0:
                        return ["background-color: rgba(0,212,170,0.07)"] * len(row)
                    else:
                        return ["background-color: rgba(255,107,107,0.07)"] * len(row)
                except Exception:
                    pass
            return [""] * len(row)

        fmt = {}
        if "가격" in df_disp.columns:  fmt["가격"] = "{:,.0f}"
        if "금액" in df_disp.columns:  fmt["금액"] = "{:,.0f}"
        if "손익액" in df_disp.columns: fmt["손익액"] = lambda x: f"{int(x):+,}" if x else "-"
        if "손익%" in df_disp.columns:  fmt["손익%"] = lambda x: f"{float(x):+.2f}%" if x else "-"

        st.dataframe(
            df_disp.style.apply(row_style, axis=1).format(fmt, na_rep="-"),
            use_container_width=True,
            height=450,
        )

        # 종목별 요약
        st.markdown("---")
        st.subheader("📊 종목별 누적 손익")
        code_stats = per_code_stats(trades)
        if code_stats:
            df_cs = pd.DataFrame(code_stats)
            if "pnl" in df_cs.columns and "name" in df_cs.columns:
                fig = px.bar(
                    df_cs, x="name", y="pnl",
                    color="avg_pct",
                    color_continuous_scale=[[0, RED], [0.5, GREY], [1, GREEN]],
                    color_continuous_midpoint=0,
                    labels={"name": "종목", "pnl": "손익(원)", "avg_pct": "평균손익%"},
                    text=df_cs["avg_pct"].apply(lambda x: f"{x:+.1f}%"),
                    height=300,
                )
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    coloraxis_showscale=False,
                    xaxis_title="",
                    margin=dict(l=0, r=0, t=10, b=0),
                )
                fig.update_traces(textposition="outside")
                st.plotly_chart(fig, use_container_width=True)

        # Win/Loss 분포
        sells = [t for t in trades if t["action"] == "SELL" and t.get("profit_pct")]
        if sells:
            pcts = [float(t["profit_pct"]) for t in sells]
            fig_hist = px.histogram(
                x=pcts, nbins=20,
                labels={"x": "손익률 (%)"},
                color_discrete_sequence=[GREEN],
                title="손익률 분포",
                height=250,
            )
            fig_hist.add_vline(x=0, line_dash="dash", line_color=RED, opacity=0.7)
            fig_hist.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_hist, use_container_width=True)
    else:
        st.info("해당 기간/조건에 거래 이력이 없습니다.")


# ══════════════════════════════════════════════════════════════
# 📜 로그 & 캐시
# ══════════════════════════════════════════════════════════════
elif page == "📜 로그 & 캐시":

    st.title("📜 로그 & 캐시")

    tab_log, tab_pool, tab_research = st.tabs(["🖥 Runner 로그", "🗂 후보 풀 캐시", "🌐 리서치 캐시"])

    # ── 러너 로그 ──────────────────────────────────────────────
    with tab_log:
        col_l, col_r = st.columns([1, 3])
        with col_l:
            n_lines = st.slider("표시 줄 수", 50, 500, 200, 50)
            filter_kw = st.text_input("키워드 필터", "")
        with col_r:
            pass

        log_lines = load_runner_log(n_lines)
        if filter_kw:
            log_lines = [l for l in log_lines if filter_kw.lower() in l.lower()]
        log_lines = list(reversed(log_lines))  # 최신 로그 최상위

        # 색상 코딩
        def colorize(line: str) -> str:
            if any(k in line for k in ["매수", "BUY", "🟢"]):
                return f"<span style='color:{BLUE}'>{line}</span>"
            if any(k in line for k in ["매도", "SELL", "🔴", "익절", "손절"]):
                return f"<span style='color:{GREEN}'>{line}</span>"
            if any(k in line for k in ["Error", "오류", "실패", "❌"]):
                return f"<span style='color:{RED}'>{line}</span>"
            if any(k in line for k in ["팩터", "Brain", "Risk", "Pool"]):
                return f"<span style='color:#FFD700'>{line}</span>"
            return f"<span style='color:#AAAAAA'>{line}</span>"

        log_html = "<br>".join(colorize(l) for l in log_lines)
        st.markdown(
            f"<div style='background:#0D1117; border-radius:8px; padding:16px; "
            f"font-family:monospace; font-size:0.78rem; line-height:1.5; "
            f"max-height:600px; overflow-y:auto'>{log_html}</div>",
            unsafe_allow_html=True,
        )
        if st.button("🔄 새로고침"):
            st.rerun()

    # ── 후보 풀 캐시 ──────────────────────────────────────────
    with tab_pool:
        c1, c2 = st.columns(2)

        with c1:
            st.markdown(f"#### 🇰🇷 한국주식 후보 풀  `{pool.get('date','-')}`")
            pool_codes = pool.get("pool", [])
            universe_data = pool.get("universe_data", [])
            if pool_codes:
                st.markdown(f"**선정 종목**: {', '.join(pool_codes)}")
                if universe_data:
                    df_u = pd.DataFrame(universe_data)
                    show_cols = [c for c in ["name", "code", "sector", "factor_score",
                                              "ret_1m", "ret_3m", "ret_6m",
                                              "pos_52w", "vol_ratio", "atr"] if c in df_u.columns]
                    st.dataframe(
                        df_u[show_cols].style.format(
                            {c: "{:+.2f}" for c in ["ret_1m","ret_3m","ret_6m"]
                             if c in df_u.columns}
                        ),
                        use_container_width=True, height=500,
                    )
            else:
                st.info("후보 풀이 비어 있습니다.")

        with c2:
            st.markdown(f"#### 🇺🇸 미국주식 후보 풀  `{pool_us.get('date','-')}`")
            pool_us_codes = pool_us.get("pool", [])
            if pool_us_codes:
                st.markdown(f"**선정 종목**: {', '.join(pool_us_codes)}")
            else:
                st.info("미국 후보 풀이 비어 있습니다.")

            # 원본 JSON 보기
            with st.expander("🔍 pool_cache.json 원본"):
                st.json(pool if pool else {})

    # ── 리서치 캐시 ────────────────────────────────────────────
    with tab_research:
        research = load_research()
        if research:
            st.markdown(f"**수집 날짜**: {research.get('date', '-')}")
            content = research.get("content", "")
            if content:
                st.markdown(
                    f"<div style='background:#1A1F2E; border-radius:8px; padding:18px; "
                    f"font-size:0.92rem; line-height:1.8'>"
                    f"{content.replace(chr(10), '<br>')}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.warning("리서치 내용이 비어 있습니다.")
        else:
            st.info("research_cache.json 없음. 장 시작 후 자동 수집됩니다.")
