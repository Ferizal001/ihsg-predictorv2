# ============================================================
#  main_pipeline.py — Pipeline Operasional Harian (Otomatis)
# ============================================================
#
#  Jadwal eksekusi (via cron atau scheduler):
#  04:00 → python main_pipeline.py --fase kumpul_data
#  06:00 → python main_pipeline.py --fase scoring
#  08:00 → python main_pipeline.py --fase cek_lampu
#  15:30 → python main_pipeline.py --fase evaluasi
#
# ============================================================

import pandas as pd
import numpy as np
import os
import json
import argparse
from datetime import date, datetime, timedelta

from config import PATHS, RETRAIN_CONFIG, TRADING_CONFIG
from data_collector import (
    fetch_harga_saham, fetch_semua_saham_idx,
    buat_fitur_harian, get_fitur_kalender,
)
from feature_engineering import (
    hitung_indikator_teknikal, filter_saham_layak,
    buat_dataset_latih, SEMUA_FITUR,
)
from model import (
    latih_model_per_sektor, simpan_model, muat_model,
    ranking_saham_hari_ini, tampilkan_feature_importance,
    walk_forward_backtest, simulasi_profit,
)
from risk_manager import (
    cek_kondisi_pasar, cek_eve_libur_panjang,
    hitung_posisi, hitung_trailing_stop,
    catat_jurnal, baca_jurnal, hitung_statistik_jurnal,
    catat_akurasi_harian, hitung_akurasi_rolling, perlu_retrain,
    deteksi_event_krisis,
)


# ════════════════════════════════════════════════════════════
#  FASE 1: KUMPUL DATA (04:00)
# ════════════════════════════════════════════════════════════

def fase_kumpul_data(tanggal: date = None):
    """Kumpulkan semua data dari 6 sumber."""
    if tanggal is None:
        tanggal = date.today()

    print(f"\n{'='*60}")
    print(f"FASE 1 · KUMPUL DATA · {tanggal}")
    print(f"{'='*60}")

    os.makedirs(PATHS["data_dir"], exist_ok=True)

    # Ambil semua saham IDX
    print("[1/3] Mengambil OHLCV 800+ saham IDX...")
    dict_ohlcv = fetch_semua_saham_idx()
    print(f"      → {len(dict_ohlcv)} saham berhasil diambil")

    # Simpan ke disk
    for ticker, df in dict_ohlcv.items():
        path = os.path.join(PATHS["data_dir"], f"{ticker.replace('.JK','')}.csv")
        df.to_csv(path)

    print("[2/3] Data cuaca, kalender, komoditas, berita...")
    fitur_kalender = get_fitur_kalender(tanggal)
    print(f"      → Kalender: bulan Hijri={fitur_kalender['bulan_hijri']}, "
          f"is_ramadan={fitur_kalender['is_ramadan']}")

    print("[3/3] Selesai kumpul data")
    print(f"      → Total saham: {len(dict_ohlcv)}")

    return dict_ohlcv


# ════════════════════════════════════════════════════════════
#  FASE 2: SCORING & RANKING (06:00)
# ════════════════════════════════════════════════════════════

