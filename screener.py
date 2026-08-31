"""
Logic screening saham -- porting 1:1 dari notebook screener_v2_updated.ipynb
Setup 1: Base / Re-Akumulasi
Setup 2: Bounce SMA Besar
Setup 3: Downtrend + Volume Signifikan
Setup 4: Post-IPO 4H (sama logic Setup 1, MA112/224/448 -- untuk saham yang
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
        + config.SMA_KECIL_POST_IPO
        + config.SMA_PENGGIRING_POST_IPO
        + config.SMA_BESAR_POST_IPO
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


def find_nearest_sma_above_periods(row, price, periods):
    """Versi generic find_nearest_sma_besar_above -- terima list period custom
    (dipakai Setup 4 dengan config.SMA_BESAR_POST_IPO)."""
    candidates = []
    for p in periods:
        val = row.get(f"SMA{p}", np.nan)
        if not np.isnan(val) and val > price:
            candidates.append((p, val))
    if not candidates:
        return None, None
    return min(candidates, key=lambda x: x[1])


def post_ipo_mepet(row):
    """
    Analog sma_kecil_mepet(), tapi untuk Setup 4 (post-IPO). Karena cuma ada
    SATU "SMA kecil" (MA112, bukan cluster 3/5/10), kriterianya:
    - Close harus >= MA112 (posisi di atas trigger, sama semangat Setup 1)
    - Gap MA112 <-> MA224 harus dalam toleransi (analog SMA20_TOL_MAHAL/MURAH)
    """
    p_kecil = config.SMA_KECIL_POST_IPO[0]
    p_penggiring = config.SMA_PENGGIRING_POST_IPO[0]

    sma_kecil = row.get(f"SMA{p_kecil}", np.nan)
    sma_penggiring = row.get(f"SMA{p_penggiring}", np.nan)
    if np.isnan(sma_kecil) or np.isnan(sma_penggiring):
        return False

    close = row["Close"]
    if close < sma_kecil:
        return False

    tol = config.POST_IPO_TOL_MAHAL if close >= 500 else config.POST_IPO_TOL_MURAH
    gap = abs(sma_penggiring - sma_kecil) / sma_kecil if sma_kecil != 0 else np.nan
    if np.isnan(gap) or gap > tol:
        return False

    return True


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
# SETUP 4 -- POST-IPO 4H (sama semangat Setup 1, MA112/224/448)
# ============================================================
def screen_setup4(daily_data):
    """
    Sama logic dengan Setup 1 (clustering + target profit di SMA besar),
    tapi pakai MA112 (kecil) / MA224 (penggiring) / MA448 (besar) supaya
    cocok untuk saham yang belum lama IPO dan belum punya cukup histori
    untuk MA60/100/200 klasik.

    Filter umur listing dilakukan berdasarkan estimasi dari histori harga itu
    sendiri (lihat listing_age.py) -- ticker yang histori harganya sudah
    sepanjang rentang download penuh (config.YF_PERIOD) dianggap "established"
    dan di-skip dari Setup 4 (cukup discreen lewat Setup 1/2/3 biasa),
    karena untuk saham lama kita tidak tahu tanggal IPO aslinya.
    """
    import listing_age

    results = []
    p_besar = config.SMA_BESAR_POST_IPO[0]

    for tkr, df in daily_data.items():
        min_bars = max(config.SMA_BESAR_POST_IPO) + 5
        if len(df) < min_bars:
            continue

        umur = listing_age.hitung_umur_listing(df)
        if umur is not None and umur["days"] > config.POST_IPO_MAX_AGE_DAYS:
            continue

        row = latest(df)
        close = row["Close"]

        if not post_ipo_mepet(row):
            continue

        tp_val_raw = row.get(f"SMA{p_besar}", np.nan)
        if np.isnan(tp_val_raw) or tp_val_raw <= close:
            continue
        tp_val = tp_val_raw

        sma_kecil = row.get(f"SMA{config.SMA_KECIL_POST_IPO[0]}", np.nan)
        sma_penggiring = row.get(f"SMA{config.SMA_PENGGIRING_POST_IPO[0]}", np.nan)

        gap_to_tp = (tp_val - sma_penggiring) / sma_penggiring if sma_penggiring else np.nan
        if np.isnan(gap_to_tp) or gap_to_tp < config.POST_IPO_TO_TP_MIN:
            continue

        tp_pct = pct_gap(tp_val, close)
        gap_pct = abs((sma_penggiring - sma_kecil) / sma_kecil) * 100 if sma_kecil else np.nan

        results.append(
            {
                "Ticker": tkr,
                "Close": round(close, 0),
                f"SMA{config.SMA_KECIL_POST_IPO[0]}": round(sma_kecil, 0) if not np.isnan(sma_kecil) else None,
                f"SMA{config.SMA_PENGGIRING_POST_IPO[0]}": round(sma_penggiring, 0) if not np.isnan(sma_penggiring) else None,
                f"SMA{p_besar}": round(tp_val, 0),
                "Gap_Cluster_pct": round(gap_pct, 2) if not np.isnan(gap_pct) else None,
                "Gap_ke_TP_pct": round(gap_to_tp * 100, 2),
                "TP_Target": f"SMA{p_besar}",
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
            + config.SMA_KECIL_POST_IPO
            + config.SMA_PENGGIRING_POST_IPO
            + config.SMA_BESAR_POST_IPO
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
