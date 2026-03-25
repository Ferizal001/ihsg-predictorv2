# ============================================================
#  risk_manager.py — Market Regime, Risiko & Retrain Otomatis
# ============================================================

import pandas as pd
import numpy as np
import os
import json
from datetime import date, datetime, timedelta
from config import REGIME_CONFIG, TRADING_CONFIG, RETRAIN_CONFIG, PATHS


# ════════════════════════════════════════════════════════════
#  MARKET REGIME DETECTION — SISTEM LAMPU 3 WARNA
# ════════════════════════════════════════════════════════════

def cek_kondisi_pasar(
    ihsg_return_hari_ini: float,
    vix: float,
    foreign_net_sell_hari: int,
    akurasi_rolling_14d: float,
    usd_idr_change_7d: float,
    portfolio_return_bulan: float,
) -> dict:
    """
    Tentukan kondisi pasar: HIJAU / KUNING / MERAH.
    Semua parameter dihitung otomatis dari data real-time.

    return: dict dengan 'lampu', 'alasan', dan 'aksi'
    """
    alasan_merah  = []
    alasan_kuning = []

    # ── Cek kondisi MERAH ────────────────────────────────
    if ihsg_return_hari_ini <= REGIME_CONFIG["ihsg_drop_merah"]:
        alasan_merah.append(f"IHSG turun {ihsg_return_hari_ini:.1%} (>3%)")

    if vix >= REGIME_CONFIG["vix_merah"]:
        alasan_merah.append(f"VIX = {vix:.1f} (panik global)")

    if akurasi_rolling_14d < REGIME_CONFIG["akurasi_min_kuning"]:
        alasan_merah.append(f"Akurasi model {akurasi_rolling_14d:.1%} (<50% = drift)")

    if portfolio_return_bulan <= REGIME_CONFIG["portfolio_stop_loss"]:
        alasan_merah.append(f"Portfolio turun {portfolio_return_bulan:.1%} bulan ini")

    if usd_idr_change_7d >= 0.02:
        alasan_merah.append(f"Rupiah melemah {usd_idr_change_7d:.1%} dalam 7 hari")

    # ── Cek kondisi KUNING ───────────────────────────────
    if not alasan_merah:
        if vix >= REGIME_CONFIG["vix_kuning"]:
            alasan_kuning.append(f"VIX = {vix:.1f} (mulai bergejolak)")

        if foreign_net_sell_hari >= REGIME_CONFIG["foreign_sell_hari"]:
            alasan_kuning.append(
                f"Asing net sell {foreign_net_sell_hari} hari berturut-turut"
            )

        if akurasi_rolling_14d < REGIME_CONFIG["akurasi_min_hijau"]:
            alasan_kuning.append(f"Akurasi model {akurasi_rolling_14d:.1%} (50-60%)")

        if usd_idr_change_7d >= 0.01:
            alasan_kuning.append(f"Rupiah melemah {usd_idr_change_7d:.1%} (waspada)")

    # ── Tentukan lampu ───────────────────────────────────
    if alasan_merah:
        lampu = "MERAH"
        aksi  = ("STOP semua trading · jual posisi terbuka · "
                 "simpan kas · tunggu kondisi pulih")
        alasan = alasan_merah

    elif alasan_kuning:
        lampu = "KUNING"
        aksi  = ("Ambil Top 2–3 saham saja · posisi diperkecil 50% · "
                 "stop loss lebih ketat")
        alasan = alasan_kuning

    else:
        lampu  = "HIJAU"
        aksi   = "Trading normal · ambil Top 5 · posisi penuh"
        alasan = ["Semua kondisi aman"]

    return {
        "lampu"    : lampu,
        "alasan"   : alasan,
        "aksi"     : aksi,
        "timestamp": str(datetime.now()),
    }


def cek_eve_libur_panjang(tanggal: date) -> bool:
    """
    Cek apakah besok libur panjang (≥ 3 hari).
    Kalau iya → tidak buka posisi baru hari ini.
    """
    libur_nasional = {
        date(tanggal.year, 1,  1),   # Tahun Baru
        date(tanggal.year, 5,  1),   # Hari Buruh
        date(tanggal.year, 8, 17),   # HUT RI
        date(tanggal.year, 12, 25),  # Natal
        date(tanggal.year, 12, 26),  # Cuti Natal
    }

    hari_libur_berturut = 0
    cek = tanggal + timedelta(days=1)
    for _ in range(5):
        if cek.weekday() >= 5 or cek in libur_nasional:
            hari_libur_berturut += 1
            cek += timedelta(days=1)
        else:
            break

    return hari_libur_berturut >= 3


