"""
Bot Telegram strategi "SMA20 lilit -> tembus SMA20" (aturan & angka di config.py, bagian BOT TELEGRAM).

  python telegram_bot.py kirim          ringkasan singkat (dijadwalkan 12:00 & 18:00 WIB hari bursa)
  python telegram_bot.py balas          balas pesan berisi kode saham (mis. "BAIK") dengan chart

Uji tanpa Telegram (hasil disimpan ke folder):
  python telegram_bot.py kirim --dry-run out [--histori file.csv.gz]
  python telegram_bot.py chart BAIK --dry-run out [--histori file.csv.gz]

Butuh env TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID. Bot hanya membalas chat TELEGRAM_CHAT_ID.
LPM tidak dihitung di sini (datanya tidak tersedia di Yahoo) -- tetap dicek manual.
"""

import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config

WIB = timezone(timedelta(hours=7))
BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
         "September", "Oktober", "November", "Desember"]
MA_BESAR = (60, 100, 200)
MA_JAUH = (60, 100, 200, 112, 224, 448)


# ============================================================
# ANALISA
# ============================================================
def siapkan(df):
    """Array numpy + indikator untuk satu saham (df: Open/High/Low/Close/Volume, index tanggal)."""
    a = {k: df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume")}
    a["tgl"] = pd.to_datetime(df.index).strftime("%Y-%m-%d").to_numpy()
    o, h, l, c, v = a["Open"], a["High"], a["Low"], a["Close"], a["Volume"]
    s = pd.Series(c)
    a["ma"] = {p: s.rolling(p).mean().to_numpy() for p in (3, 5, 10, 20) + MA_JAUH}
    k = np.vstack([a["ma"][3], a["ma"][5], a["ma"][10], a["ma"][20]])
    spread = k.max(0) / k.min(0) - 1
    gap = c / a["ma"][20] - 1
    aktif = pd.Series((h > l).astype(float)).rolling(20).sum().to_numpy()
    nilai = pd.Series(c * v).rolling(20).median().to_numpy()
    a["vs20"] = pd.Series(v).rolling(20).mean().to_numpy()
    a["likuid"] = (aktif >= config.TG_MIN_AKTIF) & (nilai >= config.TG_MIN_NILAI)
    a["streak"] = _streak((spread <= config.TG_SPREAD) & (np.abs(gap) <= config.TG_DEKAT) & a["likuid"])
    a["streak_longgar"] = _streak((spread <= config.TG_PANTUL_SPREAD) & (np.abs(gap) <= config.TG_PANTUL_DEKAT) & a["likuid"])
    pc = np.r_[np.nan, c[:-1]]
    a["barbar"] = (((h - l) / pc >= 0.15) | ((o - pc) / pc >= 0.10)).astype(int)
    a["skor"] = skor_tren(df)
    return a


def skor_tren(df):
    """Skor 0-6 per hari: TSI > 0, Guppy pendek > panjang, SMA60 naik, volume MA20 > MA120, ADX >= 20, BB Width < 11%."""
    h, l, c, v = (df[k].astype(float).reset_index(drop=True) for k in ("High", "Low", "Close", "Volume"))
    ema = lambda x, n: x.ewm(span=n, adjust=False).mean()
    wilder = lambda x, n: x.ewm(alpha=1 / n, adjust=False).mean()
    m = c.diff()
    tsi = ema(ema(m, 25), 13) / ema(ema(m.abs(), 25), 13)
    guppy = (pd.concat([ema(c, n) for n in (3, 5, 8, 10, 12, 15)], axis=1).mean(axis=1)
             / pd.concat([ema(c, n) for n in (30, 35, 40, 45, 50, 60)], axis=1).mean(axis=1))
    sma60 = c.rolling(60).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    naik, turun = h.diff(), -l.diff()
    pdi = 100 * wilder(naik.where((naik > turun) & (naik > 0), 0), 14) / wilder(tr, 14)
    ndi = 100 * wilder(turun.where((turun > naik) & (turun > 0), 0), 14) / wilder(tr, 14)
    adx = wilder(100 * (pdi - ndi).abs() / (pdi + ndi), 14)
    bbw = 4 * c.rolling(20).std() / c.rolling(20).mean()
    cek = [tsi > 0, guppy > 1, sma60 > sma60.shift(20), v.rolling(20).mean() > v.rolling(120).mean(), adx >= 20, bbw < 0.11]
    return sum(x.fillna(False).astype(int) for x in cek).to_numpy()


def peluang(a, i):
    return config.TG_PELUANG[int(a["skor"][i])]


def _streak(mask):
    out = np.zeros(len(mask), int)
    for i in range(len(mask)):
        out[i] = (out[i - 1] + 1 if i else 1) if mask[i] else 0
    return out


def ada_ma_besar_di_atas(a, i):
    return any(not np.isnan(a["ma"][p][i]) and a["ma"][p][i] > a["Close"][i] for p in MA_BESAR)


def setup_di(a, i):
    """Hari ke-i: lilit cukup lama, harga di bawah SMA20 (atap), dan ada MA60/100/200 di atas."""
    return a["streak"][i] >= config.TG_LILIT_HARI and a["Close"][i] < a["ma"][20][i] and ada_ma_besar_di_atas(a, i)


def lolos_saringan(a, i):
    return (a["Close"][i] < config.TG_HARGA_MAKS and a["likuid"][i]
            and a["barbar"][max(0, i - 59):i + 1].sum() < config.TG_BARBAR_MAKS)


def masuk_di(a, i, cek_skor=True):
    """Hari ke-i: close tembus SMA20 setelah setup dalam TG_TUNGGU hari terakhir, skor tren cukup."""
    c, m20 = a["Close"], a["ma"][20]
    if i < 1 or not (c[i] > m20[i] and c[i - 1] <= m20[i - 1]) or not lolos_saringan(a, i):
        return False
    if cek_skor and a["skor"][i] < config.TG_SKOR_MIN:
        return False
    return any(setup_di(a, s) for s in range(max(0, i - config.TG_TUNGGU), i))


def target_di(a, i):
    """(mode, nama_ma, level) untuk entry di hari ke-i. level None = belum ada target (tahan)."""
    c, ma = a["Close"], a["ma"]
    dekat = [p for p in (112, 224) if not np.isnan(ma[p][i]) and
             (c[i] < ma[p][i] <= c[i] * (1 + config.TG_K2_JARAK) or (c[i] > ma[p][i] and c[i - 1] <= ma[p][i - 1]))]
    if dekat:
        cand = {p: ma[p][i] for p in MA_JAUH if not np.isnan(ma[p][i]) and ma[p][i] >= c[i] * (1 + config.TG_K2_TARGET_MIN)}
        mode = "jauh"
    else:
        cand = {p: ma[p][i] for p in MA_BESAR if not np.isnan(ma[p][i]) and ma[p][i] > c[i] * 1.005}
        mode = "dekat"
    if not cand:
        return mode, None, None
    p = min(cand, key=cand.get)
    return mode, p, cand[p]


def cari_banting(a, i):
    """PANTUL (gaya STRK): lilit longgar, lalu dibanting >= TG_PANTUL_BANTING dalam TG_TUNGGU hari terakhir.
    Return (j = hari lilit terakhir, d = hari dasar) atau None. Gorengan dihitung SEBELUM dibanting."""
    c, l = a["Close"], a["Low"]
    if c[i] >= config.TG_HARGA_MAKS or not a["likuid"][i]:
        return None
    lo = max(0, i - config.TG_TUNGGU)
    d = lo + int(np.argmin(l[lo:i + 1]))
    js = [j for j in range(max(0, d - config.TG_PANTUL_JEJAK), d) if a["streak_longgar"][j] >= config.TG_PANTUL_LILIT]
    if not js:
        return None
    j = js[-1]
    if l[d] / c[j] - 1 > -config.TG_PANTUL_BANTING or a["barbar"][max(0, j - 59):j + 1].sum() >= config.TG_BARBAR_MAKS:
        return None
    return j, d


def pantul_di(a, i):
    """Hari ke-i: setelah dibanting (cari_banting), close tembus SMA20."""
    c, m20 = a["Close"], a["ma"][20]
    if i < 1 or not (c[i] > m20[i] and c[i - 1] <= m20[i - 1]):
        return None
    vol = a["Volume"][i] / a["vs20"][i] if a["vs20"][i] else 0
    if config.TG_PANTUL_VOL_MAKS and vol >= config.TG_PANTUL_VOL_MAKS:
        return None
    return cari_banting(a, i)


def entri_di(a, e):
    """Entry di hari e: dict(jenis 'masuk'|'pantul', mode, target, stop) atau None."""
    c = a["Close"]
    if masuk_di(a, e):
        mode, _, tgt = target_di(a, e)
        return dict(jenis="masuk", mode=mode, target=tgt, stop=c[e] * (1 - config.TG_STOP))
    p = pantul_di(a, e)
    if p:
        j, d = p
        return dict(jenis="pantul", mode="pantul", target=c[j] if c[j] > c[e] else None, stop=a["Low"][d] * 0.99)
    return None


def jalur(a, e, sampai, en):
    """Nasib entry hari e sampai bar 'sampai': ('stop'|'target'|None, hari kejadian)."""
    h, l = a["High"], a["Low"]
    for j in range(e + 1, sampai + 1):
        if l[j] <= en["stop"]:
            return "stop", j
        if en["target"] is not None and h[j] >= en["target"]:
            return "target", j
    return None, None


def status(a, i=None):
    """Kondisi saham pada bar i (default hari terakhir) untuk ringkasan & caption chart."""
    i = len(a["Close"]) - 1 if i is None else i
    c, ma = a["Close"], a["ma"]
    st = dict(i=i, close=c[i], tgl=a["tgl"][i], lolos=lolos_saringan(a, i), skor=int(a["skor"][i]), peluang=peluang(a, i),
              vol=a["Volume"][i] / a["vs20"][i] if a["vs20"][i] else np.nan)
    en = entri_di(a, i)
    if en:
        st[en["jenis"]] = en
    elif c[i] < ma[20][i] and cari_banting(a, i):
        st["calon_pantul"] = ma[20][i] / c[i] - 1
    elif masuk_di(a, i, cek_skor=False):
        st["skor_rendah"] = True
    if lolos_saringan(a, i) and setup_di(a, i) and st["skor"] >= config.TG_SKOR_MIN:
        st["pantau"] = ma[20][i] / c[i] - 1
        st["pantau_jauh"] = any(not np.isnan(ma[p][i]) and c[i] < ma[p][i] <= c[i] * (1 + config.TG_K2_JARAK) for p in (112, 224))
    # entry yang masih berjalan / baru selesai hari ini
    for e in range(max(1, i - config.TG_TUNGGU), i):
        en = entri_di(a, e)
        if not en:
            continue
        hasil, j = jalur(a, e, i, en)
        if hasil and j == i:
            st["selesai"] = (hasil, e, en)
        elif hasil is None:
            st["jalan"] = (e, en)
            sma_e = [p for p in (112, 224) if not np.isnan(ma[p][e]) and ma[p][e] > c[e]]
            if en["mode"] == "dekat" and any(c[i] > ma[p][i] and c[i - 1] <= ma[p][i - 1] for p in sma_e):
                st["tambah"] = e
    return st


# ============================================================
# FORMAT
# ============================================================
def rp(v):
    return f"{v:,.0f}".replace(",", ".")


def pct(v):
    return f"{v * 100:+.0f}%"


def tanggal(d):
    return f"{int(d[8:])} {BULAN[int(d[5:7]) - 1]} {d[:4]}"


def teks_target(en, close):
    tgt = en["target"]
    arah = f"→ {rp(tgt)} ({pct(tgt / close - 1)})" if tgt else "→ tahan, tanpa target"
    return f"{arah} · stop {rp(en['stop'])}"


def teks_peluang(st):
    return f"peluang {st['peluang']}% ({st['skor']}/6)"


def ringkasan(semua, jam):
    masuk = [(t, s) for t, s in semua.items() if "masuk" in s]
    masuk.sort(key=lambda x: (x[1]["masuk"]["mode"] != "jauh", -(x[1]["vol"] if x[1]["vol"] == x[1]["vol"] else 0)))
    pantul = [(t, s) for t, s in semua.items() if "pantul" in s]
    calon = sorted(((t, s) for t, s in semua.items() if "calon_pantul" in s), key=lambda x: x[1]["calon_pantul"])
    tambah = [t for t, s in semua.items() if "tambah" in s]
    target = [(t, s) for t, s in semua.items() if s.get("selesai", ("",))[0] == "target"]
    stop = [t for t, s in semua.items() if s.get("selesai", ("",))[0] == "stop"]
    pantau = [(t, s) for t, s in semua.items() if "pantau" in s and "masuk" not in s]
    pantau.sort(key=lambda x: (not x[1]["pantau_jauh"], x[1]["pantau"]))
    tgl = next(iter(semua.values()))["tgl"] if semua else datetime.now(WIB).strftime("%Y-%m-%d")

    out = [f"📊 {jam} · {tanggal(tgl)[:-5]}"]
    if masuk:
        out.append("🟢 MASUK")
        out += [f"{t} {rp(s['close'])} {teks_target(s['masuk'], s['close'])} · {teks_peluang(s)}" for t, s in masuk[:config.TG_MAKS_SINYAL]]
    else:
        out.append("🟢 MASUK: belum ada")
    if pantul:
        out.append("🔄 PANTUL")
        out += [f"{t} {rp(s['close'])} {teks_target(s['pantul'], s['close'])}" for t, s in pantul[:config.TG_MAKS_SINYAL]]
    if tambah:
        out.append("➕ TAMBAH: " + ", ".join(tambah))
    if target:
        out.append("🎯 TARGET: " + ", ".join(f"{t} ({pct(s['_ret_target'])})" for t, s in target))
    if stop:
        out.append("⛔ STOP: " + ", ".join(stop))
    if pantau:
        out.append("👀 PANTAU: " + ", ".join(f"{t} ({s['pantau'] * 100:.1f}% · {s['peluang']}%)".replace(".", ",")
                                             for t, s in pantau[:config.TG_MAKS_PANTAU]))
    if calon:
        out.append("🔄 CALON PANTUL: " + ", ".join(f"{t} ({s['calon_pantul'] * 100:.1f}%)".replace(".", ",")
                                                  for t, s in calon[:config.TG_MAKS_PANTAU]))
    if pantau or calon:
        out.append("(angka = jarak ke tembus SMA20" + (" · peluang naik 15% duluan)" if pantau else ")"))
    out.append("Cek LPM dulu · ketik kode saham untuk chart")
    return "\n".join(out)


def caption(t, st):
    if "masuk" in st:
        return f"{t} {rp(st['close'])} · 🟢 masuk hari ini {teks_target(st['masuk'], st['close'])} · {teks_peluang(st)}"
    if "pantul" in st:
        return f"{t} {rp(st['close'])} · 🔄 pantul hari ini {teks_target(st['pantul'], st['close'])}"
    if "selesai" in st:
        hasil, e, en = st["selesai"]
        return f"{t} {rp(st['close'])} · {'🎯 kena target' if hasil == 'target' else '⛔ kena stop'} (masuk {tanggal(st['_tgl_e'])})"
    if "jalan" in st:
        e, en = st["jalan"]
        ubah = st["close"] / st["_close_e"] - 1
        arah = f"target {rp(en['target'])}" if en["target"] else "tahan"
        jenis = "pantul" if en["jenis"] == "pantul" else "posisi"
        teks = f"{t} {rp(st['close'])} · {jenis} jalan sejak {tanggal(st['_tgl_e'])} ({pct(ubah)}) · {arah} · stop {rp(en['stop'])}"
        return teks + (" · ➕ tambah" if "tambah" in st else "")
    if "pantau" in st:
        return f"{t} {rp(st['close'])} · 👀 pantau: {st['pantau'] * 100:.0f}% lagi tembus SMA20 · {teks_peluang(st)}"
    if "skor_rendah" in st:
        return f"{t} {rp(st['close'])} · tembus SMA20 tapi skor tren rendah · {teks_peluang(st)}, tidak masuk filter"
    if "calon_pantul" in st:
        return f"{t} {rp(st['close'])} · 🔄 calon pantul: {st['calon_pantul'] * 100:.0f}% lagi tembus SMA20"
    if st["close"] >= config.TG_HARGA_MAKS:
        return f"{t} {rp(st['close'])} · harga ≥ {config.TG_HARGA_MAKS}, di luar kriteria"
    if not st["lolos"]:
        return f"{t} {rp(st['close'])} · ⚠️ gorengan / sepi, di luar kriteria"
    return f"{t} {rp(st['close'])} · belum masuk kriteria"


def lengkapi(a, st):
    """Tambah info harga entry untuk entry yang masih jalan / selesai."""
    for key in ("jalan", "selesai"):
        if key in st:
            e = st[key][0] if key == "jalan" else st[key][1]
            st["_tgl_e"], st["_close_e"] = a["tgl"][e], a["Close"][e]
            if key == "selesai" and st[key][0] == "target":
                st["_ret_target"] = st[key][2]["target"] / a["Close"][e] - 1
    return st


# ============================================================
# CHART
# ============================================================
SURFACE, TEXT, TEXT2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e9e8e4"
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#c8352b"
MA_STYLE = {3: (BLUE, 1.1, "-"), 5: (BLUE, 1.1, "-"), 10: (BLUE, 1.1, "-"), 20: (ORANGE, 2.0, "-"),
            60: (AQUA, 2.0, "-"), 100: (TEXT, 2.0, "-"), 200: (TEXT, 1.6, (0, (5, 3))),
            112: (MUTED, 1.2, (0, (1, 2))), 224: (MUTED, 1.2, (0, (4, 2)))}


def gambar(a, judul, sub, garis=(), n=90):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    s = slice(len(a["Close"]) - n, None)
    o, h, l, c, v = (a[k][s] for k in ("Open", "High", "Low", "Close", "Volume"))
    tgl, vs = a["tgl"][s], a["vs20"][s]
    m = len(c)
    fig = plt.figure(figsize=(11, 6.4), dpi=110, facecolor=SURFACE)
    ax = fig.add_axes([0.08, 0.30, 0.76, 0.56], facecolor=SURFACE)
    axv = fig.add_axes([0.08, 0.09, 0.76, 0.17], facecolor=SURFACE, sharex=ax)
    for i in range(m):
        ax.vlines(i, l[i], h[i], color=MUTED, lw=0.9, zorder=2)
        bawah, atas = sorted((o[i], c[i]))
        ax.add_patch(Rectangle((i - 0.32, bawah), 0.64, max(atas - bawah, (h[i] - l[i]) * 0.02 or 0.01),
                               facecolor=SURFACE if c[i] >= o[i] else MUTED, edgecolor=MUTED, lw=0.9, zorder=3))
    label = []
    for p, (col, lw, ls) in MA_STYLE.items():
        y = a["ma"][p][s]
        if np.all(np.isnan(y)):
            continue
        ax.plot(range(m), y, color=col, lw=lw, ls=ls, zorder=4)
        if p not in (3, 5) and not np.isnan(y[-1]):
            label.append((y[-1], "MA3/5/10" if p == 10 else f"MA{p}", col, ls))
    for y, teks, col in garis:
        ax.axhline(y, color=col, lw=1.1, ls=(0, (2, 2)), zorder=1)
        label.append((y, teks, col, (0, (2, 2))))
    lo_, hi_ = np.nanmin(l), np.nanmax(h)
    vis = [y for y, *_ in label if lo_ * 0.7 <= y <= hi_ * 1.5]
    lo_, hi_ = min([lo_] + vis), max([hi_] + vis)
    pad = (hi_ - lo_) * 0.06
    ax.set_ylim(lo_ - pad, hi_ + pad)
    ax.set_xlim(-1, m + 0.5)
    label = sorted(x for x in label if lo_ - pad <= x[0] <= hi_ + pad)
    jarak = (hi_ - lo_ + 2 * pad) * 0.045
    prev = None
    for y, teks, col, ls in label:
        yy = y if prev is None or y - prev >= jarak else prev + jarak
        prev = yy
        ax.annotate(f"{teks}  {rp(y)}", xy=(m - 1, yy), xytext=(m + 0.8, yy), textcoords="data", va="center",
                    fontsize=8.5, color=TEXT, annotation_clip=False)
        ax.plot([m + 0.15, m + 0.65], [yy, yy], color=col, lw=2.2, clip_on=False, ls=ls)
    rasio = np.where(vs > 0, v / np.where(vs > 0, vs, 1), 0)
    axv.bar(range(m), v, width=0.64, color=[TEXT2 if r >= 3 else "#cfcdc6" for r in rasio], zorder=2)
    axv.set_ylim(0, (np.nanmax(v) or 1) * 1.15)
    axv.set_yticks([])
    axv.text(0.0, 1.04, "Volume (batang gelap = di atas 3x rata-rata 20 hari)", transform=axv.transAxes, fontsize=8, color=TEXT2)
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
    axv.set_xticklabels([f"{d[8:]}/{d[5:7]}" for d in tgl][::step])
    fig.text(0.08, 0.945, judul, fontsize=14, fontweight="bold", color=TEXT)
    fig.text(0.08, 0.905, sub, fontsize=9, color=TEXT2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    return buf.getvalue()


def chart(t, a):
    st = lengkapi(a, status(a))
    en = st.get("masuk") or st.get("pantul") or (st["jalan"][1] if "jalan" in st else None)
    garis = (([(en["target"], "target", AQUA)] if en["target"] else []) + [(en["stop"], "stop", RED)]) if en else []
    cap = caption(t, st)
    sub = re.sub(r"[\U0001F000-\U0001FFFF\u2600-\u27BF]\ufe0f?\s?", "", cap.split(" · ", 1)[1] if " · " in cap else cap)
    png = gambar(a, f"{t} · Rp {rp(st['close'])} · {tanggal(st['tgl'])}", sub, garis)
    return png, cap


# ============================================================
# DATA & TELEGRAM
# ============================================================
def unduh(tickers, period="2y"):
    import screener

    return screener.download_daily([t + ".JK" for t in tickers], period=period, batch_size=25, pause=1.0)


def muat_histori(path, tickers=None):
    data = pd.read_csv(path)
    if tickers:
        data = data[data.Ticker.isin(tickers)]
    return {t: df.sort_values("Date").set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]
            for t, df in data.groupby("Ticker")}


def api(method, data=None, files=None, timeout=60):
    import requests

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    for _ in range(4):
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files, timeout=timeout)
        if r.status_code == 429:
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5) + 1)
            continue
        if not r.ok:
            raise RuntimeError(f"Telegram {method} gagal {r.status_code}: {r.text[:200]}")
        return r.json()
    raise RuntimeError(f"Telegram {method} gagal: rate limit")


