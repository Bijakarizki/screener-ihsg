"""
Estimasi umur listing (Post-IPO age) SETIAP ticker dari histori harga yang
sudah didownload (bar paling awal yang datanya ada), TANPA fetch ke sumber
eksternal apa pun.

Kenapa bukan fetch ke idx.co.id: endpoint publik idx.co.id dilindungi
Cloudflare/WAF yang mem-block request dari IP datacenter (termasuk runner
GitHub Actions) -- dicoba dengan curl_cffi (TLS impersonate Chrome) + warm-up
cookie, tapi hasil investigasi (lihat proyek lain yang perlu headless browser
penuh seperti Camoufox untuk menembusnya) menunjukkan ini butuh browser
sungguhan, bukan sekadar trik header/TLS. Karena itu didekati dengan cara yang
100% tidak butuh network tambahan: pakai tanggal bar PALING AWAL di histori
harga yang sudah didownload lewat yfinance (yang sudah reliable & battle-tested
di screener.py).

Konsekuensi pendekatan ini (disengaja, trade-off yang diterima):
- Untuk emiten yang benar-benar IPO dalam rentang download (config.YF_PERIOD,
  default 5 tahun), umur listing ini AKURAT -- bar pertama di histori kira-kira
  sama dengan tanggal IPO asli.
- Untuk emiten yang sudah listing lebih lama dari rentang download, umur ini
  HANYA estimasi minimum ("setidaknya X tahun") -- bukan tanggal IPO asli.
  Ini ditandai jelas di label sebagai "5+ tahun (established)" alih-alih
  memberi angka umur yang seolah-olah presisi tapi sebenarnya salah.
"""

from datetime import datetime

import config


def estimasi_listing_date(df):
    """
    Ambil tanggal bar paling awal yang tersedia di histori harga `df`
    (DataFrame hasil screener.download_daily, index = tanggal).
    Return datetime atau None kalau df kosong.
    """
    if df is None or df.empty:
        return None
    try:
        return df.index[0].to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None


def hitung_umur_listing(df, as_of=None):
    """
    Hitung estimasi umur listing dari histori harga `df`.

    Return dict {"days": int, "label": str, "is_estimate_only": bool} atau
    None kalau tidak bisa dihitung (df kosong).

    `is_estimate_only` True kalau histori yang tersedia sudah mentok di awal
    rentang download (config.YF_PERIOD) -- artinya bar pertama BUKAN tanggal
    IPO asli, cuma batas awal data yang kita punya. Dalam kasus ini label
    dibuat eksplisit "X+ tahun (histori terbatas)" supaya tidak menyesatkan
    seolah-olah itu tanggal IPO pasti.
    """
    listing_date = estimasi_listing_date(df)
    if listing_date is None:
        return None

    as_of = as_of or datetime.now()
    days = (as_of - listing_date).days
    if days < 0:
        return None

    # Deteksi "histori mentok di awal": kalau bar pertama cuma berjarak
    # beberapa hari dari batas teoritis rentang download (YF_PERIOD dalam
    # tahun), kemungkinan besar itu bukan tanggal IPO asli, cuma awal window
    # yang kita minta ke yfinance.
    period_years = _parse_period_years(config.YF_PERIOD)
    window_days = int(period_years * 365) if period_years else None
    near_window_edge = window_days is not None and days >= window_days - 20

    years = days // 365
    months = (days % 365) // 30

    if near_window_edge:
        label = f"{years}+ tahun (histori terbatas)"
    elif years == 0 and months == 0:
        label = f"{days} hari"
    elif years == 0:
        label = f"{months} bulan"
    else:
        label = f"{years} tahun" + (f" {months} bulan" if months else "")

    return {
        "days": days,
        "years": years,
        "months": months,
        "label": label,
        "is_estimate_only": near_window_edge,
        "listing_date": listing_date,
    }


def _parse_period_years(period_str):
    """Parse string period yfinance semacam '5y', '2y', '10y' -> jumlah tahun (float)."""
    if not period_str:
        return None
    s = period_str.strip().lower()
    if s.endswith("y"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    return None