def fase_scoring(tanggal: date = None) -> pd.DataFrame:
    """Hitung skor semua saham dan buat ranking."""
    if tanggal is None:
        tanggal = date.today()

    print(f"\n{'='*60}")
    print(f"FASE 2 · SCORING & RANKING · {tanggal}")
    print(f"{'='*60}")

    # Muat data dari disk
    dict_ohlcv = {}
    for f in os.listdir(PATHS["data_dir"]):
        if f.endswith(".csv"):
            ticker = f.replace(".csv", "") + ".JK"
            path   = os.path.join(PATHS["data_dir"], f)
            try:
                df = pd.read_csv(path, index_col=0, parse_dates=True)
                df.columns = [c.lower() for c in df.columns]
                dict_ohlcv[ticker] = df
            except Exception:
                pass

    print(f"[1/4] Loaded {len(dict_ohlcv)} saham dari disk")

    # Filter awal
    print("[2/4] Filter saham tidak layak...")
    dict_layak = filter_saham_layak(dict_ohlcv)

    # Muat model
    print("[3/4] Muat model...")
    try:
        models = muat_model("latest")
        print(f"      → {len(models)} model sektor dimuat")
    except FileNotFoundError:
        print("      ⚠️ Model belum ada · jalankan training dulu")
        return pd.DataFrame()

    # Hitung fitur & skor per saham
    print("[4/4] Hitung skor 0-100 per saham...")
    dict_fitur  = {}
    dict_sektor = {}

    for ticker, df in dict_layak.items():
        try:
            df_feat  = hitung_indikator_teknikal(df)
            fitur_1d = buat_fitur_harian(ticker, df_feat, tanggal)
            dict_fitur[ticker]  = fitur_1d

            # Tentukan sektor
            from config import SECTORS
            sektor = "lainnya"
            kode   = ticker.replace(".JK", "")
            for nama, info in SECTORS.items():
                if kode in info["emiten"]:
                    sektor = nama
                    break
            dict_sektor[ticker] = sektor
        except Exception:
            continue

    df_ranking = ranking_saham_hari_ini(dict_fitur, models, dict_sektor)
    df_ranking["tanggal"] = str(tanggal)

    # Simpan ranking
    path_ranking = os.path.join(PATHS["log_dir"], f"ranking_{tanggal}.csv")
    os.makedirs(PATHS["log_dir"], exist_ok=True)
    df_ranking.to_csv(path_ranking, index=False)

    print(f"\n── TOP 10 SAHAM HARI INI ──")
    cols = ["rank","ticker","skor_total","sinyal","skor_sd",
            "skor_teknikal","skor_komoditas","proba_naik"]
    top10 = df_ranking[cols].head(10)
    print(top10.to_string(index=False))

    return df_ranking


# ════════════════════════════════════════════════════════════
#  FASE 3: CEK LAMPU & SIAPKAN ORDER (08:00)
# ════════════════════════════════════════════════════════════

def fase_cek_lampu(
    tanggal: date          = None,
    modal_total: float     = 100_000_000,
    ihsg_return: float     = 0.0,
    vix: float             = 15.0,
    foreign_sell_hari: int = 0,
    usd_idr_change: float  = 0.0,
    portfolio_return: float= 0.0,
) -> dict:
    """Cek kondisi pasar dan siapkan rekomendasi order."""
    if tanggal is None:
        tanggal = date.today()

    print(f"\n{'='*60}")
    print(f"FASE 3 · CEK LAMPU · {tanggal}")
    print(f"{'='*60}")

    # Cek eve libur panjang
    if cek_eve_libur_panjang(tanggal):
        print("⚠️  Besok libur panjang ≥ 3 hari → tidak buka posisi baru hari ini")
        return {"lampu": "KUNING", "alasan": ["Eve libur panjang"], "order": []}

    # Akurasi rolling
    akurasi_rolling = hitung_akurasi_rolling()

    # Tentukan lampu
    kondisi = cek_kondisi_pasar(
        ihsg_return_hari_ini   = ihsg_return,
        vix                    = vix,
        foreign_net_sell_hari  = foreign_sell_hari,
        akurasi_rolling_14d    = akurasi_rolling,
        usd_idr_change_7d      = usd_idr_change,
        portfolio_return_bulan = portfolio_return,
    )

    lampu = kondisi["lampu"]
    print(f"\n  LAMPU: {lampu}")
    print(f"  Alasan: {' · '.join(kondisi['alasan'])}")
    print(f"  Aksi  : {kondisi['aksi']}")

    if lampu == "MERAH":
        print("\n  🚫 STOP TRADING — tidak ada order hari ini")
        return {**kondisi, "order": []}

    # Muat ranking
    path_ranking = os.path.join(PATHS["log_dir"], f"ranking_{tanggal}.csv")
    if not os.path.exists(path_ranking):
        print("  ⚠️ Ranking belum ada · jalankan fase scoring dulu")
        return {**kondisi, "order": []}

    df_rank = pd.read_csv(path_ranking)
    df_beli = df_rank[df_rank["sinyal"] == "BELI KUAT"].head(
        5 if lampu == "HIJAU" else 2
    )

    # Siapkan order per saham
    orders = []
    for i, (_, baris) in enumerate(df_beli.iterrows()):
        posisi = hitung_posisi(
            modal_total    = modal_total,
            skor           = baris["skor_total"],
            lampu          = lampu,
            n_posisi_aktif = i,
        )
        if not posisi["layak"]:
            continue

        order = {
            "ticker"       : baris["ticker"],
            "skor"         : baris["skor_total"],
            "sinyal"       : baris["sinyal"],
            "alokasi_rp"   : posisi["alokasi_rp"],
            "pct_modal"    : posisi["pct_modal"],
            "stop_loss_pct": posisi["stop_loss_harga_pct"],
            "take_profit_pct": posisi["take_profit_harga_pct"],
            "risiko_rp"    : posisi["risiko_rp"],
            "target_rp"    : posisi["target_rp"],
        }
        orders.append(order)

    print(f"\n── ORDER SIAP HARI INI ({len(orders)} saham) ──")
    for o in orders:
        print(f"  BUY {o['ticker']:8s} | "
              f"Skor: {o['skor']:.0f} | "
              f"Alokasi: Rp {o['alokasi_rp']/1e6:.1f}jt | "
              f"TP: +{o['take_profit_pct']:.1%} | "
              f"SL: {o['stop_loss_pct']:.1%}")

    return {**kondisi, "order": orders}


