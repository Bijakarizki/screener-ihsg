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
# DESIGN TOKENS -- dark "quant terminal": navy + indigo accent,
# monospace untuk ticker/harga, kartu kaca tipis, grid halus di background.
# ============================================================
BG = "#0a0e17"
BG_CARD = "rgba(255,255,255,0.035)"
INK = "#e7e9f5"
MUTED = "#8b93ab"
FAINT = "#5a6178"
LINE = "rgba(255,255,255,0.09)"
ACCENT = "#7c6cff"
ACCENT_SOFT = "rgba(124,108,255,0.16)"
POS = "#2fd48c"
NEG = "#ff5470"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

.stApp {{
    background:
        radial-gradient(circle at 12% 0%, rgba(124,108,255,0.10) 0%, transparent 40%),
        radial-gradient(circle at 100% 20%, rgba(47,212,140,0.06) 0%, transparent 35%),
        {BG};
}}
.block-container {{ padding-top: 2.2rem; max-width: 1100px; }}

h1, h2, h3 {{
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
    color: {INK} !important;
}}
h1 {{
    display: inline-block;
    background: linear-gradient(90deg, {INK} 40%, {ACCENT} 100%);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent !important;
}}
.accent-line {{
    height: 2px;
    width: 64px;
    margin: 6px 0 18px 0;
    background: linear-gradient(90deg, {ACCENT}, transparent);
    border-radius: 2px;
}}

[data-testid="stMetric"] {{
    background: {BG_CARD};
    border: 1px solid {LINE};
    border-radius: 10px;
    padding: 10px 14px 6px 14px;
}}
[data-testid="stMetricValue"] {{
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    color: {INK};
}}
[data-testid="stMetricLabel"] {{ color: {MUTED}; }}

hr {{ border-color: {LINE} !important; margin: 0.6rem 0 !important; }}

.row-card {{
    padding: 14px 12px;
    margin-bottom: 6px;
    border: 1px solid {LINE};
    border-radius: 10px;
    background: {BG_CARD};
    transition: border-color 0.15s ease;
}}
.row-card:hover {{ border-color: rgba(124,108,255,0.35); }}

.tag {{
    display: inline-block;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: {MUTED};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 1px 9px;
    font-weight: 500;
}}
.tag-new {{
    display: inline-block;
    font-size: 0.68rem;
    color: {ACCENT};
    background: {ACCENT_SOFT};
    border-radius: 5px;
    padding: 1px 7px;
    font-weight: 600;
    margin-left: 6px;
}}
.tag-ketat {{
    display: inline-block;
    font-size: 0.66rem;
    color: {POS};
    background: rgba(47,212,140,0.12);
    border-radius: 5px;
    padding: 1px 7px;
    font-weight: 600;
    margin-left: 6px;
}}
.tag-bigvol {{
    display: inline-block;
    font-size: 0.66rem;
    color: #ffb020;
    background: rgba(255,176,32,0.12);
    border-radius: 5px;
    padding: 1px 7px;
    font-weight: 600;
    margin-left: 6px;
}}

.ticker {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.02rem;
    font-weight: 600;
    color: {INK};
    letter-spacing: 0.01em;
}}
.price {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.92rem;
    color: {MUTED};
}}
.tp-pos {{ font-family: 'JetBrains Mono', monospace; font-weight: 600; font-size: 1.0rem; color: {POS}; }}
.tp-neg {{ font-family: 'JetBrains Mono', monospace; font-weight: 600; font-size: 1.0rem; color: {NEG}; }}
.rank {{ color: {FAINT}; font-size: 0.82rem; font-family: 'JetBrains Mono', monospace; }}
.section-desc {{ color: {MUTED}; font-size: 0.88rem; line-height: 1.5; }}
.disclaimer {{ color: {FAINT}; font-size: 0.78rem; line-height: 1.5; }}

