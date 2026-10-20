

Web app screener saham IHSG berdasarkan logic dari notebook aslinya (Setup 1, 2, 3),
jalan otomatis tiap hari setelah market close, gratis selamanya, tanpa perlu laptop nyala.

## Cara kerja

```
GitHub Actions (jadwal harian, jam 16:30 WIB)
        │
        │  download data yfinance + jalankan screening
        ▼
  data/latest_result.json   (disimpan otomatis ke repo)
        │
        ▼
Streamlit Community Cloud (dashboard, baca file di atas)
```

- **GitHub Actions** = "robot" yang jalan otomatis tiap hari kerja jam 16:30 WIB, download data saham, jalankan Setup 1/2/3, simpan hasil. Gratis, tidak perlu komputer kamu nyala.
- **Streamlit Cloud** = website dashboard yang menampilkan hasil itu dengan tabel + chart. Gratis, auto-update setiap repo berubah.

Setup 3 dipilih (Daily only, tanpa intraday 1 menit), sesuai logic asli notebook.

---

## 🚀 Langkah Deploy (sekali saja, ±15 menit)

### 1. Buat akun GitHub (kalau belum punya)
Daftar gratis di [github.com](https://github.com).

### 2. Buat repository baru
- Klik **New repository** → beri nama misalnya `screener-ihsg` → **Public** → Create.

### 3. Upload semua file di folder ini ke repo tersebut
Cara paling mudah tanpa command line:
- Di halaman repo, klik **Add file → Upload files**.
- Drag & drop **semua file dan folder** di project ini (termasuk folder `.github` dan `data` — pastikan file tersembunyi `.github/workflows/run_screener.yml` ikut terupload; kalau drag-drop tidak menyertakan folder `.github`, gunakan cara command line di bawah).

**Cara command line (lebih aman, menjamin folder `.github` ikut):**
```bash
cd screener_app
git init
git add .
git commit -m "init screener"
git branch -M main
git remote add origin https://github.com/USERNAME/screener-ihsg.git
git push -u origin main
```
Ganti `USERNAME` dengan username GitHub kamu.

### 4. Cek GitHub Actions aktif
- Buka tab **Actions** di repo kamu.
- Kamu akan lihat workflow **"Run Screener Saham IHSG"**.
- Klik workflow itu → klik **Run workflow** (tombol kanan atas) untuk jalankan manual pertama kali → tunggu ±10–20 menit (931 saham, download butuh waktu).
- Setelah selesai (centang hijau ✅), cek folder `data/latest_result.json` di repo — isinya harus sudah terisi hasil screening.

> Mulai besok, workflow ini akan jalan **otomatis sendiri** setiap hari Senin–Jumat jam 16:30 WIB. Tidak perlu disentuh lagi.

### 5. Deploy dashboard ke Streamlit Cloud
- Buka [share.streamlit.io](https://share.streamlit.io) → login dengan akun GitHub.
- Klik **Create app** → pilih repo `screener-ihsg` kamu.
- **Main file path**: `app.py`
- Klik **Deploy**.
- Tunggu 1–2 menit → dashboard kamu sudah online dengan URL publik (contoh: `https://screener-ihsg.streamlit.app`).

Selesai! Buka URL itu kapan saja, dari HP atau laptop, hasilnya selalu yang paling baru.

---

## 🔁 Update otomatis setiap hari

Tidak perlu lakukan apa-apa. Tiap hari kerja jam 16:30 WIB:
1. GitHub Actions jalan otomatis, scan ulang semua saham.
2. Hasil baru di-commit ke `data/latest_result.json`.
3. Streamlit Cloud otomatis mendeteksi perubahan repo dan refresh dashboard (atau refresh manual di browser kalau belum keubah, cache di app ini hanya 5 menit).

## 🧪 Jalankan manual / test lokal (opsional)
```bash
pip install -r requirements.txt
python run_screener.py      # jalankan screening sekali, hasil ke data/
streamlit run app.py        # buka dashboard di localhost
```

## 🛠️ Struktur file
```
screener_app/
├── app.py                  # dashboard Streamlit (UI)
├── screener.py              # logic screening (porting dari notebook asli)
├── run_screener.py          # script yang dijalankan GitHub Actions tiap hari
├── telegram_mepet.py        # notifikasi Telegram: pola mepet + 7 ciri (opsional)
├── config.py                 # daftar 931 ticker + semua parameter SMA/threshold
├── requirements.txt
├── .github/workflows/run_screener.yml   # jadwal otomatis harian
└── data/
    ├── latest_result.json   # hasil terbaru (dibaca dashboard)
    └── history/              # arsip harian (untuk lihat histori ke depan)
```

## ⚙️ Mengubah parameter screening
Semua angka (toleransi SMA, minimal gap TP, dll) ada di `config.py`, sama persis
dengan notebook aslinya. Tinggal ubah angkanya, commit, push — hasil run berikutnya
otomatis pakai parameter baru.

## 📲 Notifikasi Telegram: pola mepet + 7 ciri (opsional)
Setelah screening harian selesai, `telegram_mepet.py` mengirim ke Telegram:
ringkasan pasar, daftar **🎯 Sinyal** (sedang mepet, ≥5/7 ciri, MA besar ≥10% di atas),
**👀 Watchlist** (sempat mepet ≤5 hari lalu, tunggu mepet lagi), dan **📌 Lolos sebelum
event** (saham yang lolos dalam 7 hari bursa sebelum pasar anjlok / news), plus chart
candle + MA + volume tiap saham. Tanpa secret di bawah, langkah ini otomatis dilewati.

Cara menyalakan (sekali saja):
1. Di Telegram, chat **@BotFather** → kirim `/newbot` → ikuti langkahnya → simpan **token** bot.
2. Kirim pesan apa saja ke bot kamu (atau masukkan bot ke grup), lalu buka
   `https://api.telegram.org/bot<TOKEN>/getUpdates` di browser → catat angka `"chat":{"id": ...}`.
3. Di repo GitHub: **Settings → Secrets and variables → Actions → New repository secret**,
   buat `TELEGRAM_BOT_TOKEN` (token tadi) dan `TELEGRAM_CHAT_ID` (angka chat id).
4. Tab **Actions** → **Run Screener Saham IHSG** → **Run workflow** untuk tes kirim.

Parameter (`TG_*`) ada di bagian paling bawah `config.py`. Tanggal kejadian penting
(halt, news) bisa ditambah manual di `TG_EVENT_MANUAL`; hari pasar anjlok juga
terdeteksi otomatis. Uji tanpa kirim: `python telegram_mepet.py --dry-run folder_output`.

## 🛡️ Soal rate-limit Yahoo Finance
Yahoo Finance kadang membatasi (rate-limit) request dari server yang mengirim banyak
permintaan sekaligus, termasuk dari GitHub Actions. Untuk mengatasi ini, `screener.py`
sudah dilengkapi:
- Session yang menyamar sebagai browser Chrome asli (`curl_cffi`), bukan request polos.
- Download dipecah jadi batch kecil (25 saham/batch) dengan jeda antar batch.
- Retry otomatis dengan backoff kalau satu batch gagal total.

Kalau suatu hari hasil run tetap kosong atau jauh lebih sedikit dari biasanya (cek log
di tab Actions), itu tanda Yahoo sedang membatasi cukup keras — coba **Run workflow**
manual lagi beberapa jam kemudian, biasanya sudah normal lagi. Ini bukan bug di kode,
melainkan kebijakan pembatasan dari pihak Yahoo yang di luar kendali kita.

## ⚠️ Disclaimer
Ini alat bantu analisa teknikal berbasis SMA dan volume, **bukan rekomendasi atau
saran finansial**. Selalu lakukan riset tambahan dan kelola risiko sendiri sebelum
mengambil keputusan investasi.