# ════════════════════════════════════════════════════════════
#  FASE 4: EVALUASI HARIAN (15:30 — setelah BEI tutup)
# ════════════════════════════════════════════════════════════

def fase_evaluasi(tanggal: date = None, akurasi_hari_ini: float = None):
    """Evaluasi hasil trading hari ini dan update monitoring."""
    if tanggal is None:
        tanggal = date.today()

    print(f"\n{'='*60}")
    print(f"FASE 4 · EVALUASI HARIAN · {tanggal}")
    print(f"{'='*60}")

    # Catat akurasi
    if akurasi_hari_ini is not None:
        catat_akurasi_harian(tanggal, akurasi_hari_ini)
        print(f"[1/3] Akurasi hari ini: {akurasi_hari_ini:.2%}")

    akurasi_rolling = hitung_akurasi_rolling()
    print(f"      Akurasi rolling 14 hari: {akurasi_rolling:.2%}")

    # Statistik jurnal
    df_jurnal = baca_jurnal()
    if not df_jurnal.empty:
        stats = hitung_statistik_jurnal(df_jurnal)
        print(f"\n[2/3] Statistik trading keseluruhan:")
        print(f"      Total trade  : {stats['total_trade']}")
        print(f"      Win rate     : {stats['win_rate']:.2%}")
        print(f"      Avg profit   : {stats['avg_profit']:.2%}")
        print(f"      Profit factor: {stats['profit_factor']:.2f}")
        print(f"      Total profit : Rp {stats['total_profit_rp']/1e6:.2f}jt")

    # Cek apakah perlu retrain
    print(f"\n[3/3] Cek kebutuhan retrain...")
    tanggal_latih = date.today() - timedelta(days=7)  # placeholder
    retrain_info  = perlu_retrain(tanggal_latih)

    if retrain_info["perlu"]:
        print(f"  ⚠️  RETRAIN {retrain_info['jenis']}: {retrain_info['alasan']}")
        print(f"      Jalankan: python main_pipeline.py --fase retrain")
    else:
        print(f"  ✓  Model OK: {retrain_info['alasan']}")

    return {
        "akurasi_rolling": akurasi_rolling,
        "retrain_info"   : retrain_info,
    }


# ════════════════════════════════════════════════════════════
#  FASE TRAINING — LATIH MODEL DARI DATA HISTORIS
# ════════════════════════════════════════════════════════════