section[data-testid="stSidebar"] {{ background: #0d1220; border-right: 1px solid {LINE}; }}
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
    "SMA3": "#ffd166",
    "SMA5": "#f4a261",
    "SMA10": "#e76f51",
    "SMA20": "#4cc9f0",
    "SMA60": "#2fd48c",
    "SMA100": "#9d8cff",
    "SMA200": "#e7e9f5",
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


def get_tp_period(row):
    """
    Ambil angka SMA target (60/100/200) dari row Setup 1. Pakai field TP_Period
    kalau sudah ada (hasil run_screener.py terbaru); kalau belum (data lama sebelum
    field ini ditambahkan), fallback parse dari TP_Target (contoh: "SMA100" -> 100).
    """
    if row.get("TP_Period") is not None:
        return row["TP_Period"]
    target = row.get("TP_Target", "")
    if target.startswith("SMA"):
        try:
            return int(target[3:])
        except ValueError:
            return None
    return None


def cek_big_volume_terakhir(chart_rows, lookback_days, ratio):
    """
    Cek apakah dalam `lookback_days` hari terakhir (dari data chart, bukan cuma
    hari ini) pernah ada bar dengan volume >= `ratio` x rata-rata volume 20 hari.
    Ringan (pure Python, tanpa pandas) karena dipanggil untuk tiap baris tiap rerun.
    """
    if not chart_rows:
        return False
    for bar in chart_rows[-lookback_days:]:
        vol = bar.get("volume")
        vol_sma = bar.get("vol_sma20")
        if vol is None or not vol_sma:
            continue
        if vol / vol_sma >= ratio:
            return True
    return False


def _spread_sma_bar(bar, periods):
    """Spread (desimal) antar SMA di `periods` untuk satu bar candle. None kalau data kurang."""
    vals = []
    for p in periods:
        v = bar.get(f"SMA{p}")
        if v is None:
            return None
        vals.append(v)
    mid = sum(vals) / len(vals)
    if mid == 0:
        return None
    return (max(vals) - min(vals)) / mid


def cek_clustering_konsisten(chart_rows, consistency_days, tol_pct):
    """
    Cek apakah SMA3/5/10/20 sudah rapat (spread <= tol_pct) SECARA KONSISTEN
    selama `consistency_days` hari terakhir berturut-turut -- bukan cuma
    snapshot hari ini. Ini yang bikin chart-nya kelihatan "rapi" seperti contoh
    TradingView (pita SMA nempel beberapa hari), bukan cuma nyentuh sesaat lalu
    mencar lagi.
    Return False kalau data candle kurang dari `consistency_days` hari.
    """
    if not chart_rows or len(chart_rows) < consistency_days:
        return False
    tol = tol_pct / 100.0
    for bar in chart_rows[-consistency_days:]:
        spread = _spread_sma_bar(bar, [3, 5, 10, 20])
        if spread is None or spread > tol:
            return False
    return True


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
        "rgba(47,212,140,0.45)" if c >= o else "rgba(255,84,112,0.45)"
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
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=11, color=INK),
        ),
        yaxis=dict(domain=[0.28, 1.0], title=None, side="right", gridcolor=LINE),
        yaxis2=dict(domain=[0.0, 0.2], title=None, showticklabels=False),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        font=dict(color=INK, size=12),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor=LINE)

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


