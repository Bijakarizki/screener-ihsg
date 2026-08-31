"""
Script utama -- dijalankan oleh GitHub Actions tiap hari setelah market close.
1. Download data semua ticker (histori 5 tahun -- lihat config.YF_PERIOD).
2. Jalankan Setup 1, 2, 3, 4 (Setup 4 = Post-IPO 4H, MA112/224/448).
3. Tempel label estimasi umur listing ("Post-IPO age") ke setiap hasil,
   dihitung dari histori harga itu sendiri (listing_age.py) -- bukan fetch
   eksternal (lihat catatan di listing_age.py kenapa idx.co.id ditinggalkan).
4. Gabungkan semua hasil, urutkan dari TP_Pot_pct terbesar -> terkecil.
5. Bandingkan dengan hasil run sebelumnya -> tandai is_new.
6. Simpan candle chart (90 bar) untuk tiap ticker yang lolos screening (biar ringan,
   tidak semua ticker disimpan candle-nya).
7. Simpan ke data/latest_result.json + arsip ke data/history/.
"""

import json
import os
import sys
from datetime import datetime

import config
import listing_age
import screener


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def progress_cb(i, total, batch):
    log(f"Downloading batch {i}-{min(i+len(batch), total)} / {total} ...")


def load_previous_tickers():
    """Ambil set ticker per setup dari hasil run sebelumnya, untuk deteksi 'penghuni baru'."""
    if not os.path.exists(config.LATEST_RESULT_FILE):
        return {"1": set(), "2": set(), "3": set(), "4": set()}
    try:
        with open(config.LATEST_RESULT_FILE, "r") as f:
            prev = json.load(f)
        sets = {"1": set(), "2": set(), "3": set(), "4": set()}
        for row in prev.get("results", []):
            sets.setdefault(row["Setup"], set()).add(row["Ticker"])
        return sets
    except Exception as e:
        log(f"Gagal load hasil sebelumnya: {e}")
        return {"1": set(), "2": set(), "3": set(), "4": set()}


def main():
    log("=== MULAI SCREENING ===")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.HISTORY_DIR, exist_ok=True)

    prev_tickers = load_previous_tickers()

    tickers_yf = config.TICKERS_YF
    log(f"Total ticker yang akan di-download: {len(tickers_yf)}")

    daily_data = screener.download_daily(
        tickers_yf,
        lookback=config.LOOKBACK_DAILY,
        batch_size=25,
        pause=3.0,
        max_retries=3,
        progress_cb=progress_cb,
        period=config.YF_PERIOD,
    )
    log(f"Berhasil download {len(daily_data)} / {len(tickers_yf)} ticker.")

    success_ratio = len(daily_data) / len(tickers_yf)
    if len(daily_data) == 0:
        log("FATAL: tidak ada data yang berhasil di-download (kemungkinan rate-limited Yahoo Finance). Berhenti.")
        sys.exit(1)
    elif success_ratio < 0.3:
        log(
            f"PERINGATAN: hanya {success_ratio*100:.0f}% ticker berhasil di-download "
            f"(kemungkinan rate-limit parsial dari Yahoo Finance). Hasil screening kali ini "
            f"mungkin tidak lengkap, tapi tetap akan disimpan."
        )

    log("Menjalankan Setup 1 (Base/Re-Akumulasi) ...")
    r1 = screener.screen_setup1(daily_data)
    log(f"  -> {len(r1)} kandidat")

    log("Menjalankan Setup 2 (Bounce SMA Besar) ...")
    r2 = screener.screen_setup2(daily_data)
    log(f"  -> {len(r2)} kandidat")

    log("Menjalankan Setup 3 (Downtrend + Volume) ...")
    r3 = screener.screen_setup3(daily_data)
    log(f"  -> {len(r3)} kandidat")

    log("Menjalankan Setup 4 (Post-IPO 4H) ...")
    r4 = screener.screen_setup4(daily_data)
    log(f"  -> {len(r4)} kandidat")

    all_results = r1 + r2 + r3 + r4

    # Tempel label estimasi umur listing ("Post-IPO age") ke SEMUA hasil,
    # semua setup -- dihitung dari histori harga masing-masing ticker.
    for row in all_results:
        df = daily_data.get(row["Ticker"])
        umur = listing_age.hitung_umur_listing(df)
        if umur:
            row["Listing_Date_Estimasi"] = umur["listing_date"].strftime("%Y-%m-%d")
            row["Post_IPO_Label"] = umur["label"]
            row["Post_IPO_Days"] = umur["days"]
            row["Post_IPO_Is_Estimate"] = umur["is_estimate_only"]
        else:
            row["Listing_Date_Estimasi"] = None
            row["Post_IPO_Label"] = "Tidak diketahui"
            row["Post_IPO_Days"] = None
            row["Post_IPO_Is_Estimate"] = None

    # Tandai is_new dibanding hasil run sebelumnya
    for row in all_results:
        row["is_new"] = row["Ticker"] not in prev_tickers.get(row["Setup"], set())

    # Urutkan global: TP_Pot_pct terbesar -> terkecil (None di belakang)
    def sort_key(row):
        v = row.get("TP_Pot_pct")
        return v if v is not None else -999999

    all_results.sort(key=sort_key, reverse=True)

    # Tambahkan rank
    for i, row in enumerate(all_results, start=1):
        row["rank"] = i

    # Simpan candle chart untuk ticker yang lolos screening saja (hemat ukuran file)
    tickers_lolos = sorted(set(row["Ticker"] for row in all_results))
    charts = {}
    for tkr in tickers_lolos:
        df = daily_data.get(tkr)
        if df is not None:
            charts[tkr] = screener.extract_chart_data(df, n=90)
    log(f"Chart data disiapkan untuk {len(charts)} ticker.")

    now = datetime.now()
    output = {
        "generated_at": now.isoformat(),
        "generated_at_display": now.strftime("%d %B %Y, %H:%M WIB"),
        "total_ticker_discan": len(daily_data),
        "total_ticker_terdaftar": len(tickers_yf),
        "summary": {
            "setup1_count": len(r1),
            "setup2_count": len(r2),
            "setup3_count": len(r3),
            "setup4_count": len(r4),
            "total_count": len(all_results),
            "new_count": sum(1 for r in all_results if r["is_new"]),
        },
        "results": all_results,
        "charts": charts,
    }

    with open(config.LATEST_RESULT_FILE, "w") as f:
        json.dump(output, f, indent=None, default=str)
    log(f"Hasil disimpan ke {config.LATEST_RESULT_FILE}")

    history_file = os.path.join(config.HISTORY_DIR, f"{now.strftime('%Y-%m-%d')}.json")
    # History tidak usah simpan full chart, biar repo tidak membengkak
    history_output = {k: v for k, v in output.items() if k != "charts"}
    with open(history_file, "w") as f:
        json.dump(history_output, f, indent=None, default=str)
    log(f"Arsip disimpan ke {history_file}")

    log("=== SELESAI ===")


if __name__ == "__main__":
    main()
