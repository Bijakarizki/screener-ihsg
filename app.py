"""
Dashboard Screener Saham IHSG -- Streamlit
Menampilkan hasil screening (Setup 1/2/3) yang sudah disiapkan oleh
run_screener.py (dijalankan otomatis lewat GitHub Actions tiap market close).

Desain:
- Simpel, tidak spam meski hasil ratusan -> pakai ringkasan + tabel ringkas +
  detail/chart hanya dibuka saat diklik (expander), bukan semua dirender langsung.
- Diurutkan dari TP Potential % terbesar -> terkecil (global, lintas setup).
- Badge "BARU" untuk saham yang baru muncul dibanding hasil sebelumnya.
- Chart candlestick + semua garis SMA + volume, dengan toggle SMA mana yang
  mau ditampilkan supaya tidak penuh sesak.
"""

import json
import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config

st.set_page_config(
    page_title="Screener Saham IHSG",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

SETUP_INFO = {
    "1": {
        "label": "Base / Re-Akumulasi",
        "desc": "SMA3/5/10 melilit rapat & SMA20 dekat cluster -- potensi rebound ke SMA besar di atasnya.",
        "color": "#2E86AB",
    },
    "2": {
        "label": "Bounce SMA Besar",
        "desc": "Harga mendekati SMA60/100/200 dari atas -- berpotensi memantul (bounce) ke SMA besar berikutnya.",
        "color": "#7B61FF",
    },
    "3": {
        "label": "Downtrend + Volume Signifikan",
        "desc": "Harga di bawah semua SMA, tapi volume tiba-tiba membesar -- ada aktivitas tak biasa di tengah downtrend.",
        "color": "#E0633F",
    },
}

SMA_COLORS = {
    "SMA3": "#FFB703",
    "SMA5": "#FB8500",
    "SMA10": "#D7263D",
    "SMA20": "#3A86FF",
    "SMA60": "#06A77D",
    "SMA100": "#8338EC",
    "SMA200": "#222222",
}


# ============================================================
# LOAD DATA
# ============================================================
@st.cache_data(ttl=300)
def load_result():
    if not os.path.exists(config.LATEST_RESULT_FILE):
        return None
    with open(config.LATEST_RESULT_FILE, "r") as f:
        return json.load(f)


def format_pct(v):
    if v is None:
        return "-"
    return f"{v:+.1f}%"


def format_rupiah(v):
    if v is None:
        return "-"
    return f"{v:,.0f}".replace(",", ".")


# ============================================================
# CHART
# ============================================================
def render_chart(ticker, candles, visible_smas):
    if not candles:
        st.info("Data chart tidak tersedia untuk ticker ini.")
        return

    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])

    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Harga",
            increasing_line_color="#2BAE66",
            decreasing_line_color="#D7263D",
            increasing_fillcolor="#2BAE66",
            decreasing_fillcolor="#D7263D",
            yaxis="y1",
        )
    )

    for sma in visible_smas:
        if sma in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df["date"],
                    y=df[sma],
                    name=sma,
                    mode="lines",
                    line=dict(width=1.6, color=SMA_COLORS.get(sma, "#999999")),
                    yaxis="y1",
                )
            )

    vol_colors = [
        "rgba(43,174,102,0.5)" if c >= o else "rgba(215,38,61,0.5)"
        for o, c in zip(df["open"], df["close"])
    ]
    fig.add_trace(
        go.Bar(
            x=df["date"],
            y=df["volume"],
            name="Volume",
            marker_color=vol_colors,
            yaxis="y2",
            opacity=0.7,
        )
    )

    fig.update_layout(
        height=460,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        yaxis=dict(domain=[0.28, 1.0], title="Harga", side="right"),
        yaxis2=dict(domain=[0.0, 0.22], title="Vol", showticklabels=False),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="#eeeeee")

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ============================================================
# CARD HASIL (1 baris ringkas + detail saat expand)
# ============================================================
def render_result_card(row, charts):
    info = SETUP_INFO[row["Setup"]]
    badge_new = "🆕 " if row.get("is_new") else ""
    tp_pct = row.get("TP_Pot_pct")

    header_cols = st.columns([0.6, 1.6, 1.3, 1.6, 2.4, 1.0])
    with header_cols[0]:
        st.markdown(f"**#{row['rank']}**")
    with header_cols[1]:
        st.markdown(f"### {badge_new}{row['Ticker']}")
    with header_cols[2]:
        st.markdown(f"Rp {format_rupiah(row['Close'])}")
    with header_cols[3]:
        color = "#1a9850" if (tp_pct or 0) >= 0 else "#d73027"
        st.markdown(
            f"<span style='color:{color};font-weight:700;font-size:1.1rem'>{format_pct(tp_pct)}</span>",
            unsafe_allow_html=True,
        )
    with header_cols[4]:
        st.markdown(
            f"<span style='background:{info['color']}22;color:{info['color']};"
            f"padding:2px 10px;border-radius:12px;font-size:0.82rem;font-weight:600'>"
            f"Setup {row['Setup']} -- {info['label']}</span>",
            unsafe_allow_html=True,
        )

    with header_cols[5]:
        expand = st.toggle("Detail", key=f"toggle_{row['Setup']}_{row['Ticker']}_{row['rank']}")

    if expand:
        with st.container(border=True):
            dcol1, dcol2 = st.columns([1.3, 1])
            with dcol1:
                st.caption(info["desc"])
                if row["Setup"] == "1":
                    st.write(
                        f"- SMA3/5/10/20: **{format_rupiah(row['SMA3'])} / {format_rupiah(row['SMA5'])} / "
                        f"{format_rupiah(row['SMA10'])} / {format_rupiah(row['SMA20'])}**"
                    )
                    st.write(f"- Target TP: **{row['TP_Target']} = Rp {format_rupiah(row['TP_Val'])}**")
                    st.write(f"- Semua level TP di atas: {row['Semua_TP']}")
                elif row["Setup"] == "2":
                    st.write(
                        f"- Support: **{row['Support_SMA']} = Rp {format_rupiah(row['Support_Val'])}** "
                        f"(jarak {row['Gap_Support_pct']:.1f}%)"
                    )
                    st.write(f"- Target TP: **{row['TP_SMA']} = Rp {format_rupiah(row['TP_Val'])}**")
                    st.write(f"- Semua SMA besar: {row['Semua_SMA_Besar']}")
                elif row["Setup"] == "3":
                    st.write(f"- Volume hari ini **{row['Vol_Ratio']:.2f}x** dari rata-rata 20 hari")
                    st.write(
                        f"- Resistance terdekat: **{row['Resist_Terdekat']} = "
                        f"Rp {format_rupiah(row['Resist_Val'])}**"
                    )
                st.divider()
                sma_options = ["SMA3", "SMA5", "SMA10", "SMA20", "SMA60", "SMA100", "SMA200"]
                default_sma = ["SMA20", "SMA60", "SMA100", "SMA200"]
                visible_smas = st.multiselect(
                    "Tampilkan garis SMA",
                    sma_options,
                    default=default_sma,
                    key=f"sma_select_{row['Setup']}_{row['Ticker']}_{row['rank']}",
                )
            with dcol2:
                st.caption("⚠️ Alat bantu analisa teknikal, bukan rekomendasi beli/jual.")

            render_chart(row["Ticker"], charts.get(row["Ticker"]), visible_smas)

    st.divider()


