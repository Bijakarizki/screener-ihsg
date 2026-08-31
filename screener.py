"""
Logic screening saham -- porting 1:1 dari notebook screener_v2_updated.ipynb
Setup 1: Base / Re-Akumulasi
Setup 2: Bounce SMA Besar
Setup 3: Downtrend + Volume Signifikan
Setup 4: Post-IPO 4H (Darvas Box vs MA112/224/448 -- untuk saham yang
         belum punya histori panjang untuk MA60/100/200 klasik)

Perbedaan vs notebook:
- Tidak ada bagian Intraday 1 menit (sengaja dihilangkan, sesuai keputusan).
- Setiap hasil disimpan juga candle OHLCV (60 bar terakhir) untuk dipakai chart.
- Ditambah flag `is_new` per ticker per setup, dibanding hasil run sebelumnya.
- Download pakai session `curl_cffi` (impersonate browser Chrome) + retry & backoff,
  supaya tahan terhadap rate-limit Yahoo Finance yang sering terjadi di server
  datacenter seperti GitHub Actions (lihat catatan di run_screener.py).
- Daftar ticker tetap statis (config.SAHAM_IHSG_SEED). Label "Post-IPO age"
  diestimasi dari tanggal bar paling awal di histori harga yang sudah
  didownload (lihat listing_age.py), TANPA fetch ke sumber eksternal lain --
  endpoint publik idx.co.id ternyata diblokir Cloudflare/WAF untuk request
  dari IP datacenter seperti GitHub Actions, jadi pendekatan itu ditinggalkan.
"""

import random
import warnings
import time
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

import config

warnings.filterwarnings("ignore")

try:
    from curl_cffi import requests as curl_requests

    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False


def make_session():
    """
    Session yang menyamar sebagai browser Chrome asli (TLS fingerprint level),
    supaya tidak mudah dikenali & di-rate-limit sebagai bot oleh Yahoo Finance.
    Fallback ke session requests biasa kalau curl_cffi tidak terpasang.
    """
    if HAS_CURL_CFFI:
        return curl_requests.Session(impersonate="chrome")
    return None


