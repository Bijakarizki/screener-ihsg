"""
Fetch daftar emiten resmi IDX (kode saham + tanggal IPO/listing) dari endpoint
publik yang dipakai website idx.co.id sendiri.

Endpoint ini TIDAK didokumentasikan resmi sebagai API publik (bukan produk
"IDX Data Reference" berbayar) -- ini endpoint internal yang dipakai halaman
web idx.co.id untuk menampilkan tabel "Daftar Saham". Karena itu:
- Selalu ada fallback ke config.SAHAM_IHSG (list statis) kalau fetch gagal,
  supaya screener tidak pernah berhenti total gara-gara endpoint ini berubah/down.
- Response di-cache ke disk (data/emiten_idx.json) supaya:
  1. Kalau endpoint down di suatu hari, run tetap bisa pakai cache terakhir.
  2. Tidak perlu selalu fetch ulang kalau mau development/test lokal.

Field yang dipakai dari response IDX:
- Code         -> kode ticker (tanpa .JK)
- Name         -> nama perusahaan
- ListingDate  -> tanggal IPO asli (format ISO, misal "1997-12-09T00:00:00")
- ListingBoard -> papan pencatatan (Utama/Pengembangan/Akselerasi/dst)
"""

import json
import os
from datetime import datetime

import requests

IDX_STOCK_LIST_URL = "https://www.idx.co.id/umbraco/Surface/StockData/GetSecuritiesStock"
EMITEN_CACHE_FILE = "data/emiten_idx.json"

# Header wajib -- endpoint ini kadang menolak request tanpa User-Agent browser.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.idx.co.id/id/data-pasar/data-saham/daftar-saham/",
}


def _parse_listing_date(raw):
    """Parse tanggal ISO dari IDX. Return None kalau kosong/gagal parse."""
    if not raw:
        return None
    try:
        # Format umum: "1997-12-09T00:00:00"
        return datetime.fromisoformat(raw.split("T")[0])
    except (ValueError, AttributeError):
        return None


def fetch_emiten_idx(timeout=20, length=2000):
    """
    Fetch daftar emiten dari endpoint publik IDX.

    Return list of dict: [{"code": "BBCA", "name": "...", "listing_date": datetime|None,
                            "listing_board": "Utama"}, ...]
    Raise exception kalau request gagal / response tidak sesuai ekspektasi --
    caller (get_emiten_list) yang menangani fallback.
    """
    params = {
        "securities": "",
        "code": "",
        "sector": "",
        "subsector": "",
        "indexcode": "",
        "start": 0,
        "length": length,
    }
    resp = requests.get(IDX_STOCK_LIST_URL, params=params, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    # Struktur umum: {"data": [...], "recordsTotal": N, ...} tapi kadang langsung list.
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not rows:
        raise ValueError("Response IDX kosong / format tidak dikenali")

    out = []
    for r in rows:
        code = (r.get("Code") or r.get("code") or "").strip().upper()
        if not code:
            continue
        out.append(
            {
                "code": code,
                "name": r.get("Name") or r.get("name") or "",
                "listing_date": _parse_listing_date(r.get("ListingDate") or r.get("listingDate")),
                "listing_board": r.get("ListingBoard") or r.get("listingBoard") or "",
            }
        )

    if len(out) < 100:
        # Sanity check -- IDX punya 900+ emiten. Kalau hasilnya jauh lebih
        # sedikit, kemungkinan endpoint berubah bentuk / request diblokir.
        raise ValueError(f"Hasil parse cuma {len(out)} emiten, dicurigai response tidak lengkap")

    return out


def _save_cache(emiten_list, cache_file=EMITEN_CACHE_FILE):
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    serializable = [
        {
            "code": e["code"],
            "name": e["name"],
            "listing_date": e["listing_date"].strftime("%Y-%m-%d") if e["listing_date"] else None,
            "listing_board": e["listing_board"],
        }
        for e in emiten_list
    ]
    with open(cache_file, "w") as f:
        json.dump(
            {"fetched_at": datetime.now().isoformat(), "emiten": serializable},
            f,
            indent=None,
        )


def _load_cache(cache_file=EMITEN_CACHE_FILE):
    if not os.path.exists(cache_file):
        return None
    try:
        with open(cache_file, "r") as f:
            payload = json.load(f)
        out = []
        for e in payload.get("emiten", []):
            ld = e.get("listing_date")
            out.append(
                {
                    "code": e["code"],
                    "name": e.get("name", ""),
                    "listing_date": datetime.strptime(ld, "%Y-%m-%d") if ld else None,
                    "listing_board": e.get("listing_board", ""),
                }
            )
        return out
    except Exception:
        return None


def get_emiten_list(fallback_tickers, log=print, cache_file=EMITEN_CACHE_FILE):
    """
    Entry point utama. Urutan prioritas:
    1. Fetch langsung dari endpoint IDX (paling fresh, ada listing_date resmi).
    2. Kalau gagal -> pakai cache lokal terakhir (data/emiten_idx.json) kalau ada.
    3. Kalau cache juga tidak ada -> fallback ke `fallback_tickers` (config.SAHAM_IHSG),
       semua tanpa listing_date (nanti akan ditandai "Tidak diketahui" di label post-IPO).

    Return list of dict seperti fetch_emiten_idx().
    """
    try:
        emiten_list = fetch_emiten_idx()
        log(f"Berhasil fetch {len(emiten_list)} emiten dari IDX (live).")
        try:
            _save_cache(emiten_list, cache_file)
        except Exception as e:
            log(f"Gagal simpan cache emiten (tidak fatal): {e}")
        return emiten_list
    except Exception as e:
        log(f"Fetch emiten IDX gagal ({e}), coba pakai cache lokal ...")

    cached = _load_cache(cache_file)
    if cached:
        log(f"Pakai cache emiten lokal ({len(cached)} emiten).")
        return cached

    log(f"Tidak ada cache, fallback ke daftar statis config.py ({len(fallback_tickers)} ticker).")
    return [
        {"code": t, "name": "", "listing_date": None, "listing_board": ""}
        for t in fallback_tickers
    ]


def hitung_umur_listing(listing_date, as_of=None):
    """
    Hitung umur listing dari `listing_date` sampai `as_of` (default: sekarang).
    Return dict {"days": int, "label": "X tahun Y bulan"} atau None kalau
    listing_date tidak diketahui.
    """
    if listing_date is None:
        return None
    as_of = as_of or datetime.now()
    days = (as_of - listing_date).days
    if days < 0:
        return None

    years = days // 365
    months = (days % 365) // 30

    if years == 0 and months == 0:
        label = f"{days} hari"
    elif years == 0:
        label = f"{months} bulan"
    else:
        label = f"{years} tahun" + (f" {months} bulan" if months else "")

    return {"days": days, "years": years, "months": months, "label": label}