# ════════════════════════════════════════════════════════════
#  POSITION SIZING — BERAPA MODAL PER SAHAM
# ════════════════════════════════════════════════════════════

def hitung_posisi(
    modal_total: float,
    skor: float,
    lampu: str,
    n_posisi_aktif: int,
) -> dict:
    """
    Hitung ukuran posisi berdasarkan skor, lampu, dan modal.

    return: dict dengan 'alokasi_rp', 'pct_modal', 'layak'
    """
    tp  = TRADING_CONFIG["take_profit_pct"]
    sl  = abs(TRADING_CONFIG["stop_loss_pct"])
    kas = TRADING_CONFIG["min_kas_pct"]

    # Cek rasio risk/reward minimum 1:2
    if tp / sl < 2.0:
        return {"layak": False, "alasan": "Rasio R/R < 1:2, skip trade"}

    # Cek skor minimum
    min_skor = 75 if lampu == "HIJAU" else 65
    if skor < min_skor:
        return {"layak": False, "alasan": f"Skor {skor} < {min_skor}"}

    # Cek slot posisi
    max_pos = TRADING_CONFIG["max_posisi"]
    if lampu == "KUNING":
        max_pos = 2
    if n_posisi_aktif >= max_pos:
        return {"layak": False, "alasan": f"Sudah {n_posisi_aktif} posisi aktif"}

    # Hitung alokasi
    modal_aktif = modal_total * (1 - kas)
    if lampu == "KUNING":
        modal_aktif *= 0.5   # Kurangi 50% saat kuning

    alokasi_base = modal_aktif / max_pos

    # Sesuaikan dengan skor
    if skor >= 80:
        faktor = 1.00   # Posisi penuh
    elif skor >= 70:
        faktor = 0.75
    elif skor >= 60:
        faktor = 0.50
    else:
        faktor = 0.25

    alokasi = alokasi_base * faktor

    # Pastikan risiko per trade ≤ 2% modal
    risiko_rp    = alokasi * sl
    risiko_pct   = risiko_rp / modal_total
    if risiko_pct > TRADING_CONFIG["max_risiko_per_trade"]:
        alokasi = (modal_total * TRADING_CONFIG["max_risiko_per_trade"]) / sl

    return {
        "layak"      : True,
        "alokasi_rp" : round(alokasi, 0),
        "pct_modal"  : round(alokasi / modal_total, 4),
        "risiko_rp"  : round(alokasi * sl, 0),
        "risiko_pct" : round(risiko_pct, 4),
        "target_rp"  : round(alokasi * tp, 0),
        "stop_loss_harga_pct" : -sl,
        "take_profit_harga_pct": tp,
    }


def hitung_trailing_stop(
    harga_beli: float,
    harga_tertinggi: float,
    trailing_pct: float = None,
) -> float:
    """
    Hitung level trailing stop loss.
    Stop loss mengikuti naik tapi tidak turun.
    """
    if trailing_pct is None:
        trailing_pct = TRADING_CONFIG["trailing_stop_pct"]

    stop = harga_tertinggi * (1 - trailing_pct)
    stop_awal = harga_beli * (1 + abs(TRADING_CONFIG["stop_loss_pct"]))
    return max(stop, stop_awal * (1 - TRADING_CONFIG["trailing_stop_pct"]))


# ════════════════════════════════════════════════════════════
#  JURNAL TRADING — CATAT SETIAP TRANSAKSI
# ════════════════════════════════════════════════════════════

def catat_jurnal(transaksi: dict):
    """Catat 1 transaksi ke jurnal CSV."""
    os.makedirs(PATHS["log_dir"], exist_ok=True)
    path = PATHS["jurnal"]
    df   = pd.DataFrame([transaksi])

    if os.path.exists(path):
        df.to_csv(path, mode="a", header=False, index=False)
    else:
        df.to_csv(path, index=False)


def baca_jurnal() -> pd.DataFrame:
    """Baca semua jurnal trading."""
    path = PATHS["jurnal"]
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