def fase_training(periode_tahun: int = None):
    """
    Latih model dari data historis.
    Jalankan sekali di awal, kemudian otomatis retrain bulanan.
    """
    if periode_tahun is None:
        periode_tahun = RETRAIN_CONFIG["window_latih_tahun"]

    print(f"\n{'='*60}")
    print(f"FASE TRAINING · Pakai data {periode_tahun} tahun terakhir")
    print(f"{'='*60}")

    # Muat semua data historis
    dict_ohlcv = {}
    if os.path.exists(PATHS["data_dir"]):
        for f in os.listdir(PATHS["data_dir"]):
            if f.endswith(".csv"):
                ticker = f.replace(".csv", "") + ".JK"
                path   = os.path.join(PATHS["data_dir"], f)
                try:
                    df = pd.read_csv(path, index_col=0, parse_dates=True)
                    df.columns = [c.lower() for c in df.columns]
                    # Filter hanya data N tahun terakhir
                    cutoff = pd.Timestamp.now() - pd.DateOffset(years=periode_tahun)
                    df = df[df.index >= cutoff]
                    if not df.empty:
                        dict_ohlcv[ticker] = df
                except Exception:
                    pass

    if not dict_ohlcv:
        print("⚠️  Tidak ada data · jalankan fase kumpul_data dulu")
        return

    print(f"[1/4] {len(dict_ohlcv)} saham dimuat")

    # Filter & buat dataset latih
    print("[2/4] Filter dan buat fitur...")
    dict_layak = filter_saham_layak(dict_ohlcv)
    for ticker, df in dict_layak.items():
        dict_layak[ticker] = hitung_indikator_teknikal(df)

    df_latih = buat_dataset_latih(dict_layak)
    if df_latih.empty:
        print("⚠️  Dataset kosong setelah preprocessing")
        return

    print(f"[3/4] Latih model per sektor...")
    models = latih_model_per_sektor(df_latih)

    print(f"[4/4] Simpan model...")
    simpan_model(models, "latest")
    versi = datetime.now().strftime("%Y%m%d")
    simpan_model(models, versi)

    print(f"\n✓ Training selesai · {len(models)} model sektor tersimpan")
    tampilkan_feature_importance(models, top_n=10)


# ════════════════════════════════════════════════════════════
#  BACKTESTING LENGKAP
# ════════════════════════════════════════════════════════════

def fase_backtesting():
    """Jalankan walk-forward backtesting lengkap."""
    print(f"\n{'='*60}")
    print(f"FASE BACKTESTING")
    print(f"{'='*60}")

    # Muat semua data
    dict_ohlcv = {}
    if os.path.exists(PATHS["data_dir"]):
        for f in os.listdir(PATHS["data_dir"]):
            if f.endswith(".csv"):
                ticker = f.replace(".csv", "") + ".JK"
                path   = os.path.join(PATHS["data_dir"], f)
                try:
                    df = pd.read_csv(path, index_col=0, parse_dates=True)
                    df.columns = [c.lower() for c in df.columns]
                    dict_ohlcv[ticker] = df
                except Exception:
                    pass

    dict_layak = filter_saham_layak(dict_ohlcv)
    for ticker, df in dict_layak.items():
        dict_layak[ticker] = hitung_indikator_teknikal(df)

    df_semua = buat_dataset_latih(dict_layak)
    if df_semua.empty:
        print("⚠️  Tidak ada data untuk backtesting")
        return

    # Walk-forward validation
    df_hasil = walk_forward_backtest(df_semua)

    if not df_hasil.empty:
        print(f"\n── Ringkasan Backtesting ──")
        print(f"  Putaran         : {len(df_hasil)}")
        print(f"  Akurasi rata-rata: {df_hasil['akurasi'].mean():.2%}")
        print(f"  Akurasi min     : {df_hasil['akurasi'].min():.2%}")
        print(f"  Akurasi max     : {df_hasil['akurasi'].max():.2%}")

        # Simpan hasil
        path = os.path.join(PATHS["log_dir"], "backtest_results.csv")
        os.makedirs(PATHS["log_dir"], exist_ok=True)
        df_hasil.to_csv(path, index=False)
        print(f"  Hasil disimpan  : {path}")


# ════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="IHSG Stock Predictor Pipeline")
    parser.add_argument(
        "--fase",
        choices=["kumpul_data","scoring","cek_lampu",
                 "evaluasi","training","backtesting","semua"],
        default="semua",
        help="Fase pipeline yang dijalankan"
    )
    parser.add_argument("--modal", type=float, default=100_000_000,
                        help="Modal total dalam rupiah")
    parser.add_argument("--vix", type=float, default=15.0)
    parser.add_argument("--ihsg_return", type=float, default=0.0)
    args = parser.parse_args()

    tanggal = date.today()

    if args.fase in ["kumpul_data", "semua"]:
        fase_kumpul_data(tanggal)

    if args.fase == "training":
        fase_training()

    if args.fase == "backtesting":
        fase_backtesting()

    if args.fase in ["scoring", "semua"]:
        fase_scoring(tanggal)

    if args.fase in ["cek_lampu", "semua"]:
        fase_cek_lampu(
            tanggal      = tanggal,
            modal_total  = args.modal,
            ihsg_return  = args.ihsg_return,
            vix          = args.vix,
        )

    if args.fase in ["evaluasi", "semua"]:
        fase_evaluasi(tanggal)


if __name__ == "__main__":
    main()
