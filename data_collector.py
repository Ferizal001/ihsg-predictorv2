# ============================================================
#  data_collector.py — Pengumpulan & Preprocessing 6 Sumber
# ============================================================

import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import requests
import json
import os
from config import DATA_SOURCES, COMMODITIES, PATHS

# ── Catatan: ganti fungsi _fetch_* dengan API key Anda ──────


# ════════════════════════════════════════════════════════════
#  SUMBER 1 — HARGA SAHAM (OHLCV)
# ════════════════════════════════════════════════════════════

def fetch_harga_saham(ticker: str, periode_hari: int = 365) -> pd.DataFrame:
    """
    Ambil data OHLCV dari Yahoo Finance.
    ticker  : kode saham (misal 'ADRO.JK', 'BBRI.JK')
    return  : DataFrame dengan kolom Open/High/Low/Close/Volume
    """
    try:
        import yfinance as yf
        end   = datetime.today()
        start = end - timedelta(days=periode_hari)
        df    = yf.download(ticker, start=start, end=end, progress=False)
        df.columns = [c.lower() for c in df.columns]
        df.index   = pd.to_datetime(df.index)
        return df.dropna()
    except ImportError:
        # Fallback: baca dari CSV lokal kalau yfinance tidak tersedia
        path = os.path.join(PATHS["data_dir"], f"{ticker}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            df.columns = [c.lower() for c in df.columns]
            return df.dropna()
        return pd.DataFrame()


def fetch_semua_saham_idx() -> dict:
    """
    Ambil daftar saham IDX dari file lokal atau API BEI.
    return: dict { ticker: DataFrame OHLCV }
    """
    # Daftar contoh — ganti dengan scraping BEI atau IDX API
    daftar_tickers = [
        "ADRO.JK","PTBA.JK","BBRI.JK","BMRI.JK","BBCA.JK",
        "INCO.JK","ANTM.JK","TLKM.JK","UNVR.JK","GOTO.JK",
        # ... tambahkan 800+ saham IDX di sini
    ]
    hasil = {}
    for ticker in daftar_tickers:
        df = fetch_harga_saham(ticker)
        if not df.empty:
            hasil[ticker] = df
    return hasil


# ════════════════════════════════════════════════════════════
#  SUMBER 2 — CUACA JAKARTA
# ════════════════════════════════════════════════════════════

def fetch_cuaca_jakarta(tanggal: date) -> dict:
    """
    Ambil data cuaca Jakarta dari Open-Meteo API (gratis).
    return: dict fitur cuaca hari itu
    """
    try:
        url = (
            "https://archive-api.open-meteo.com/v1/archive"
            f"?latitude=-6.2&longitude=106.8"
            f"&start_date={tanggal}&end_date={tanggal}"
            "&daily=temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,windspeed_10m_max"
            "&timezone=Asia/Jakarta"
        )
        r    = requests.get(url, timeout=10)
        data = r.json()["daily"]
        return {
            "suhu_max"   : data["temperature_2m_max"][0],
            "suhu_min"   : data["temperature_2m_min"][0],
            "hujan_mm"   : data["precipitation_sum"][0],
            "angin_max"  : data["windspeed_10m_max"][0],
            "is_banjir"  : int((data["precipitation_sum"][0] or 0) > 50),
        }
    except Exception:
        # Nilai default kalau API tidak tersedia
        return {"suhu_max": 32, "suhu_min": 25, "hujan_mm": 0,
                "angin_max": 15, "is_banjir": 0}


# ════════════════════════════════════════════════════════════
#  SUMBER 3 — KALENDER EFEK (HIJRIAH + MASEHI)
# ════════════════════════════════════════════════════════════

def get_fitur_kalender(tanggal: date) -> dict:
    """
    Hitung semua fitur kalender Hijriah dan Masehi untuk 1 hari.
    return: dict ~15 fitur kalender
    """
    # ── Kalender Hijriah ──────────────────────────────────
    try:
        from hijri_converter import convert
        h = convert.Gregorian(tanggal.year, tanggal.month, tanggal.day).to_hijri()
        bulan_hijri = h.month
        hari_hijri  = h.day
    except ImportError:
        # Estimasi sederhana kalau library tidak tersedia
        bulan_hijri = ((tanggal.month + 10) % 12) + 1
        hari_hijri  = tanggal.day

    is_ramadan  = int(bulan_hijri == 9)
    is_syawal   = int(bulan_hijri == 10)
    is_dzulhijj = int(bulan_hijri == 12)

    # Estimasi hari menuju/setelah lebaran (Syawal hari 1)
    # Hitung mundur dari akhir Ramadan
    if is_ramadan:
        sisa_ramadan = 30 - hari_hijri
        days_to_lebaran = sisa_ramadan
    elif is_syawal:
        days_to_lebaran = -hari_hijri   # negatif = sudah lewat
    else:
        days_to_lebaran = 999           # jauh dari lebaran

    days_after_lebaran = max(0, -days_to_lebaran) if is_syawal else 0
    is_libur_lebaran   = int(is_syawal and hari_hijri <= 7)
    is_idul_adha_week  = int(is_dzulhijj and 8 <= hari_hijri <= 15)

    # ── Kalender Masehi ───────────────────────────────────
    bulan = tanggal.month
    hari  = tanggal.day
    dw    = tanggal.weekday()  # 0=Senin, 4=Jumat

    is_januari         = int(bulan == 1)
    is_desember        = int(bulan == 12)
    days_to_year_end   = (date(tanggal.year, 12, 31) - tanggal).days
    is_quarter_end     = int((bulan in [3, 6, 9, 12]) and hari >= 28)
    is_christmas       = int(bulan == 12 and 24 <= hari <= 31)
    is_new_year_period = int((bulan == 12 and hari >= 28) or
                              (bulan == 1  and hari <= 7))
    is_window_dressing = int(bulan == 12 and 10 <= hari <= 25)

    # ── Efek long weekend ────────────────────────────────
    is_jumat = int(dw == 4)
    is_senin = int(dw == 0)

    # Libur nasional Indonesia (perkiraan tetap)
    libur_nasional = {
        (1, 1), (5, 1), (8, 17), (12, 25), (12, 26)
    }
    besok = tanggal + timedelta(days=1)
    is_eve_libur = int((besok.month, besok.day) in libur_nasional or
                        besok.weekday() >= 5)

    return {
        # Hijriah
        "bulan_hijri"        : bulan_hijri,
        "is_ramadan"         : is_ramadan,
        "is_syawal"          : is_syawal,
        "days_to_lebaran"    : min(days_to_lebaran, 30),
        "days_after_lebaran" : min(days_after_lebaran, 14),
        "is_libur_lebaran"   : is_libur_lebaran,
        "is_idul_adha_week"  : is_idul_adha_week,
        # Masehi
        "bulan"              : bulan,
        "is_januari"         : is_januari,
        "is_desember"        : is_desember,
        "days_to_year_end"   : min(days_to_year_end, 60),
        "is_quarter_end"     : is_quarter_end,
        "is_window_dressing" : is_window_dressing,
        "is_christmas"       : is_christmas,
        "is_new_year_period" : is_new_year_period,
        # Long weekend
        "is_jumat"           : is_jumat,
        "is_senin"           : is_senin,
        "is_eve_libur"       : is_eve_libur,
    }


# ════════════════════════════════════════════════════════════
#  SUMBER 4 — BERITA & SENTIMEN
# ════════════════════════════════════════════════════════════

def fetch_sentimen_berita(tanggal: date, ticker: str = None) -> dict:
    """
    Scraping berita dan hitung skor sentimen dengan NLP.
    Gunakan IndoBERT atau rule-based jika model tidak tersedia.
    return: dict skor sentimen hari itu
    """
    # ── Contoh implementasi rule-based sederhana ──────────
    # Ganti dengan IndoBERT untuk akurasi lebih tinggi

    kata_positif = [
        "naik", "profit", "laba", "pertumbuhan", "rekor", "dividen",
        "ekspansi", "akuisisi", "kerjasama", "bullish", "optimis"
    ]
    kata_negatif = [
        "turun", "rugi", "penurunan", "krisis", "gagal", "bangkrut",
        "default", "bearish", "pesimis", "korupsi", "penyelidikan"
    ]

    try:
        from bs4 import BeautifulSoup
        # Scraping contoh — ganti URL sesuai sumber
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://www.bisnis.com/search?keywords={ticker or 'IHSG'}"
        r   = requests.get(url, timeout=10, headers=headers)
        soup = BeautifulSoup(r.text, "html.parser")
        teks = " ".join([h.get_text() for h in soup.find_all(["h1","h2","h3","p"])[:20]])
        teks = teks.lower()
    except Exception:
        teks = ""

    if not teks:
        return {
            "skor_sentimen"   : 0.0,
            "jumlah_positif"  : 0,
            "jumlah_negatif"  : 0,
            "buzz_score"      : 0,
        }

    n_pos = sum(1 for k in kata_positif if k in teks)
    n_neg = sum(1 for k in kata_negatif if k in teks)
    total = n_pos + n_neg

    skor = (n_pos - n_neg) / total if total > 0 else 0.0
    skor = max(-1.0, min(1.0, skor))   # clamp -1 sampai +1

    return {
        "skor_sentimen"  : round(skor, 3),
        "jumlah_positif" : n_pos,
        "jumlah_negatif" : n_neg,
        "buzz_score"     : total,
    }


# ════════════════════════════════════════════════════════════
#  SUMBER 5 — KOMODITAS GLOBAL
# ════════════════════════════════════════════════════════════

def fetch_komoditas(tanggal: date) -> dict:
    """
    Ambil harga komoditas dari Yahoo Finance atau Trading Economics.
    return: dict perubahan % harga per komoditas
    """
    hasil = {}
    for nama, ticker in COMMODITIES.items():
        try:
            import yfinance as yf
            end   = tanggal
            start = tanggal - timedelta(days=7)
            df    = yf.download(ticker, start=start, end=end, progress=False)
            if len(df) >= 2:
                pct_change = float((df["Close"].iloc[-1] / df["Close"].iloc[-2]) - 1)
                hasil[f"{nama}_pct"]   = round(pct_change, 4)
                hasil[f"{nama}_close"] = float(df["Close"].iloc[-1])
            else:
                hasil[f"{nama}_pct"]   = 0.0
                hasil[f"{nama}_close"] = 0.0
        except Exception:
            hasil[f"{nama}_pct"]   = 0.0
            hasil[f"{nama}_close"] = 0.0

    # Lag features: komoditas 1 dan 2 hari lalu
    for nama in COMMODITIES.keys():
        hasil[f"{nama}_lag1"] = hasil.get(f"{nama}_pct", 0.0)

    return hasil


# ════════════════════════════════════════════════════════════
#  SUMBER 6 — SUPPLY & DEMAND
# ════════════════════════════════════════════════════════════

def hitung_supply_demand(df_ohlcv: pd.DataFrame) -> dict:
    """
    Hitung fitur supply/demand dari data OHLCV historis.
    df_ohlcv : DataFrame dengan kolom close, volume, high, low
    return   : dict fitur supply/demand
    """
    if df_ohlcv.empty or len(df_ohlcv) < 30:
        return {k: 0 for k in [
            "volume_spike", "akumulasi", "distribusi",
            "volume_ratio", "price_momentum", "is_breakout"
        ]}

    close  = df_ohlcv["close"]
    volume = df_ohlcv["volume"]
    high   = df_ohlcv["high"]

    # Volume spike: volume hari ini vs rata-rata 30 hari
    vol_avg_30     = volume.iloc[-31:-1].mean()
    vol_hari_ini   = volume.iloc[-1]
    volume_ratio   = vol_hari_ini / vol_avg_30 if vol_avg_30 > 0 else 1.0

    # Akumulasi: harga naik + volume naik
    harga_naik  = int(close.iloc[-1] > close.iloc[-2])
    volume_naik = int(volume.iloc[-1] > volume.iloc[-2])
    akumulasi   = int(harga_naik and volume_naik)
    distribusi  = int((not harga_naik) and volume_naik)

    # Price momentum 5 hari
    momentum_5d = float((close.iloc[-1] / close.iloc[-6]) - 1) if len(close) > 6 else 0.0

    # Breakout: harga tembus high 20 hari
    high_20d   = high.iloc[-21:-1].max()
    is_breakout = int(close.iloc[-1] > high_20d)

    # Volume spike biner (>2x rata-rata = spike)
    volume_spike = int(volume_ratio > 2.0)

    return {
        "volume_ratio"   : round(float(volume_ratio), 3),
        "volume_spike"   : volume_spike,
        "akumulasi"      : akumulasi,
        "distribusi"     : distribusi,
        "momentum_5d"    : round(momentum_5d, 4),
        "is_breakout"    : is_breakout,
    }


# ════════════════════════════════════════════════════════════
#  GABUNGKAN SEMUA SUMBER — 1 BARIS PER SAHAM PER HARI
# ════════════════════════════════════════════════════════════

def buat_fitur_harian(ticker: str, df_ohlcv: pd.DataFrame,
                       tanggal: date) -> dict:
    """
    Gabungkan semua 6 sumber menjadi 1 vektor fitur per saham per hari.
    """
    fitur = {"ticker": ticker, "tanggal": str(tanggal)}

    # Sumber 6: supply/demand (dari OHLCV)
    fitur.update(hitung_supply_demand(df_ohlcv))

    # Sumber 3: kalender
    fitur.update(get_fitur_kalender(tanggal))

    # Sumber 4: sentimen berita
    fitur.update(fetch_sentimen_berita(tanggal, ticker))

    # Sumber 5: komoditas
    fitur.update(fetch_komoditas(tanggal))

    # Sumber 2: cuaca
    fitur.update(fetch_cuaca_jakarta(tanggal))

    return fitur
