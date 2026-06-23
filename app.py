"""
Dashboard Screener Saham IHSG -- Streamlit
Menampilkan hasil screening (Potential 4H / Potential 3M / Big Vol) yang sudah
disiapkan oleh run_screener.py (dijalankan otomatis lewat GitHub Actions tiap
market close).

Desain:
- Minimalis, monokrom, tanpa emoji/sticker -- gaya bersih ala Perplexity.
- Simpel, tidak spam meski hasil ratusan -> tabel ringkas + detail/chart hanya
  dibuka saat diklik, bukan semua dirender langsung.
- Diurutkan dari TP Potential % terbesar -> terkecil (global, lintas kategori).
- Label "Baru" (teks polos) untuk saham yang baru muncul dibanding hasil sebelumnya.
- Chart candlestick + semua garis SMA + volume, dengan toggle SMA yang ingin
  ditampilkan supaya tidak penuh sesak.
"""

import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config

st.set_page_config(
    page_title="Screener Saham IHSG",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# DESIGN TOKENS -- monokrom + satu aksen warna untuk +/- saja
# ============================================================
INK = "#1a1a1a"
MUTED = "#6b6b6b"
FAINT = "#9a9a9a"
LINE = "#e5e5e5"
BG_SOFT = "#f7f7f7"
POS = "#1a7a4c"
NEG = "#b3261e"

CSS = f"""
<style>
.block-container {{ padding-top: 2.2rem; max-width: 1100px; }}
h1, h2, h3 {{ font-weight: 600 !important; letter-spacing: -0.01em; }}
[data-testid="stMetricValue"] {{ font-weight: 600; color: {INK}; }}
[data-testid="stMetricLabel"] {{ color: {MUTED}; }}
hr {{ border-color: {LINE} !important; margin: 0.6rem 0 !important; }}
.row-card {{
    padding: 14px 4px;
    border-bottom: 1px solid {LINE};
}}
.tag {{
    display: inline-block;
    font-size: 0.78rem;
    color: {MUTED};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 1px 9px;
    font-weight: 500;
}}
.tag-new {{
    display: inline-block;
    font-size: 0.72rem;
    color: {INK};
    background: {BG_SOFT};
    border-radius: 5px;
    padding: 1px 7px;
    font-weight: 600;
    margin-left: 6px;
}}
.ticker {{ font-size: 1.05rem; font-weight: 600; color: {INK}; }}
.price {{ font-size: 0.95rem; color: {MUTED}; }}
.tp-pos {{ font-weight: 600; font-size: 1.0rem; color: {POS}; }}
.tp-neg {{ font-weight: 600; font-size: 1.0rem; color: {NEG}; }}
.rank {{ color: {FAINT}; font-size: 0.85rem; }}
.section-desc {{ color: {MUTED}; font-size: 0.88rem; line-height: 1.5; }}
.disclaimer {{ color: {FAINT}; font-size: 0.78rem; line-height: 1.5; }}
</style>
"""

CATEGORY_INFO = {
    "1": {
        "label": "Potential 4H",
        "desc": "SMA3/5/10 melilit rapat dan SMA20 dekat dengan cluster tersebut -- potensi rebound ke SMA besar di atasnya.",
    },
    "2": {
        "label": "Potential 3M",
        "desc": "Harga mendekati SMA60/100/200 dari atas -- berpotensi memantul (bounce) ke SMA besar berikutnya.",
    },
    "3": {
        "label": "Big Vol",
        "desc": "Harga di bawah semua SMA, tapi volume tiba-tiba membesar -- ada aktivitas tidak biasa di tengah downtrend.",
    },
}

SMA_COLORS = {
    "SMA3": "#c9a227",
    "SMA5": "#b07d1f",
    "SMA10": "#8a5a2b",
    "SMA20": "#3b6ea5",
    "SMA60": "#1a7a4c",
    "SMA100": "#5b4a8a",
    "SMA200": "#1a1a1a",
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
def render_chart(candles, visible_smas):
    if not candles:
        st.caption("Data chart tidak tersedia untuk ticker ini.")
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
            increasing_line_color=POS,
            decreasing_line_color=NEG,
            increasing_fillcolor=POS,
            decreasing_fillcolor=NEG,
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
                    line=dict(width=1.4, color=SMA_COLORS.get(sma, "#999999")),
                    yaxis="y1",
                )
            )

    vol_colors = [
        "rgba(26,122,76,0.45)" if c >= o else "rgba(179,38,30,0.45)"
        for o, c in zip(df["open"], df["close"])
    ]
    fig.add_trace(
        go.Bar(
            x=df["date"],
            y=df["volume"],
            name="Volume",
            marker_color=vol_colors,
            yaxis="y2",
        )
    )

    fig.update_layout(
        height=440,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=11)),
        yaxis=dict(domain=[0.28, 1.0], title=None, side="right", gridcolor=LINE),
        yaxis2=dict(domain=[0.0, 0.2], title=None, showticklabels=False),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
        font=dict(color=INK, size=12),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor=LINE)

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


