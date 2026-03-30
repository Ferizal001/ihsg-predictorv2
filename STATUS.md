# IHSG Predictor Bot — Status Lengkap
**Terakhir update: 28 Maret 2026**

---

## INFO BOT
- **Bot Telegram** : @axygoz_bot
- **Railway project** : airy-playfulness/production
- **GitHub** : https://github.com/samudra-azygo/ihsg-predictor
- **Start command** : `python3 main.py`
- **Token Telegram** : `8744135725:AAEZ9vPbxdmxSBQIUHazu1KmWUngx42MOxE`
- **Chat ID** : `828736755` (Ferizal, @Ferizal11)
- **GROQ_API_KEY** : sudah di Railway Variables

---

## STATUS MODEL
- **Akurasi** : 60.45% (terbaik)
- **Model file** : `models/models_final.pkl` = `models/models_latest.pkl`
- **Sektor** : 11 model terpisah (RandomForest)
- **Saham** : 70 saham aktif IDX
- **Total fitur** : 180

### Akurasi per sektor
```
Properti       : 65.46%
Perbankan      : 62.94%
Tambang        : 62.06%
Agribisnis     : 61.69%
Media          : 62.65%
Lainnya        : 60.40%
Telekomunikasi : 60.06%
Ritel          : 59.13%
Konsumer       : 57.92%
Kesehatan      : 59.57%
Energi         : 56.06%
```

---

## SUMBER DATA (180 FITUR)

### 1. Teknikal OHLCV (18 fitur)
- 70 saham IDX via Yahoo Finance
- RSI, MACD, Bollinger Band, Volume ratio
- Momentum 5d/20d, MFI, CMF

### 2. Komoditas (28 fitur)
- Coal, Oil, Gold, CPO
- Beras, Gandum, Jagung, Kedelai
- File: `data/komoditas/KOMODITAS_GABUNGAN.csv`

### 3. Cuaca Global (28 fitur — 7 negara)
- Indonesia (Kalimantan — sawit)
- Australia (Queensland — coal)
- Brasil (Mato Grosso — kedelai)
- Jerman (Frankfurt — gas)
- China (Shanghai — industri)
- Amerika (Chicago — komoditas)
- Rusia (Moskow — energi)
- File: `data/cuaca/CUACA_GABUNGAN.csv`

### 4. Makro Global (67 fitur — 13 sumber)
- Indeks: S&P500, NASDAQ, Nikkei, HangSeng
- Fear: VIX (level, tinggi, panik)
- Kurs: USD, EUR, CNY, JPY, SGD, AUD per IDR
- Bond: US Bond yield
- File: `data/makro/MAKRO_GABUNGAN.csv`

### 5. ENSO + Kalender (35 fitur)
- ONI index, SOI index (El Nino/La Nina)
- Libur nasional Indonesia 2022-2026
- Ramadan, Lebaran (bobot Islam lebih tinggi)
- Window dressing, January effect
- File: `data/enso/ENSO_KALENDER_GABUNGAN.csv`

### 6. Berita Real-time (sentimen)
- IDX Channel, CNBC Indonesia, Detik Finance
- 60+ berita dianalisis per hari
- File: `data/berita/`

---

## JADWAL OTOMATIS (Railway)
```
01:00 UTC = 08:00 WIB → download data saham terbaru
01:15 UTC = 08:15 WIB → scoring + analisis berita → kirim ke Telegram
08:30 UTC = 15:30 WIB → evaluasi harian
```

---

## FORMULA SCORING
```
Skor final = Teknikal(40%) + Berita(30%) + Model AI(30%)
           × bobot sentimen global

Lampu HIJAU  = skor_global > 0.3  → bobot 1.1
Lampu KUNING = -0.3 sampai 0.3    → bobot 1.0
Lampu MERAH  = skor_global < -0.3 → bobot 0.9

Sinyal BELI   = skor final > 75
Sinyal PANTAU = skor final 55-75
Sinyal SKIP   = skor final < 55
```

---

## MANAJEMEN RISIKO
```
Stop loss  : -1% dari harga beli
Take profit: +2% dari harga beli
Rasio      : 1:2
Max saham  : 3 per hari
Kas minimum: 20% modal
```

---

## FILE UTAMA
```
main.py                    ← START COMMAND Railway (bot + jadwal)
sentimen_ai.py             ← Analisis berita pakai Groq AI
analisis_berita.py         ← Analisis berita kamus kata kunci
scoring_dengan_berita.py   ← Scoring manual harian
simpan_model_final.py      ← Training model (GUNAKAN INI)
download_cuaca.py          ← Download cuaca 7 negara
download_enso.py           ← Download ENSO dari NOAA
buat_kalender_lengkap.py   ← Buat kalender libur nasional
update_main_final.py       ← Update kamus sentimen + jadwal WIB
```

---

## PERINTAH BOT TELEGRAM
```
/start    → menu utama
/ranking  → top 10 saham + sentimen berita
/berita   → berita positif dan negatif
/lampu    → status kondisi pasar
/status   → info model dan sistem
/risiko   → panduan manajemen risiko
/posisi [modal] [skor] → kalkulator posisi
/data     → sumber data aktif
/help     → semua perintah
```

---

## YANG BELUM SELESAI (PRIORITAS)

### 1. Integrasikan Groq AI ke main.py (PALING PENTING)
`sentimen_ai.py` sudah jalan tapi belum terhubung ke `main.py`.
Fungsi `ambil_sentimen()` di `main.py` masih pakai kamus kata kunci lama.
Perlu diganti dengan `scoring_sentimen_ai()` dari `sentimen_ai.py`.
**Estimasi dampak: +1-2% akurasi**

### 2. Conflict error Railway
Kalau muncul Conflict error di Railway log:
```bash
pkill -f python3   # di MacBook
```
Tunggu 2 menit → Railway reconnect otomatis.

### 3. Naik akurasi ke 65%+
```
Sekarang  : 60.45%
Langkah 1 : Integrasi Groq AI sentimen → target 62%
Langkah 2 : Kumpul data sentimen historis 3 bulan → target 63%
Langkah 3 : Foreign flow (RTI Business ~Rp400rb/bulan) → target 65%+
```

---

## PERJALANAN AKURASI
```
Awal (OHLCV saja)          : 52.57%
+ Komoditas (coal dll)     : 59.96%
+ Cuaca global (4 negara)  : 59.01%
+ Makro S&P VIX dll        : 60.18%
+ CNY JPY SGD AUD IDR      : 60.45% ← terbaik sekarang
+ ENSO + Kalender          : 60.43% (belum signifikan)
```

---

## CATATAN PENTING
- Jangan jalankan bot di MacBook saat Railway aktif → Conflict error
- `pkill -f python3` untuk matikan semua bot di MacBook
- Gold dihapus dari MAKRO_GABUNGAN (duplikat dengan komoditas)
- Timezone Railway = UTC, jadwal pakai UTC bukan WIB
- GROQ_API_KEY jangan di-hardcode di file Python → simpan di Railway Variables
- GitHub akan blokir push kalau ada API key di dalam file