def hitung_statistik_jurnal(df_jurnal: pd.DataFrame) -> dict:
    """Hitung statistik ringkasan dari jurnal trading."""
    if df_jurnal.empty:
        return {}

    return {
        "total_trade"  : len(df_jurnal),
        "win_rate"     : float((df_jurnal["hasil_pct"] > 0).mean()),
        "avg_profit"   : float(df_jurnal["hasil_pct"].mean()),
        "avg_win"      : float(df_jurnal.loc[df_jurnal["hasil_pct"]>0,"hasil_pct"].mean()),
        "avg_loss"     : float(df_jurnal.loc[df_jurnal["hasil_pct"]<0,"hasil_pct"].mean()),
        "profit_factor": float(
            df_jurnal.loc[df_jurnal["hasil_pct"]>0,"hasil_pct"].sum() /
            abs(df_jurnal.loc[df_jurnal["hasil_pct"]<0,"hasil_pct"].sum() or 1)
        ),
        "total_profit_rp": float(df_jurnal["profit_rp"].sum()),
    }


# ════════════════════════════════════════════════════════════
#  DETEKSI DRIFT & RETRAIN OTOMATIS
# ════════════════════════════════════════════════════════════

def catat_akurasi_harian(tanggal: date, akurasi: float, sektor: str = "all"):
    """Catat akurasi harian untuk monitoring rolling."""
    os.makedirs(PATHS["log_dir"], exist_ok=True)
    path   = PATHS["akurasi_log"]
    record = pd.DataFrame([{
        "tanggal" : str(tanggal),
        "sektor"  : sektor,
        "akurasi" : akurasi,
    }])
    if os.path.exists(path):
        record.to_csv(path, mode="a", header=False, index=False)
    else:
        record.to_csv(path, index=False)


def hitung_akurasi_rolling(window_hari: int = None) -> float:
    """
    Hitung akurasi rolling N hari terakhir.
    return: float akurasi (0.0 - 1.0)
    """
    if window_hari is None:
        window_hari = RETRAIN_CONFIG["rolling_window_hari"]

    path = PATHS["akurasi_log"]
    if not os.path.exists(path):
        return 0.6   # Default awal sebelum ada data

    df  = pd.read_csv(path)
    df  = df[df["sektor"] == "all"].tail(window_hari)
    if df.empty:
        return 0.6
    return float(df["akurasi"].mean())


def perlu_retrain(tanggal_latih_terakhir: date) -> dict:
    """
    Cek apakah model perlu dilatih ulang.
    return: dict { 'perlu': bool, 'alasan': str, 'jenis': str }
    """
    akurasi = hitung_akurasi_rolling()
    hari_sejak_latih = (date.today() - tanggal_latih_terakhir).days

    # ── Retrain darurat: akurasi < 50% ───────────────────
    if akurasi < RETRAIN_CONFIG["drift_threshold"]:
        return {
            "perlu": True,
            "jenis": "DARURAT",
            "alasan": f"Akurasi rolling {akurasi:.1%} di bawah threshold 50%",
        }

    # ── Retrain rutin: sudah 30 hari ─────────────────────
    if hari_sejak_latih >= RETRAIN_CONFIG["jadwal_rutin_hari"]:
        return {
            "perlu": True,
            "jenis": "RUTIN",
            "alasan": f"Sudah {hari_sejak_latih} hari sejak training terakhir",
        }

    # ── Tidak perlu retrain ───────────────────────────────
    return {
        "perlu": False,
        "jenis": None,
        "alasan": (f"Model masih sehat · akurasi {akurasi:.1%} · "
                   f"terlatih {hari_sejak_latih} hari lalu"),
    }


def deteksi_event_krisis(teks_berita: str) -> bool:
    """
    Scan teks berita untuk kata kunci krisis.
    Trigger retrain darurat jika terdeteksi.
    """
    kata_krisis = [
        "krisis", "resesi", "pandemi", "lockdown", "default",
        "gagal bayar", "collaps", "crash", "perang", "sanksi",
        "darurat nasional", "force majeure",
    ]
    teks = teks_berita.lower()
    terdeteksi = [k for k in kata_krisis if k in teks]
    if terdeteksi:
        print(f"[Alert] Kata kritis terdeteksi: {terdeteksi}")
        return True
    return False