# ============================================================
# MAIN
# ============================================================
def main():
    st.markdown(
        "<h1 style='margin-bottom:0'>📈 Screener Saham IHSG</h1>"
        "<p style='color:#666;margin-top:0'>Auto-scan tiap market close &middot; diurutkan dari potensi Take Profit terbesar</p>",
        unsafe_allow_html=True,
    )

    data = load_result()

    if data is None:
        st.warning(
            "Belum ada hasil screening. Jalankan `run_screener.py` (lewat GitHub Actions) "
            "minimal sekali untuk menghasilkan data."
        )
        st.stop()

    results = data["results"]
    charts = data.get("charts", {})
    summary = data["summary"]

    # ---------- HEADER METRICS ----------
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Kandidat", summary["total_count"])
    m2.metric("🆕 Baru Hari Ini", summary["new_count"])
    m3.metric("Setup 1", summary["setup1_count"])
    m4.metric("Setup 2", summary["setup2_count"])
    m5.metric("Setup 3", summary["setup3_count"])

    st.caption(
        f"Terakhir update: **{data['generated_at_display']}** &middot; "
        f"{data['total_ticker_discan']}/{data['total_ticker_terdaftar']} saham berhasil discan"
    )

    st.divider()

    # ---------- SIDEBAR FILTER ----------
    st.sidebar.header("🔎 Filter")
    setup_filter = st.sidebar.multiselect(
        "Setup",
        options=["1", "2", "3"],
        default=["1", "2", "3"],
        format_func=lambda s: f"Setup {s} -- {SETUP_INFO[s]['label']}",
    )
    only_new = st.sidebar.checkbox("Hanya tampilkan yang 🆕 baru", value=False)
    min_tp = st.sidebar.slider("Minimal TP Potential (%)", 0, 100, 0, step=5)
    search = st.sidebar.text_input("Cari ticker", "").upper().strip()

    n_show_options = [10, 20, 50, 100, "Semua"]
    n_show = st.sidebar.selectbox("Tampilkan berapa hasil", n_show_options, index=1)

    st.sidebar.divider()
    st.sidebar.caption(
        "⚠️ **Disclaimer**: Ini alat bantu analisa teknikal berbasis SMA & volume, "
        "bukan rekomendasi atau saran finansial. Selalu lakukan riset & manajemen risiko sendiri."
    )

    # ---------- APPLY FILTERS ----------
    filtered = [
        r
        for r in results
        if r["Setup"] in setup_filter
        and (not only_new or r.get("is_new"))
        and (r.get("TP_Pot_pct") is None or r.get("TP_Pot_pct") >= min_tp)
        and (search == "" or search in r["Ticker"])
    ]

    if not filtered:
        st.info("Tidak ada saham yang cocok dengan filter saat ini. Coba kurangi filter.")
        return

    st.markdown(f"**Menampilkan {min(len(filtered), n_show if n_show != 'Semua' else len(filtered))} dari {len(filtered)} hasil (terurut TP Potential)**")

    show_list = filtered if n_show == "Semua" else filtered[: int(n_show)]

    for row in show_list:
        render_result_card(row, charts)

    if n_show != "Semua" and len(filtered) > int(n_show):
        st.caption(f"... {len(filtered) - int(n_show)} hasil lainnya disembunyikan. Ubah filter di sidebar untuk melihat lebih banyak.")


if __name__ == "__main__":
    main()