# ============================================================
# BARIS HASIL (ringkas + detail saat expand)
# ============================================================
def render_result_row(row, charts):
    info = CATEGORY_INFO[row["Setup"]]
    tp_pct = row.get("TP_Pot_pct")
    tp_class = "tp-pos" if (tp_pct or 0) >= 0 else "tp-neg"
    new_html = "<span class='tag-new'>Baru</span>" if row.get("is_new") else ""

    st.markdown('<div class="row-card">', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns([0.5, 1.6, 1.3, 1.2, 1.3])
    with c1:
        st.markdown(f"<span class='rank'>{row['rank']}</span>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<span class='ticker'>{row['Ticker']}</span>{new_html}", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<span class='price'>Rp {format_rupiah(row['Close'])}</span>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<span class='{tp_class}'>{format_pct(tp_pct)}</span>", unsafe_allow_html=True)
    with c5:
        st.markdown(f"<span class='tag'>{info['label']}</span>", unsafe_allow_html=True)

    expand = st.toggle(
        "Lihat detail",
        key=f"toggle_{row['Setup']}_{row['Ticker']}_{row['rank']}",
        label_visibility="collapsed",
    )

    if expand:
        dcol1, dcol2 = st.columns([1.3, 1])
        with dcol1:
            st.markdown(f"<p class='section-desc'>{info['desc']}</p>", unsafe_allow_html=True)
            if row["Setup"] == "1":
                st.write(
                    f"SMA3 / SMA5 / SMA10 / SMA20: "
                    f"Rp {format_rupiah(row['SMA3'])} / Rp {format_rupiah(row['SMA5'])} / "
                    f"Rp {format_rupiah(row['SMA10'])} / Rp {format_rupiah(row['SMA20'])}"
                )
                st.write(f"Target: {row['TP_Target']} = Rp {format_rupiah(row['TP_Val'])}")
                st.write(f"Semua level di atas: {row['Semua_TP']}")
            elif row["Setup"] == "2":
                st.write(
                    f"Support: {row['Support_SMA']} = Rp {format_rupiah(row['Support_Val'])} "
                    f"(jarak {row['Gap_Support_pct']:.1f}%)"
                )
                st.write(f"Target: {row['TP_SMA']} = Rp {format_rupiah(row['TP_Val'])}")
                st.write(f"Semua SMA besar: {row['Semua_SMA_Besar']}")
            elif row["Setup"] == "3":
                st.write(f"Volume hari ini {row['Vol_Ratio']:.2f}x dari rata-rata 20 hari")
                st.write(f"Resistance terdekat: {row['Resist_Terdekat']} = Rp {format_rupiah(row['Resist_Val'])}")

            st.markdown("<br>", unsafe_allow_html=True)
            sma_options = ["SMA3", "SMA5", "SMA10", "SMA20", "SMA60", "SMA100", "SMA200"]
            default_sma = ["SMA20", "SMA60", "SMA100", "SMA200"]
            visible_smas = st.multiselect(
                "Garis SMA pada chart",
                sma_options,
                default=default_sma,
                key=f"sma_select_{row['Setup']}_{row['Ticker']}_{row['rank']}",
            )
        with dcol2:
            st.markdown(
                "<p class='disclaimer'>Alat bantu analisa teknikal, bukan rekomendasi beli atau jual.</p>",
                unsafe_allow_html=True,
            )

        render_chart(charts.get(row["Ticker"]), visible_smas)

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# MAIN
# ============================================================
def main():
    st.markdown(CSS, unsafe_allow_html=True)

    st.markdown(
        f"<h1 style='margin-bottom:0.1rem'>Screener Saham IHSG</h1>"
        f"<p style='color:{MUTED};margin-top:0;font-size:0.95rem'>"
        f"Pemindaian otomatis setiap penutupan pasar, diurutkan dari potensi take profit terbesar.</p>",
        unsafe_allow_html=True,
    )

    data = load_result()

    if data is None:
        st.info(
            "Belum ada hasil screening. Jalankan `run_screener.py` (lewat GitHub Actions) "
            "minimal sekali untuk menghasilkan data."
        )
        st.stop()

    results = data["results"]
    charts = data.get("charts", {})
    summary = data["summary"]

    st.markdown("<br>", unsafe_allow_html=True)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total kandidat", summary["total_count"])
    m2.metric("Baru hari ini", summary["new_count"])
    m3.metric("Potential 4H", summary["setup1_count"])
    m4.metric("Potential 3M", summary["setup2_count"])
    m5.metric("Big Vol", summary["setup3_count"])

    st.markdown(
        f"<p style='color:{FAINT};font-size:0.82rem'>Terakhir update: {data['generated_at_display']} &middot; "
        f"{data['total_ticker_discan']}/{data['total_ticker_terdaftar']} saham berhasil discan</p>",
        unsafe_allow_html=True,
    )

    st.divider()

    # ---------- SIDEBAR FILTER ----------
    st.sidebar.markdown("**Filter**")
    setup_filter = st.sidebar.multiselect(
        "Kategori",
        options=["1", "2", "3"],
        default=["1", "2", "3"],
        format_func=lambda s: CATEGORY_INFO[s]["label"],
    )
    only_new = st.sidebar.checkbox("Hanya tampilkan yang baru", value=False)
    min_tp = st.sidebar.slider("Minimal potential (%)", 0, 100, 0, step=5)
    search = st.sidebar.text_input("Cari ticker", "").upper().strip()

    n_show_options = [10, 20, 50, 100, "Semua"]
    n_show = st.sidebar.selectbox("Jumlah hasil ditampilkan", n_show_options, index=1)

    st.sidebar.divider()
    st.sidebar.markdown(
        "<p class='disclaimer'>Disclaimer: ini alat bantu analisa teknikal berbasis SMA dan volume, "
        "bukan rekomendasi atau saran finansial. Selalu lakukan riset dan kelola risiko sendiri.</p>",
        unsafe_allow_html=True,
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

    shown_count = min(len(filtered), n_show if n_show != "Semua" else len(filtered))
    st.markdown(
        f"<p style='color:{MUTED};font-size:0.88rem'>Menampilkan {shown_count} dari {len(filtered)} hasil, "
        f"terurut dari potential terbesar.</p>",
        unsafe_allow_html=True,
    )

    show_list = filtered if n_show == "Semua" else filtered[: int(n_show)]

    for row in show_list:
        render_result_row(row, charts)

    if n_show != "Semua" and len(filtered) > int(n_show):
        st.markdown(
            f"<p class='disclaimer'>{len(filtered) - int(n_show)} hasil lainnya disembunyikan. "
            f"Ubah filter di sidebar untuk melihat lebih banyak.</p>",
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    main()