# ============================================================
# BARIS HASIL (ringkas + detail saat expand)
# ============================================================
@st.fragment
def render_result_row(row, charts, sma20_tol_pct, big_vol_days, big_vol_ratio, cluster_consistency_days):
    info = CATEGORY_INFO[row["Setup"]]
    tp_pct = row.get("TP_Pot_pct")
    tp_class = "tp-pos" if (tp_pct or 0) >= 0 else "tp-neg"
    new_html = "<span class='tag-new'>Baru</span>" if row.get("is_new") else ""

    spread4 = row.get("SMA20_Cluster4_Spread_pct")
    is_ketat = row["Setup"] == "1" and spread4 is not None and spread4 <= sma20_tol_pct
    ketat_html = "<span class='tag-ketat'>SMA20 Ketat</span>" if is_ketat else ""

    is_konsisten = row["Setup"] == "1" and cek_clustering_konsisten(
        charts.get(row["Ticker"]), cluster_consistency_days, sma20_tol_pct
    )
    konsisten_html = "<span class='tag-ketat'>Rapi & Konsisten</span>" if is_konsisten else ""

    is_bigvol = row["Setup"] == "1" and cek_big_volume_terakhir(
        charts.get(row["Ticker"]), big_vol_days, big_vol_ratio
    )
    bigvol_html = "<span class='tag-bigvol'>Big Vol</span>" if is_bigvol else ""

    st.markdown('<div class="row-card">', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns([0.5, 1.6, 1.3, 1.2, 1.3])
    with c1:
        st.markdown(f"<span class='rank'>{row['rank']}</span>", unsafe_allow_html=True)
    with c2:
        st.markdown(
            f"<span class='ticker'>{row['Ticker']}</span>{new_html}{ketat_html}{konsisten_html}{bigvol_html}",
            unsafe_allow_html=True,
        )
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
                if row.get("SMA20_Cluster4_Spread_pct") is not None:
                    st.write(f"Spread SMA3/5/10/20: {row['SMA20_Cluster4_Spread_pct']:.1f}%")
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
        f"<div class='accent-line'></div>"
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

    st.sidebar.markdown("**Filter khusus Potential 4H (Setup 1)**")

    target_sma_filter = st.sidebar.multiselect(
        "Target SMA besar",
        options=[60, 100, 200],
        default=[60, 100, 200],
        format_func=lambda p: f"SMA{p}",
        help="Cuma tampilkan saham yang harganya di bawah SMA besar yang dipilih "
        "(target/TP terdekatnya persis SMA itu). Kosongkan semua = tidak difilter.",
    )

    filter_sma20_ketat = st.sidebar.checkbox("SMA20 ikut melilit rapat (ketat)", value=False)
    sma20_tol_pct = st.sidebar.slider(
        "Toleransi spread SMA3/5/10/20 (%)",
        min_value=int(config.SMA20_KETAT_TOLERANCE_MIN * 100),
        max_value=int(config.SMA20_KETAT_TOLERANCE_MAX * 100),
        value=int(config.SMA20_KETAT_TOLERANCE * 100),
        step=1,
        disabled=not filter_sma20_ketat,
        help="Makin kecil = makin ketat/rapat ke-4 SMA-nya, makin sedikit saham yang lolos. "
        "0% = SMA20 nyaris nempel persis di SMA3/5/10.",
    )

    filter_cluster_consisten = st.sidebar.checkbox("Clustering rapi & konsisten", value=False)
    cluster_consistency_days = st.sidebar.slider(
        "Bertahan rapat berapa hari terakhir",
        min_value=config.CLUSTER_CONSISTENCY_DAYS_MIN,
        max_value=config.CLUSTER_CONSISTENCY_DAYS_MAX,
        value=config.CLUSTER_CONSISTENCY_DAYS,
        step=1,
        disabled=not filter_cluster_consisten,
        help="Pakai toleransi spread yang sama dengan slider di atas, tapi harus rapat "
        "SETIAP HARI selama N hari terakhir berturut-turut -- bukan cuma hari ini. "
        "Ini yang bikin chart-nya kelihatan rapi/nempel seperti contoh, bukan cuma "
        "nyentuh sesaat lalu mencar lagi.",
    )

    filter_big_vol_history = st.sidebar.checkbox("Pernah big volume", value=False)
    big_vol_days = st.sidebar.slider(
        "Cek berapa hari terakhir",
        min_value=config.BIG_VOLUME_LOOKBACK_DAYS_MIN,
        max_value=config.BIG_VOLUME_LOOKBACK_DAYS_MAX,
        value=config.BIG_VOLUME_LOOKBACK_DAYS,
        step=1,
        disabled=not filter_big_vol_history,
        help="Cek dalam berapa hari terakhir volume pernah dianggap besar. Tidak memengaruhi Setup 2/3.",
    )
    big_vol_ratio = st.sidebar.slider(
        "Seberapa besar volume-nya (x rata-rata 20 hari)",
        min_value=config.VOL_MULTIPLIER_MIN,
        max_value=config.VOL_MULTIPLIER_MAX,
        value=config.VOL_MULTIPLIER,
        step=0.1,
        disabled=not filter_big_vol_history,
        help="Makin besar = makin ekstrem lonjakan volume yang dicari. Contoh: 2.0x berarti "
        "volume hari itu minimal 2x rata-rata 20 hari.",
    )

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
        and (
            r["Setup"] != "1"
            or not target_sma_filter
            or get_tp_period(r) in target_sma_filter
        )
        and (
            not filter_sma20_ketat
            or r["Setup"] != "1"
            or (r.get("SMA20_Cluster4_Spread_pct") is not None and r["SMA20_Cluster4_Spread_pct"] <= sma20_tol_pct)
        )
        and (
            not filter_cluster_consisten
            or r["Setup"] != "1"
            or cek_clustering_konsisten(charts.get(r["Ticker"]), cluster_consistency_days, sma20_tol_pct)
        )
        and (
            not filter_big_vol_history
            or r["Setup"] != "1"
            or cek_big_volume_terakhir(charts.get(r["Ticker"]), big_vol_days, big_vol_ratio)
        )
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
        render_result_row(row, charts, sma20_tol_pct, big_vol_days, big_vol_ratio, cluster_consistency_days)

    if n_show != "Semua" and len(filtered) > int(n_show):
        st.markdown(
            f"<p class='disclaimer'>{len(filtered) - int(n_show)} hasil lainnya disembunyikan. "
            f"Ubah filter di sidebar untuk melihat lebih banyak.</p>",
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    main()
