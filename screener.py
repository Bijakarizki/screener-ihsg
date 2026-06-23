"""
Logic screening saham -- porting 1:1 dari notebook screener_v2_updated.ipynb
Setup 1: Base / Re-Akumulasi
Setup 2: Bounce SMA Besar
Setup 3: Downtrend + Volume Signifikan

Perbedaan vs notebook:
- Tidak ada bagian Intraday 1 menit (sengaja dihilangkan, sesuai keputusan).
- Setiap hasil disimpan juga candle OHLCV (60 bar terakhir) untuk dipakai chart.
- Ditambah flag `is_new` per ticker per setup, dibanding hasil run sebelumnya.
"""

import warnings
import time
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

import config

warnings.filterwarnings("ignore")


# ============================================================
# DOWNLOAD DATA
# ============================================================
def download_daily(tickers, lookback=250, batch_size=80, pause=1.0, progress_cb=None):
    """
    Download OHLCV daily untuk semua ticker, hitung semua SMA.
    Pakai yf.download batch (lebih cepat & lebih jarang di-rate-limit
    dibanding loop satu-satu seperti di notebook asli).
    Return dict {ticker_tanpa_jk: DataFrame}.
    """
    data = {}
    all_periods = config.SMA_KECIL + config.SMA_PENGGIRING + config.SMA_BESAR

    total = len(tickers)
    for i in range(0, total, batch_size):
        batch = tickers[i : i + batch_size]
        if progress_cb:
            progress_cb(i, total, batch)

        try:
            raw = yf.download(
                batch,
                period="2y",
                interval="1d",
                progress=False,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
            )
        except Exception as e:
            print(f"   batch error {i}: {e}")
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

        time.sleep(pause)

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
                "TP_Val": round(tp_val, 0),
                "TP_Pot_pct": round(tp_pct * 100, 2),
                "Semua_TP": " | ".join(all_tp) if all_tp else "-",
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
        if vol_ratio < 1.5:
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
# CANDLE DATA UNTUK CHART (60 bar terakhir + SMA + volume)
# ============================================================
def extract_chart_data(df, n=90):
    """Ambil n bar terakhir, return list of dict siap dipakai chart JS."""
    tail = df.tail(n).copy()
    tail = tail.reset_index()
    date_col = tail.columns[0]
    out = []
    sma_cols = [f"SMA{p}" for p in (config.SMA_KECIL + config.SMA_PENGGIRING + config.SMA_BESAR)]
    for _, r in tail.iterrows():
        rec = {
            "date": pd.Timestamp(r[date_col]).strftime("%Y-%m-%d"),
            "open": round(float(r["Open"]), 2) if not pd.isna(r["Open"]) else None,
            "high": round(float(r["High"]), 2) if not pd.isna(r["High"]) else None,
            "low": round(float(r["Low"]), 2) if not pd.isna(r["Low"]) else None,
            "close": round(float(r["Close"]), 2) if not pd.isna(r["Close"]) else None,
            "volume": int(r["Volume"]) if not pd.isna(r["Volume"]) else 0,
        }
        for c in sma_cols:
            v = r.get(c, np.nan)
            rec[c] = round(float(v), 2) if not pd.isna(v) else None
        out.append(rec)
    return out
