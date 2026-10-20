"""
Notifikasi Telegram harian: pola "mepet" + 7 ciri (hasil backtest 2 tahun).

Dipanggil di akhir run_screener.py memakai daily_data yang sudah di-download
(tidak download ulang). Isi kiriman:
  1. Ringkasan teks: kondisi pasar, lalu tiga daftar --
     - SINYAL    : sedang mepet, >= TG_MIN_CIRI dari 7 ciri, MA besar terdekat >= TG_MIN_JARAK_MA di atas
     - WATCHLIST : >= TG_MIN_CIRI ciri & MA besar jauh, sempat mepet <= TG_WINDOW_MEPET hari lalu
                   tapi sekarang pola rusak (tunggu mepet lagi). Tiap saham dipantau sejak hari
                   pertama masuk: ✅ berhasil kalau mepet lagi / sampai MA besar, ❌ gagal kalau
                   close turun >= TG_GAGAL_TURUN dari harga masuk atau TG_GAGAL_HARI hari tak mepet lagi
     - SEBELUM EVENT : saham yang lolos syarat watchlist dalam TG_EVENT_WINDOW hari bursa sebelum pasar anjlok / news
                   (deteksi otomatis + TG_EVENT_MANUAL), beserta kondisinya sekarang
  2. Chart candle + MA + volume untuk sinyal & watchlist yang masih dipantau (album maks 10 foto).

Pola mepet : MA3/5/10/20 selisih <= TG_SPREAD dan harga <= TG_DEKAT dari MA20.
7 ciri     : 1 spike volume >= 6x dalam 3 bln       2 MA60 < MA100 < MA200
             3 harga tidak di bawah MA20 (maks -1%)  4 sudah naik >= 15% dari low 3 bln
             5 harga < 200                           6 candle spike "ditolak" (ekor atas >= 50% / tutup bawah)
             7 sempat dibanting >= 12% di bawah MA20 dalam 20 hari

Butuh env TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID (GitHub secrets). Tanpa itu dilewati.
Uji lokal tanpa kirim:  python telegram_mepet.py --dry-run out_dir [--histori file.csv.gz]
"""

import io
import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

import config

NAMA_CIRI = {
    1: "spike vol ≥6x", 2: "MA besar rapi", 3: "≥ MA20", 4: "naik ≥15% dr dasar",
    5: "harga <200", 6: "spike ditolak", 7: "dibanting ≥12%",
}


