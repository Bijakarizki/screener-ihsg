"""
Unduh OHLCV harian mentah semua emiten BEI (sekali jalan, untuk analisa/backtest).
Hasil: data/analisa/histori_<period>.csv.gz (kolom: Ticker, Date, Open, High, Low, Close, Volume).
"""
import json
import os
import random
import sys
import time

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from screener import make_session  # noqa: E402

PERIOD = sys.argv[1] if len(sys.argv) > 1 else "3y"
OUT_DIR = os.path.join(config.DATA_DIR, "analisa")


def main():
    with open(config.EMITEN_JKT_CACHE_FILE) as f:
        codes = set(json.load(f)["codes"])
    codes |= set(config.SAHAM_IHSG_SEED)
    tickers = [c + ".JK" for c in sorted(codes)]
    print(f"{len(tickers)} ticker, period {PERIOD}", flush=True)

    frames = []
    session = make_session()
    for i in range(0, len(tickers), 25):
        batch = tickers[i : i + 25]
        raw = None
        for attempt in range(1, 4):
            try:
                raw = yf.download(batch, period=PERIOD, interval="1d", progress=False, auto_adjust=True,
                                  group_by="ticker", threads=True, session=session)
                if raw is None or raw.empty:
                    raise ValueError("kosong")
                break
            except Exception as e:
                print(f"  batch {i} gagal ({attempt}/3): {e}", flush=True)
                time.sleep(3 * 2 ** attempt + random.uniform(0, 2))
                session = make_session()
                raw = None
        if raw is not None:
            for tkr in batch:
                if tkr not in raw.columns.get_level_values(0):
                    continue
                df = raw[tkr].rename(columns=str.title).dropna(subset=["Open", "High", "Low", "Close"])
                if len(df) < 30:
                    continue
                df = df[["Open", "High", "Low", "Close", "Volume"]].reset_index()
                df.insert(0, "Ticker", tkr.replace(".JK", ""))
                frames.append(df)
        print(f"  {min(i + 25, len(tickers))}/{len(tickers)}", flush=True)
        time.sleep(3 + random.uniform(0, 1.5))

    out = pd.concat(frames, ignore_index=True)
    out["Date"] = pd.to_datetime(out["Date"]).dt.strftime("%Y-%m-%d")
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"histori_{PERIOD}.csv.gz")
    out.to_csv(path, index=False, float_format="%.4f", compression="gzip")
    print(f"Tersimpan {path}: {out['Ticker'].nunique()} ticker, {len(out)} baris", flush=True)


if __name__ == "__main__":
    main()