# ============================================================
# DOWNLOAD DATA
# ============================================================
def download_daily(
    tickers,
    lookback=250,
    batch_size=25,
    pause=3.0,
    max_retries=3,
    progress_cb=None,
    period=None,
):
    """
    Download OHLCV daily untuk semua ticker, hitung semua SMA (termasuk
    MA112/224/448 untuk Setup 4 post-IPO).

    Strategi anti-rate-limit:
    - batch kecil (default 25 ticker/batch, bukan 80) supaya tiap request
      ke Yahoo lebih ringan dan jarang dianggap mencurigakan.
    - session curl_cffi impersonate Chrome (TLS fingerprint browser asli).
    - retry dengan exponential backoff + jitter kalau satu batch gagal total
      (indikasi kena rate-limit 429 / blocked sesaat).
    - delay antar batch (default 3 detik) supaya tidak membombardir Yahoo.

    `period`: rentang download yfinance (default config.YF_PERIOD = "5y").
    Diperpanjang dari "2y" semula supaya MA448 (Setup 4) bisa terbentuk.

    Return dict {ticker_tanpa_jk: DataFrame}.
    """
    data = {}
    period = period or config.YF_PERIOD
    all_periods = (
        config.SMA_KECIL
        + config.SMA_PENGGIRING
        + config.SMA_BESAR
        + config.SMA_POST_IPO
    )
    session = make_session()

    total = len(tickers)
    for i in range(0, total, batch_size):
        batch = tickers[i : i + batch_size]
        if progress_cb:
            progress_cb(i, total, batch)

        attempt = 0
        raw = None
        while attempt < max_retries:
            try:
                raw = yf.download(
                    batch,
                    period=period,
                    interval="1d",
                    progress=False,
                    auto_adjust=True,
                    group_by="ticker",
                    threads=True,
                    session=session,
                )
                # Kalau hasilnya kosong total, anggap kena rate-limit -> retry
                if raw is None or raw.empty:
                    raise ValueError("Hasil download kosong (kemungkinan rate-limited)")
                break
            except Exception as e:
                attempt += 1
                wait = pause * (2 ** attempt) + random.uniform(0, 2)
                print(f"   batch {i} gagal (percobaan {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    print(f"   menunggu {wait:.1f}s sebelum retry ...")
                    time.sleep(wait)
                    # session baru untuk percobaan berikutnya (kadang cookie/crumb basi)
                    session = make_session()
                else:
                    print(f"   batch {i} dilewati setelah {max_retries} percobaan.")

        if raw is None or raw.empty:
            time.sleep(pause)
            continue

        for tkr in batch:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    if tkr not in raw.columns.get_level_values(0):
                        continue
                    df = raw[tkr].copy()
                else:
                    # single ticker fallback
                    df = raw.copy()

                df = df.dropna(how="all")
                if df.empty or len(df) < 30:
                    continue

                df = df.rename(columns=str.title)
                df.index = pd.to_datetime(df.index)
                df.sort_index(inplace=True)

                for p in all_periods:
                    df[f"SMA{p}"] = df["Close"].rolling(p).mean()
                df["VolSMA20"] = df["Volume"].rolling(20).mean()

                clean_tkr = tkr.replace(".JK", "")
                data[clean_tkr] = df
            except Exception:
                continue

        time.sleep(pause + random.uniform(0, 1.5))

    return data


# ============================================================
# HELPER FUNCTIONS (porting 1:1 dari notebook Cell 3)
# ============================================================
def latest(df):
    return df.dropna(subset=["Close"]).iloc[-1]


def pct_gap(price, sma_val):
    if pd.isna(sma_val) or sma_val == 0:
        return np.nan
    return (price - sma_val) / sma_val


def sma_kecil_mepet(row):
    vals_kecil = []
    for p in config.SMA_KECIL:
        v = row.get(f"SMA{p}", np.nan)
        if np.isnan(v):
            return False
        vals_kecil.append(v)

    sma20 = row.get("SMA20", np.nan)
    if np.isnan(sma20):
        return False

    close = row["Close"]
    mid = np.mean(vals_kecil)

    spread = (max(vals_kecil) - min(vals_kecil)) / mid if mid != 0 else np.nan
    if np.isnan(spread) or spread > config.SMA_CLUSTER_TOLERANCE:
        return False

    if close < min(vals_kecil):
        return False

    tol_sma20 = config.SMA20_TOL_MAHAL if close >= 500 else config.SMA20_TOL_MURAH
    gap_sma20 = abs(sma20 - mid) / mid if mid != 0 else np.nan
    if np.isnan(gap_sma20) or gap_sma20 > tol_sma20:
        return False

    return True


def hitung_spread_sma20_cluster(row):
    """
    Hitung spread (desimal, misal 0.12 = 12%) antara SMA3/5/10/20 -- dipakai untuk
    filter "SMA20 Ketat" di web, yang toleransinya diatur live lewat slider
    (SMA20_KETAT_TOLERANCE di config.py cuma default posisi slider).
    Return None kalau salah satu SMA belum tersedia (data kurang panjang).
    """
    vals = []
    for p in [3, 5, 10, 20]:
        v = row.get(f"SMA{p}", np.nan)
        if np.isnan(v):
            return None
        vals.append(v)

    mid = np.mean(vals)
    if mid == 0:
        return None
    return (max(vals) - min(vals)) / mid


def find_nearest_sma_besar_below(row, price):
    candidates = []
    for p in config.SMA_BESAR:
        val = row.get(f"SMA{p}", np.nan)
        if not np.isnan(val) and val < price:
            candidates.append((p, val))
    if not candidates:
        return None, None
    return max(candidates, key=lambda x: x[1])


def find_nearest_sma_besar_above(row, price):
    candidates = []
    for p in config.SMA_BESAR:
        val = row.get(f"SMA{p}", np.nan)
        if not np.isnan(val) and val > price:
            candidates.append((p, val))
    if not candidates:
        return None, None
    return min(candidates, key=lambda x: x[1])


def hitung_darvas_box(df, lookback_days, confirmation_days=None):
    """
    Hitung Darvas Box dari `lookback_days` hari terakhir di `df`, dengan
    validasi dua-periode ala Darvas klasik:

    - box_top/box_bottom dihitung dari SELURUH window `lookback_days` hari.
    - Box dianggap VALID kalau extremes itu (box_top/box_bottom) sudah
      terbentuk di bagian box period SEBELUM `confirmation_days` hari
      terakhir -- artinya `confirmation_days` hari terakhir tidak membuat
      high/low baru dibanding sisa periode sebelumnya. Ini menandakan harga
      sudah "tenang"/terkurung beberapa hari terakhir, bukan masih dalam
      proses membuat rekor tinggi/rendah baru (masih trending kuat).

    Return dict {"box_top": float, "box_bottom": float, "is_valid": bool}
    atau None kalau data kurang dari lookback_days.
    """
    confirmation_days = confirmation_days or config.DARVAS_CONFIRMATION_DAYS
    if df is None or len(df) < lookback_days or confirmation_days >= lookback_days:
        return None

    window = df.tail(lookback_days)
    box_top = float(window["High"].max())
    box_bottom = float(window["Low"].min())

    if box_top <= box_bottom:
        return None

    # Bagian "lama" (box period dikurangi confirmation period di ujung) --
    # extremes box HARUS berasal dari sini.
    older_part = window.iloc[:-confirmation_days]
    recent_part = window.iloc[-confirmation_days:]

    older_top = float(older_part["High"].max())
    older_bottom = float(older_part["Low"].min())

    # Valid kalau bagian recent tidak melampaui extremes yang sudah terbentuk
    # di bagian older -- dengan kata lain, box_top/box_bottom keseluruhan
    # window SAMA DENGAN box_top/box_bottom dari bagian older saja (recent
    # part tidak menambah rekor baru), DAN Close di recent part tetap di
    # dalam rentang box.
    no_new_extreme = (older_top >= box_top - 1e-9) and (older_bottom <= box_bottom + 1e-9)
    recent_closes_inside = bool(
        ((recent_part["Close"] >= box_bottom) & (recent_part["Close"] <= box_top)).all()
    )
    is_valid = no_new_extreme and recent_closes_inside

    return {"box_top": box_top, "box_bottom": box_bottom, "is_valid": is_valid}


def cek_box_dekat_ma_post_ipo(row, box, tolerance):
    """
    Cek apakah salah satu sisi Darvas Box (box_top atau box_bottom) berhimpit
    (dalam `tolerance` persen) dengan salah satu MA post-IPO
    (config.SMA_POST_IPO = [112, 224, 448]).

    Return dict berisi info MA/sisi box yang PALING dekat (jarak persen
    terkecil), atau None kalau tidak ada satu pun MA yang dalam toleransi
    ATAU MA-nya belum terbentuk (data belum cukup panjang).

    Dict yang direturn:
    {
        "ma_period": int,       # 112/224/448
        "ma_val": float,
        "role": "support"|"resistance",   # support = box_bottom yg dekat, resistance = box_top
        "gap_pct": float,       # jarak persen (positif)
        "box_top": float,
        "box_bottom": float,
    }
    """
    best = None
    for p in config.SMA_POST_IPO:
        ma_val = row.get(f"SMA{p}", np.nan)
        if np.isnan(ma_val) or ma_val <= 0:
            continue

        gap_bottom = abs(box["box_bottom"] - ma_val) / ma_val
        gap_top = abs(box["box_top"] - ma_val) / ma_val

        if gap_bottom <= gap_top:
            role, gap = "support", gap_bottom
        else:
            role, gap = "resistance", gap_top

        if gap > tolerance:
            continue

        if best is None or gap < best["gap_pct"]:
            best = {
                "ma_period": p,
                "ma_val": ma_val,
                "role": role,
                "gap_pct": gap,
                "box_top": box["box_top"],
                "box_bottom": box["box_bottom"],
            }

    return best


# ============================================================
# SETUP 1 -- Base / Re-Akumulasi
# ============================================================
def screen_setup1(daily_data):
    results = []
    for tkr, df in daily_data.items():
        if len(df) < 60:
            continue
        row = latest(df)
        close = row["Close"]

        if not sma_kecil_mepet(row):
            continue

        tp_period, tp_val = find_nearest_sma_besar_above(row, close)
        if tp_period is None:
            continue

        sma20 = row.get("SMA20", np.nan)
        if np.isnan(sma20) or sma20 <= 0:
            continue
        gap_sma20_to_tp = (tp_val - sma20) / sma20
        if gap_sma20_to_tp < config.SMA20_TO_SMABT_MIN:
            continue

        tp_pct = pct_gap(tp_val, close)

        sma3 = row.get("SMA3", np.nan)
        sma5 = row.get("SMA5", np.nan)
        sma10 = row.get("SMA10", np.nan)
        vals_kecil = [v for v in [sma3, sma5, sma10] if not np.isnan(v)]
        mid = np.mean(vals_kecil) if vals_kecil else np.nan
        spread_pct = (max(vals_kecil) - min(vals_kecil)) / mid * 100 if vals_kecil and mid else np.nan
        gap_sma20_pct = abs((sma20 - mid) / mid) * 100 if vals_kecil and mid and not np.isnan(sma20) else np.nan

        all_tp = []
        for p in config.SMA_BESAR:
            v = row.get(f"SMA{p}", np.nan)
            if not np.isnan(v) and v > close:
                all_tp.append(f"SMA{p}={v:.0f} (+{pct_gap(v, close) * 100:.1f}%)")

        spread4 = hitung_spread_sma20_cluster(row)

        results.append(
            {
                "Ticker": tkr,
                "Close": round(close, 0),
                "SMA3": round(sma3, 0) if not np.isnan(sma3) else None,
                "SMA5": round(sma5, 0) if not np.isnan(sma5) else None,
                "SMA10": round(sma10, 0) if not np.isnan(sma10) else None,
                "SMA20": round(sma20, 0) if not np.isnan(sma20) else None,
                "Spread_3_5_10_pct": round(spread_pct, 2) if not np.isnan(spread_pct) else None,
                "Gap_SMA20_cluster_pct": round(gap_sma20_pct, 2) if not np.isnan(gap_sma20_pct) else None,
                "Gap_SMA20_ke_TP_pct": round(gap_sma20_to_tp * 100, 2),
                "TP_Target": f"SMA{tp_period}",
                "TP_Period": tp_period,
                "TP_Val": round(tp_val, 0),
                "TP_Pot_pct": round(tp_pct * 100, 2),
                "Semua_TP": " | ".join(all_tp) if all_tp else "-",
                "SMA20_Cluster4_Spread_pct": (
                    round(spread4 * 100, 2) if spread4 is not None else None
                ),
                "Setup": "1",
                "Setup_Label": "Base / Re-Akumulasi",
            }
        )
    return results


# ============================================================
# SETUP 2 -- Bounce SMA Besar
# ============================================================
def screen_setup2(daily_data):
    results = []
    for tkr, df in daily_data.items():
        if len(df) < 210:
            continue
        row = latest(df)
        close = row["Close"]

        sma_vals = {}
        for p in config.SMA_BESAR:
            v = row.get(f"SMA{p}", np.nan)
            if not np.isnan(v):
                sma_vals[p] = v

        if len(sma_vals) < 2:
            continue

        below = {p: v for p, v in sma_vals.items() if v < close}
        if not below:
            continue

        support_p = max(below, key=lambda p: below[p])
        support_val = below[support_p]
        gap_support = pct_gap(close, support_val)

        if gap_support > config.APPROACHING_PCT:
            continue

        above = {p: v for p, v in sma_vals.items() if v > close}
        if not above:
            continue

        tp_p = min(above, key=lambda p: above[p])
        tp_val = above[tp_p]
        tp_pct = pct_gap(tp_val, close)

        all_sma_info = []
        for p in config.SMA_BESAR:
            v = sma_vals.get(p, np.nan)
            if not np.isnan(v):
                tag = "TP" if v > close else ("Support" if v < close else "=")
                all_sma_info.append(f"SMA{p}={v:.0f} ({tag})")

        results.append(
            {
                "Ticker": tkr,
                "Close": round(close, 0),
                "Support_SMA": f"SMA{support_p}",
                "Support_Val": round(support_val, 0),
                "Gap_Support_pct": round(gap_support * 100, 2),
                "TP_SMA": f"SMA{tp_p}",
                "TP_Val": round(tp_val, 0),
                "TP_Pot_pct": round(tp_pct * 100, 2),
                "Semua_SMA_Besar": " | ".join(all_sma_info),
                "Setup": "2",
                "Setup_Label": "Bounce SMA Besar",
            }
        )
    return results


# ============================================================
# SETUP 3 -- Downtrend + Volume Signifikan
# ============================================================
def screen_setup3(daily_data):
    results = []
    for tkr, df in daily_data.items():
        if len(df) < 210:
            continue
        row = latest(df)
        close = row["Close"]

        all_sma_periods = config.SMA_KECIL + config.SMA_PENGGIRING + config.SMA_BESAR
        all_below = True
        for p in all_sma_periods:
            val = row.get(f"SMA{p}", np.nan)
            if np.isnan(val) or close >= val:
                all_below = False
                break
        if not all_below:
            continue

        vol = row.get("Volume", np.nan)
        vol_sma = row.get("VolSMA20", np.nan)
        if np.isnan(vol) or np.isnan(vol_sma) or vol_sma == 0:
            continue
        vol_ratio = vol / vol_sma
        if vol_ratio < config.VOL_MULTIPLIER:
            continue

        nearest_resist_p, nearest_resist_val = find_nearest_sma_besar_above(row, close)
        # TP potential pakai resistance terdekat di atas, biar sebanding dgn setup lain
        tp_pct = pct_gap(nearest_resist_val, close) * 100 if nearest_resist_val else None

        results.append(
            {
                "Ticker": tkr,
                "Close": round(close, 0),
                "Volume": int(vol),
                "VolSMA20": int(vol_sma),
                "Vol_Ratio": round(vol_ratio, 2),
                "SMA3": round(row.get("SMA3", np.nan), 0) if not np.isnan(row.get("SMA3", np.nan)) else None,
                "SMA5": round(row.get("SMA5", np.nan), 0) if not np.isnan(row.get("SMA5", np.nan)) else None,
                "SMA10": round(row.get("SMA10", np.nan), 0) if not np.isnan(row.get("SMA10", np.nan)) else None,
                "SMA20": round(row.get("SMA20", np.nan), 0) if not np.isnan(row.get("SMA20", np.nan)) else None,
                "Resist_Terdekat": f"SMA{nearest_resist_p}" if nearest_resist_p else "-",
                "Resist_Val": round(nearest_resist_val, 0) if nearest_resist_val else None,
                "TP_Pot_pct": round(tp_pct, 2) if tp_pct is not None else None,
                "Setup": "3",
                "Setup_Label": "Downtrend + Volume Signifikan",
            }
        )
    return results


# ============================================================
# SETUP 4 -- POST-IPO 4H (Darvas Box vs MA112/224/448)
# ============================================================
def screen_setup4(daily_data, lookback_days=None, tolerance=None, confirmation_days=None):
    """
    Cari saham post-IPO yang membentuk Darvas Box (konsolidasi harga N hari
    terakhir, belum breakout) dengan salah satu sisi box (box_top ATAU
    box_bottom) berhimpit dengan salah satu MA post-IPO (112/224/448) --
    MA itu jadi support (kalau box_bottom yang dekat) atau resistance (kalau
    box_top yang dekat) dari box tersebut.

    `lookback_days` / `tolerance` / `confirmation_days`: parameter Darvas Box,
    default dari config (DARVAS_BOX_LOOKBACK_DAYS / DARVAS_MA_TOLERANCE /
    DARVAS_CONFIRMATION_DAYS) -- juga dipakai sebagai slider yang bisa digeser
    live di dashboard (lihat app.py), makanya fungsi ini menerima override
    eksplisit, bukan cuma baca config langsung.

    Filter umur listing dilakukan berdasarkan estimasi dari histori harga itu
    sendiri (lihat listing_age.py) -- ticker yang histori harganya sudah
    sepanjang rentang download penuh (config.YF_PERIOD) dianggap "established"
    dan di-skip dari Setup 4 (cukup discreen lewat Setup 1/2/3 biasa),
    karena untuk saham lama kita tidak tahu tanggal IPO aslinya.
    """
    import listing_age

    lookback_days = lookback_days or config.DARVAS_BOX_LOOKBACK_DAYS
    tolerance = tolerance if tolerance is not None else config.DARVAS_MA_TOLERANCE
    confirmation_days = confirmation_days or config.DARVAS_CONFIRMATION_DAYS

    results = []
    min_bars = max(config.SMA_POST_IPO) + 5

    for tkr, df in daily_data.items():
        if len(df) < min_bars:
            continue

        umur = listing_age.hitung_umur_listing(df)
        if umur is not None and umur["days"] > config.POST_IPO_MAX_AGE_DAYS:
            continue

        box = hitung_darvas_box(df, lookback_days, confirmation_days)
        if box is None or not box["is_valid"]:
            continue

        row = latest(df)
        close = row["Close"]

        match = cek_box_dekat_ma_post_ipo(row, box, tolerance)
        if match is None:
            continue

        box_range_pct = pct_gap(box["box_top"], box["box_bottom"])

        if match["role"] == "support":
            # MA jadi lantai box -- target breakout ke atas box_top.
            tp_val = box["box_top"]
            tp_target_label = "Box_Top (breakout)"
        else:
            # MA jadi atap box (resistance) -- target ke MA post-IPO
            # berikutnya yang lebih besar (kalau ada); kalau match["ma_period"]
            # sudah yang terbesar (448), proyeksikan target selebar box_range
            # di atas box_top (breakout measuring move ala Darvas).
            bigger_mas = [p for p in config.SMA_POST_IPO if p > match["ma_period"]]
            if bigger_mas:
                next_p = min(bigger_mas)
                next_val = row.get(f"SMA{next_p}", np.nan)
                if not np.isnan(next_val):
                    tp_val = next_val
                    tp_target_label = f"SMA{next_p}"
                else:
                    tp_val = box["box_top"] * (1 + box_range_pct)
                    tp_target_label = "Proyeksi box"
            else:
                tp_val = box["box_top"] * (1 + box_range_pct)
                tp_target_label = "Proyeksi box"

        tp_pct = pct_gap(tp_val, close)

        results.append(
            {
                "Ticker": tkr,
                "Close": round(close, 0),
                "Box_Top": round(box["box_top"], 0),
                "Box_Bottom": round(box["box_bottom"], 0),
                "Box_Range_pct": round(box_range_pct * 100, 2),
                "MA_Period": match["ma_period"],
                "MA_Val": round(match["ma_val"], 0),
                "MA_Role": match["role"],
                "Gap_Box_MA_pct": round(match["gap_pct"] * 100, 2),
                "TP_Target": tp_target_label,
                "TP_Val": round(tp_val, 0),
                "TP_Pot_pct": round(tp_pct * 100, 2),
                "Setup": "4",
                "Setup_Label": "Post-IPO 4H",
            }
        )
    return results


# ============================================================
# CANDLE DATA UNTUK CHART (60 bar terakhir + SMA + volume)
# ============================================================
def extract_chart_data(df, n=90):
    """Ambil n bar terakhir, return list of dict siap dipakai chart JS."""
    tail = df.tail(n).copy()
    tail = tail.reset_index()
    date_col = tail.columns[0]
    out = []
    sma_cols = [
        f"SMA{p}"
        for p in (
            config.SMA_KECIL
            + config.SMA_PENGGIRING
            + config.SMA_BESAR
            + config.SMA_POST_IPO
        )
    ]
    for _, r in tail.iterrows():
        rec = {
            "date": pd.Timestamp(r[date_col]).strftime("%Y-%m-%d"),
            "open": round(float(r["Open"]), 2) if not pd.isna(r["Open"]) else None,
            "high": round(float(r["High"]), 2) if not pd.isna(r["High"]) else None,
            "low": round(float(r["Low"]), 2) if not pd.isna(r["Low"]) else None,
            "close": round(float(r["Close"]), 2) if not pd.isna(r["Close"]) else None,
            "volume": int(r["Volume"]) if not pd.isna(r["Volume"]) else 0,
            "vol_sma20": round(float(r["VolSMA20"]), 2) if not pd.isna(r.get("VolSMA20", np.nan)) else None,
        }
        for c in sma_cols:
            v = r.get(c, np.nan)
            rec[c] = round(float(v), 2) if not pd.isna(v) else None
        out.append(rec)
    return out