# ============================================================
# HITUNG FITUR
# ============================================================
def siapkan(df):
    """Array numpy + indikator untuk satu saham (df: Open/High/Low/Close/Volume, index tanggal)."""
    a = {k: df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume")}
    a["tgl"] = pd.to_datetime(df.index).strftime("%Y-%m-%d").to_numpy()
    s = pd.Series(a["Close"])
    a["ma"] = {p: s.rolling(p).mean().to_numpy() for p in (3, 5, 10, 20, 60, 100, 200)}
    kecil = np.vstack([a["ma"][3], a["ma"][5], a["ma"][10], a["ma"][20]])
    a["spread"] = kecil.max(0) / kecil.min(0) - 1
    a["gap20"] = a["Close"] / a["ma"][20] - 1
    h, l, c, v = a["High"], a["Low"], a["Close"], a["Volume"]
    a["aktif"] = pd.Series((h > l).astype(float)).rolling(20).sum().to_numpy()
    a["nilai"] = pd.Series(c * v).rolling(20).median().to_numpy()
    a["vs20"] = pd.Series(v).rolling(20).mean().to_numpy()
    kond = ((a["spread"] <= config.TG_SPREAD) & (np.abs(a["gap20"]) <= config.TG_DEKAT)
            & (a["aktif"] >= config.TG_MIN_AKTIF) & (a["nilai"] >= config.TG_MIN_NILAI))
    a["kond"] = kond
    streak = np.zeros(len(c), int)
    for i in range(len(c)):
        streak[i] = (streak[i - 1] + 1 if i else 1) if kond[i] else 0
    a["streak"] = streak
    return a


def nilai_di(a, i):
    """Fitur + 7 ciri pada bar ke-i. None kalau data kurang / saham tidak aktif."""
    c, h, l, o, v, ma = a["Close"], a["High"], a["Low"], a["Open"], a["Volume"], a["ma"]
    if i < 200 or np.isnan(ma[200][i]) or a["aktif"][i] < config.TG_MIN_AKTIF or a["nilai"][i] < config.TG_MIN_NILAI:
        return None
    lo = i - 62
    iv = lo + int(np.argmax(v[lo:i + 1]))
    di_atas = {p: ma[p][i] for p in (60, 100, 200) if ma[p][i] > c[i]}
    q = min(di_atas, key=di_atas.get) if di_atas else None
    rng = h[iv] - l[iv]
    r = dict(
        close=c[i], tgl=a["tgl"][i], streak=int(a["streak"][i]),
        mepet5h=bool(a["kond"][max(0, i - config.TG_WINDOW_MEPET + 1):i + 1].any()),
        spread=a["spread"][i], gap20=a["gap20"][i],
        ma=q, ma_nilai=di_atas[q] if q else np.nan, ma_jarak=(di_atas[q] / c[i] - 1) if q else np.nan,
        spike=v[iv] / a["vs20"][iv] if a["vs20"][iv] else np.nan, spike_tgl=a["tgl"][iv],
        ekor=(h[iv] - max(o[iv], c[iv])) / rng if rng > 0 else 0.0,
        tutup=(c[iv] - l[iv]) / rng if rng > 0 else 1.0,
        dasar=c[i] / l[lo:i + 1].min() - 1, shake=l[i - 20:i + 1].min() / ma[20][i] - 1,
    )
    r["ciri"] = {
        1: r["spike"] >= 6,
        2: ma[60][i] < ma[100][i] < ma[200][i],
        3: r["gap20"] >= -0.01,
        4: r["dasar"] >= 0.15,
        5: c[i] < 200,
        6: r["ekor"] >= 0.5 or r["tutup"] < 0.4,
        7: r["shake"] <= -0.12,
    }
    r["skor"] = int(sum(bool(x) for x in r["ciri"].values()))
    return r


def lolos_watch(r):
    return r is not None and r["skor"] >= config.TG_MIN_CIRI and r["ma"] and r["ma_jarak"] >= config.TG_MIN_JARAK_MA


def syarat_watch(r):
    """Lolos ciri, sempat mepet dalam TG_WINDOW_MEPET hari, tapi belum cukup lama mepet untuk jadi sinyal."""
    return lolos_watch(r) and r["mepet5h"] and r["streak"] < config.TG_MIN_STREAK


def pantau_watch(a):
    """
    Telusuri TG_PANTAU_LOOKBACK bar terakhir: kapan saham masuk watchlist dan apa hasilnya.
    Return (aktif, selesai): aktif = episode yang masih dipantau hari ini (atau None),
    selesai = episode terakhir yang sudah berakhir berhasil/gagal (atau None).
    Episode baru hanya dimulai saat syarat berubah dari tidak lolos ke lolos, jadi saham yang
    sudah gagal tidak langsung masuk lagi esok harinya.
    """
    n = len(a["Close"])
    ep = selesai = None
    sebelumnya = False
    for i in range(max(201, n - config.TG_PANTAU_LOOKBACK), n):
        r = nilai_di(a, i)
        lolos = syarat_watch(r)
        if ep is None:
            if lolos and not sebelumnya:
                ep = dict(i0=i, r0=r)
            sebelumnya = lolos
            continue
        r0 = ep["r0"]
        if a["streak"][i] >= config.TG_MIN_STREAK:
            hasil = ("berhasil", f"mepet lagi {config.TG_MIN_STREAK} hari")
        elif a["High"][i] >= r0["ma_nilai"]:
            hasil = ("berhasil", f"sampai MA{r0['ma']}")
        elif a["Close"][i] <= r0["close"] * (1 - config.TG_GAGAL_TURUN):
            hasil = ("gagal", f"turun ≥{config.TG_GAGAL_TURUN * 100:.0f}% sejak masuk")
        elif i - ep["i0"] >= config.TG_GAGAL_HARI:
            hasil = ("gagal", f"{config.TG_GAGAL_HARI} hari tidak mepet lagi")
        else:
            hasil = None
        if hasil:
            ep.update(status=hasil[0], alasan=hasil[1], i1=i, tgl1=a["tgl"][i], close1=a["Close"][i])
            selesai, ep = ep, None
        sebelumnya = lolos
    if ep:
        ep["hari"] = n - 1 - ep["i0"]
    return ep, selesai


# ============================================================
# KONDISI PASAR & DETEKSI EVENT
# ============================================================
def kondisi_pasar(daily_data):
    cl = pd.DataFrame({t: df["Close"] for t, df in daily_data.items()})
    cl.index = pd.to_datetime(cl.index).strftime("%Y-%m-%d")
    cl = cl.sort_index()
    harian = cl / cl.shift(1) - 1
    murah = cl.shift(1) < 200
    med_semua = harian.median(axis=1)
    med_murah = harian.where(murah).median(axis=1)
    info = dict(
        tgl=cl.index[-1],
        pasar20=float((cl.iloc[-1] / cl.iloc[-21] - 1).median()),
        atas20=float((cl.iloc[-1] > cl.rolling(20).mean().iloc[-1]).mean()),
        hari_ini=float(med_semua.iloc[-1]),
    )
    tgl = list(cl.index)
    events = {}
    awal = max(1, len(tgl) - config.TG_EVENT_LOOKBACK)
    for k in range(awal, len(tgl)):
        d = tgl[k]
        kena_semua = med_semua.iloc[k] <= config.TG_SHOCK_SEMUA
        kena_murah = med_murah.iloc[k] <= config.TG_SHOCK_MURAH
        if not (kena_semua or kena_murah):
            continue
        kemarin_shock = (med_semua.iloc[k - 1] <= config.TG_SHOCK_SEMUA) or (med_murah.iloc[k - 1] <= config.TG_SHOCK_MURAH)
        if kemarin_shock:
            continue  # cukup hari pertama dari rentetan hari anjlok
        if kena_semua:
            label = f"Pasar anjlok (median saham {pct(med_semua.iloc[k])})"
        else:
            label = f"Saham murah dibanting (median saham &lt;200 {pct(med_murah.iloc[k])})"
        events[d] = dict(label=label, sebelum=tgl[k - 1])
    for d, label in config.TG_EVENT_MANUAL.items():
        if d in tgl and tgl.index(d) >= awal:
            events[d] = dict(label=label, sebelum=tgl[tgl.index(d) - 1])
    return info, dict(sorted(events.items()))


# ============================================================
# FORMAT
# ============================================================
def rp(v):
    return f"{v:,.0f}".replace(",", ".")


def pct(v, tanda=True):
    s = f"{v * 100:+.1f}%" if tanda else f"{v * 100:.1f}%"
    return s.replace(".", ",")


def tgl_id(d):
    return f"{d[8:]}/{d[5:7]}"


def kurang(r):
    hilang = [str(k) for k, x in r["ciri"].items() if not x]
    return "lengkap" if not hilang else "kurang " + ",".join(hilang)


def baris(t, r, ekstra=""):
    return (f"<b>{t}</b> Rp{rp(r['close'])} · <b>{r['skor']}/7</b> ({kurang(r)}) · "
            f"{'MA' + str(r['ma'])} {pct(r['ma_jarak'])}{ekstra}")


def susun(daily_data):
    """Hitung semua daftar. Return dict siap kirim."""
    info, events = kondisi_pasar(daily_data)
    cache, sinyal, watch, hasil = {}, [], [], []
    for t, df in daily_data.items():
        if len(df) < 260:
            continue
        a = siapkan(df)
        if a["tgl"][-1] != info["tgl"]:
            continue  # tidak ada transaksi hari ini (suspend dll)
        cache[t] = a
        r = nilai_di(a, len(df) - 1)
        if lolos_watch(r) and r["streak"] >= config.TG_MIN_STREAK:
            sinyal.append((t, r))
        aktif, selesai = pantau_watch(a)
        if aktif and lolos_watch(r):  # ciri turun di bawah syarat -> tetap dipantau tapi tidak ditampilkan
            aktif["sebelumnya"] = selesai
            watch.append((t, r, aktif))
        if selesai and len(df) - 1 - selesai["i1"] < config.TG_TAMPIL_SELESAI:
            hasil.append((t, selesai))
    sinyal.sort(key=lambda x: (-x[1]["skor"], -x[1]["ma_jarak"]))
    watch.sort(key=lambda x: (-x[1]["skor"], x[1]["spread"]))
    hasil.sort(key=lambda x: (x[1]["status"] != "berhasil", x[1]["tgl1"], x[0]))

    per_event = []
    for d, ev in events.items():
        daftar = []
        for t, a in cache.items():
            pos = np.where(a["tgl"] == ev["sebelum"])[0]
            if not len(pos):
                continue
            r0 = None  # hari lolos terakhir dalam TG_EVENT_WINDOW hari bursa sebelum event
            for i in range(int(pos[0]), max(0, int(pos[0]) - config.TG_EVENT_WINDOW), -1):
                r = nilai_di(a, i)
                if lolos_watch(r) and r["mepet5h"]:
                    r0 = r
                    break
            if r0 is None:
                continue
            r1 = nilai_di(a, len(a["tgl"]) - 1)
            if r1 is None:
                continue
            daftar.append((t, r0, r1))
        daftar.sort(key=lambda x: (-x[1]["skor"], x[1]["spread"]))
        per_event.append((d, ev, daftar))
    return dict(info=info, sinyal=sinyal, watch=watch, hasil=hasil, events=per_event, cache=cache)


def teks_ringkasan(h):
    info = h["info"]
    out = [f"<b>📊 Pola Mepet + 7 Ciri · data {tgl_id(info['tgl'])}</b>",
           f"Pasar: hari ini {pct(info['hari_ini'])} · 20 hari {pct(info['pasar20'])} · "
           f"{info['atas20'] * 100:.0f}% saham di atas MA20".replace(".", ",")]
    if info["pasar20"] < -0.02:
        out.append("ℹ️ Pasar 20 hari sedang turun: historis sinyal yang muncul saat begini lebih sering berhasil (90%).")
    out.append("")
    out.append(f"<b>🎯 SINYAL — sedang mepet, ≥{config.TG_MIN_CIRI}/7 ciri, MA besar ≥{config.TG_MIN_JARAK_MA * 100:.0f}% di atas</b>")
    if h["sinyal"]:
        out += [baris(t, r, f" · mepet {r['streak']} hari") for t, r in h["sinyal"]]
    else:
        out.append("– belum ada hari ini")
    out.append("")
    out.append(f"<b>👀 WATCHLIST — sempat mepet ≤{config.TG_WINDOW_MEPET} hari lalu, tunggu mepet lagi</b>")
    if h["watch"]:
        for t, r, ep in h["watch"]:
            ubah = r["close"] / ep["r0"]["close"] - 1
            pantau = ("🆕 masuk hari ini" if ep["hari"] == 0 else
                      f"⏳ hari ke-{ep['hari']} (masuk {tgl_id(ep['r0']['tgl'])} {pct(ubah)})")
            lama = ep["sebelumnya"]
            if lama:
                pantau += f" · masuk lagi setelah {'✅' if lama['status'] == 'berhasil' else '❌'} {tgl_id(lama['tgl1'])}"
            out.append(baris(t, r, f" · vs MA20 {pct(r['gap20'])} · {pantau}"))
    else:
        out.append("– kosong")
    if h["hasil"]:
        out.append("")
        out.append(f"<b>📋 HASIL WATCHLIST — {config.TG_TAMPIL_SELESAI} hari bursa terakhir</b>")
        for t, ep in h["hasil"]:
            ikon = "✅" if ep["status"] == "berhasil" else "❌"
            r0 = ep["r0"]
            out.append(f"{ikon} <b>{t}</b> masuk {tgl_id(r0['tgl'])} Rp{rp(r0['close'])} → {rp(ep['close1'])} "
                       f"({pct(ep['close1'] / r0['close'] - 1)}) · {ep['alasan']} ({tgl_id(ep['tgl1'])})")
    for d, ev, daftar in h["events"]:
        out.append("")
        out.append(f"<b>📌 LOLOS SEBELUM {tgl_id(d)} — {ev['label']}</b>")
        if not daftar:
            out.append(f"– tidak ada yang lolos dalam {config.TG_EVENT_WINDOW} hari bursa sebelumnya")
        for t, r0, r1 in daftar:
            status = "✅ sudah mepet lagi" if r1["streak"] >= 1 else f"vs MA20 {pct(r1['gap20'])}"
            out.append(f"<b>{t}</b> {r0['skor']}/7 ({tgl_id(r0['tgl'])}) · Rp{rp(r0['close'])} → {rp(r1['close'])} "
                       f"({pct(r1['close'] / r0['close'] - 1)}) · {status}"
                       + (f" · MA{r1['ma']} {pct(r1['ma_jarak'])}" if r1["ma"] else ""))
    out += ["", f"<i>✅ berhasil = mepet lagi {config.TG_MIN_STREAK} hari / sampai MA besar · ❌ gagal = close turun "
                f"≥{config.TG_GAGAL_TURUN * 100:.0f}% dari harga masuk / {config.TG_GAGAL_HARI} hari bursa tidak mepet lagi</i>",
            "<i>Ciri: 1 spike vol ≥6x (3 bln) · 2 MA60&lt;MA100&lt;MA200 · 3 harga ≥ MA20 · "
                "4 naik ≥15% dari dasar 3 bln · 5 harga &lt;200 · 6 candle spike ditolak · "
                "7 sempat dibanting ≥12% di bawah MA20</i>",
            "<i>Backtest 2 th (mepet, ≥5/7, MA besar ≥10%): 81% sampai MA besar ≤60 hari, median +10%. "
            "Bukan rekomendasi — validasi LPM, frekuensi & asing.</i>"]
    return "\n".join(out)


# ============================================================
# CHART
# ============================================================
SURFACE, TEXT, TEXT2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e9e8e4"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
MA_STYLE = {3: (BLUE, 1.1, "-"), 5: (BLUE, 1.1, "-"), 10: (BLUE, 1.1, "-"), 20: (ORANGE, 2.0, "-"),
            60: (AQUA, 2.0, "-"), 100: (TEXT, 2.0, "-"), 200: (TEXT, 1.6, (0, (5, 3)))}


def gambar(a, judul, subjudul, arsir_dari=None, n=90):
    """Chart candle + MA + volume (PNG bytes), gaya sama dengan chart analisa."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    s = slice(len(a["Close"]) - n, None)
    o, h, l, c, v = (a[k][s] for k in ("Open", "High", "Low", "Close", "Volume"))
    tgl, vs = a["tgl"][s], a["vs20"][s]
    m = len(c)
    fig = plt.figure(figsize=(11, 6.4), dpi=110, facecolor=SURFACE)
    ax = fig.add_axes([0.08, 0.30, 0.78, 0.56], facecolor=SURFACE)
    axv = fig.add_axes([0.08, 0.09, 0.78, 0.17], facecolor=SURFACE, sharex=ax)
    for i in range(m):
        ax.vlines(i, l[i], h[i], color=MUTED, lw=0.9, zorder=2)
        bawah, atas = sorted((o[i], c[i]))
        tinggi = max(atas - bawah, (h[i] - l[i]) * 0.02 or 0.01)
        ax.add_patch(Rectangle((i - 0.32, bawah), 0.64, tinggi, facecolor=SURFACE if c[i] >= o[i] else MUTED,
                               edgecolor=MUTED, lw=0.9, zorder=3))
    label = []
    for p, (col, lw, ls) in MA_STYLE.items():
        y = a["ma"][p][s]
        ax.plot(range(m), y, color=col, lw=lw, ls=ls, zorder=4)
        if p not in (3, 5) and not np.isnan(y[-1]):
            label.append((y[-1], "MA3/5/10" if p == 10 else f"MA{p}", col, ls))
    lo_, hi_ = np.nanmin(l), max(np.nanmax(h), *(y for y, *_ in label))
    pad = (hi_ - lo_) * 0.06
    ax.set_ylim(lo_ - pad, hi_ + pad)
    ax.set_xlim(-1, m + 0.5)
    label.sort()
    jarak_min = (hi_ - lo_ + 2 * pad) * 0.045
    sebelum = None
    for y, txt, col, ls in label:
        yy = y if sebelum is None or y - sebelum >= jarak_min else sebelum + jarak_min
        sebelum = yy
        ax.annotate(f"{txt}  {rp(y)}", xy=(m - 1, yy), xytext=(m + 0.8, yy), textcoords="data", va="center",
                    fontsize=8.5, color=TEXT, annotation_clip=False)
        ax.plot([m + 0.15, m + 0.65], [yy, yy], color=col, lw=2.2, clip_on=False, ls=ls)
    rasio = np.where(vs > 0, v / np.where(vs > 0, vs, 1), 0)
    axv.bar(range(m), v, width=0.64, color=[TEXT2 if r >= 3 else "#cfcdc6" for r in rasio], zorder=2)
    if arsir_dari:
        idx = [i for i in range(m) if tgl[i] >= arsir_dari]
        if idx:
            axv.axvspan(idx[0] - 0.5, m - 0.5, color="#f1efe9", zorder=0)
            ax.axvspan(idx[0] - 0.5, m - 0.5, color="#f6f5f1", zorder=0)
    axv.set_ylim(0, (np.nanmax(v) or 1) * 1.15)
    axv.set_yticks([])
    ket = f"; area arsir = sejak masuk watchlist {tgl_id(arsir_dari)}" if arsir_dari else ""
    axv.text(0.0, 1.04, f"Volume (batang gelap = di atas 3x rata-rata 20 hari{ket})", transform=axv.transAxes,
             fontsize=8, color=TEXT2)
    for x in (ax, axv):
        for sp in ("top", "right", "left"):
            x.spines[sp].set_visible(False)
        x.spines["bottom"].set_color(GRID)
        x.tick_params(colors=TEXT2, labelsize=8, length=0)
    ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=7, integer=True))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda val, _: rp(val)))
    plt.setp(ax.get_xticklabels(), visible=False)
    step = max(1, m // 8)
    axv.set_xticks(list(range(m))[::step])
    axv.set_xticklabels([tgl_id(d) for d in tgl][::step])
    fig.text(0.08, 0.945, judul, fontsize=14, fontweight="bold", color=TEXT)
    fig.text(0.08, 0.905, subjudul, fontsize=9, color=TEXT2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    return buf.getvalue()


def sub_ciri(r):
    tanda = " ".join(("✓" if x else "✗") + NAMA_CIRI[k] for k, x in r["ciri"].items())
    spike = f"{r['spike']:.1f}".replace(".", ",")
    return (f"MA{r['ma']} {rp(r['ma_nilai'])} ({pct(r['ma_jarak'])}) · spike {spike}x "
            f"({tgl_id(r['spike_tgl'])}) · {tanda}") if r["ma"] else tanda


def daftar_chart(h):
    """[(png, caption)] untuk tiap kelompok, tanpa duplikat ticker."""
    sudah, kelompok = set(), []

    def tambah(nama, isi, maks):
        foto = []
        for t, r, judul, cap, arsir in isi:
            if t in sudah or len(foto) >= maks:
                continue
            sudah.add(t)
            foto.append((gambar(h["cache"][t], judul, sub_ciri(r), arsir), cap))
        if foto:
            kelompok.append((nama, foto))

    tambah("🎯 Sinyal", [(t, r, f"{t} · Rp {rp(r['close'])} · {r['skor']}/7 ciri · mepet {r['streak']} hari",
                          f"🎯 <b>{t}</b> {r['skor']}/7 · MA{r['ma']} {pct(r['ma_jarak'])}", None)
                         for t, r in h["sinyal"]], config.TG_MAX_CHART)
    tambah("👀 Watchlist", [(t, r, f"{t} · Rp {rp(r['close'])} · {r['skor']}/7 ciri · pantau hari ke-{ep['hari']}",
                             f"👀 <b>{t}</b> {r['skor']}/7 · masuk {tgl_id(ep['r0']['tgl'])} "
                             f"{pct(r['close'] / ep['r0']['close'] - 1)} · vs MA20 {pct(r['gap20'])}", ep["r0"]["tgl"])
                            for t, r, ep in h["watch"]], config.TG_MAX_CHART)
    return kelompok


# ============================================================
# KIRIM
# ============================================================
def _api(token, method, data, files=None):
    import requests

    for coba in range(4):
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files, timeout=90)
        if r.status_code == 429:
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5) + 1)
            continue
        if not r.ok:
            raise RuntimeError(f"Telegram {method} gagal {r.status_code}: {r.text[:300]}")
        return r.json()
    raise RuntimeError(f"Telegram {method} gagal: rate limit terus")


def potong(teks, maks=4000):
    bagian, buf = [], ""
    for line in teks.split("\n"):
        if len(buf) + len(line) + 1 > maks:
            bagian.append(buf)
            buf = ""
        buf += line + "\n"
    return bagian + ([buf] if buf.strip() else [])


def kirim_harian(daily_data, dry_run_dir=None, log=print):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not dry_run_dir and not (token and chat):
        log("Telegram dilewati (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum di-set).")
        return
    h = susun(daily_data)
    teks = teks_ringkasan(h)
    kelompok = daftar_chart(h)
    log(f"Telegram: {len(h['sinyal'])} sinyal, {len(h['watch'])} watchlist, {len(h['hasil'])} hasil, {len(h['events'])} event, "
        f"{sum(len(f) for _, f in kelompok)} chart.")
    if dry_run_dir:
        os.makedirs(dry_run_dir, exist_ok=True)
        with open(os.path.join(dry_run_dir, "pesan.html"), "w") as f:
            f.write(teks)
        n = 0
        for nama, foto in kelompok:
            for png, cap in foto:
                n += 1
                with open(os.path.join(dry_run_dir, f"{n:02d}.png"), "wb") as f:
                    f.write(png)
        log(f"Dry run tersimpan di {dry_run_dir}")
        return
    for bagian in potong(teks):
        _api(token, "sendMessage", {"chat_id": chat, "text": bagian, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"})
    for nama, foto in kelompok:
        for k in range(0, len(foto), 10):
            album = foto[k:k + 10]
            media = [{"type": "photo", "media": f"attach://f{j}", "caption": cap, "parse_mode": "HTML"}
                     for j, (_, cap) in enumerate(album)]
            files = {f"f{j}": (f"f{j}.png", png, "image/png") for j, (png, _) in enumerate(album)}
            _api(token, "sendMediaGroup", {"chat_id": chat, "media": json.dumps(media)}, files)
            time.sleep(1.5)
    log("Telegram terkirim.")


def _muat_histori(path):
    data = pd.read_csv(path)
    out = {}
    for t, df in data.groupby("Ticker"):
        df = df.sort_values("Date").set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]
        out[t] = df
    return out


if __name__ == "__main__":
    # python telegram_mepet.py --dry-run out_dir [--histori file.csv.gz]   (tanpa --histori: download dulu)
    args = sys.argv[1:]
    out_dir = args[args.index("--dry-run") + 1] if "--dry-run" in args else None
    if "--histori" in args:
        daily = _muat_histori(args[args.index("--histori") + 1])
    else:
        import run_screener
        import screener

        daily = screener.download_daily(run_screener.get_all_tickers(), period="2y")
    print(datetime.now().strftime("%H:%M:%S"), f"{len(daily)} saham")
    kirim_harian(daily, dry_run_dir=out_dir)