def kirim(daily, dry=None, paksa=False):
    hari_ini = datetime.now(WIB).strftime("%Y-%m-%d")
    semua, tgl_data = {}, max(pd.to_datetime(df.index[-1]).strftime("%Y-%m-%d") for df in daily.values())
    for t, df in daily.items():
        if len(df) < 260:
            continue
        a = siapkan(df)
        if a["tgl"][-1] != tgl_data:
            continue
        semua[t] = lengkapi(a, status(a))
    if tgl_data != hari_ini and not paksa:
        print(f"Data terakhir {tgl_data}, bukan hari ini ({hari_ini}) -- libur bursa, tidak kirim.")
        return
    jam = "Siang" if datetime.now(WIB).hour < 15 else "Sore"
    teks = ringkasan(semua, jam)
    print(teks)
    if dry:
        os.makedirs(dry, exist_ok=True)
        open(os.path.join(dry, "ringkasan.txt"), "w").write(teks)
        return
    api("sendMessage", {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": teks})


def daftar_emiten():
    kode = set(config.SAHAM_IHSG_SEED)
    try:
        with open(config.EMITEN_JKT_CACHE_FILE) as f:
            kode |= set(json.load(f).get("codes", []))
    except (OSError, ValueError):
        pass
    return kode


def kode_dari(teks):
    """Satu kata 4 huruf ('baik') = kode saham. Dalam kalimat, hanya kata HURUF BESAR yang ada di daftar emiten."""
    kata = re.findall(r"(?<![A-Za-z])[A-Za-z]{4}(?![A-Za-z])", teks)
    if len(teks.split()) == 1 and len(kata) == 1:
        return [kata[0].upper()]
    emiten = daftar_emiten()
    return [k for k in kata if k.isupper() and k in emiten][:config.TG_MAKS_CHART]


def balas():
    chat = str(os.environ["TELEGRAM_CHAT_ID"])
    upd = api("getUpdates", {"timeout": 0}).get("result", [])
    if not upd:
        print("Tidak ada pesan baru.")
        return
    permintaan = []
    for u in upd:
        msg = u.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != chat:
            continue
        teks = (msg.get("text") or "").strip()
        if teks.lower() in ("/start", "/help", "help", "bantuan"):
            api("sendMessage", {"chat_id": chat, "text": "Ketik kode saham untuk chart, contoh: BAIK\n"
                                                         "Ringkasan otomatis jam 12:00 & 18:00 WIB."})
            continue
        permintaan += kode_dari(teks)
    api("getUpdates", {"offset": upd[-1]["update_id"] + 1, "timeout": 0})  # tandai sudah dibaca
    permintaan = list(dict.fromkeys(permintaan))
    if not permintaan:
        return
    daily = unduh(permintaan)
    for t in permintaan:
        df = daily.get(t)
        if df is None or len(df) < 230:
            api("sendMessage", {"chat_id": chat, "text": f"{t} tidak ditemukan / datanya kurang."})
            continue
        png, cap = chart(t, siapkan(df))
        api("sendPhoto", {"chat_id": chat, "caption": cap}, files={"photo": (f"{t}.png", png, "image/png")})


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = args[0] if args else "kirim"
    dry = args[args.index("--dry-run") + 1] if "--dry-run" in args else None
    histori = args[args.index("--histori") + 1] if "--histori" in args else None
    if mode == "kirim":
        if histori:
            daily = muat_histori(histori)
        else:
            import run_screener

            daily = unduh([t.replace(".JK", "") for t in run_screener.get_all_tickers()])
        kirim(daily, dry=dry, paksa=bool(histori))
    elif mode == "balas":
        balas()
    elif mode == "chart":
        kode = [k.upper() for k in args[1:] if not k.startswith("--") and k not in (dry, histori)]
        daily = muat_histori(histori, kode) if histori else unduh(kode)
        os.makedirs(dry or ".", exist_ok=True)
        for t in kode:
            png, cap = chart(t, siapkan(daily[t]))
            open(os.path.join(dry or ".", f"{t}.png"), "wb").write(png)
            print(cap)
