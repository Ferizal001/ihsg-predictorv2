# ============================================================
#  model.py — Training, Scoring, Backtesting & Walk-Forward
# ============================================================

import pandas as pd
import numpy as np
import os
import json
import pickle
from datetime import date, datetime, timedelta
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report
from sklearn.pipeline import Pipeline

from config import SECTORS, RETRAIN_CONFIG, PATHS, TRADING_CONFIG
from feature_engineering import SEMUA_FITUR, FITUR_SUPPLY_DEMAND, FITUR_TEKNIKAL


# ════════════════════════════════════════════════════════════
#  MODEL PER SEKTOR (bukan 1 model untuk semua)
# ════════════════════════════════════════════════════════════

def buat_model_xgboost() -> Pipeline:
    """
    Buat pipeline model XGBoost (GradientBoosting sebagai pengganti).
    Gunakan xgboost.XGBClassifier jika library tersedia.
    """
    try:
        from xgboost import XGBClassifier
        clf = XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            eval_metric="logloss",
            verbosity=0,
        )
    except ImportError:
        # Fallback ke GradientBoosting sklearn
        clf = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )

    return Pipeline([
        ("scaler", StandardScaler()),
        ("model",  clf),
    ])


def latih_model_per_sektor(df_latih: pd.DataFrame) -> dict:
    """
    Latih 1 model terpisah per sektor.
    df_latih : DataFrame dengan kolom 'sektor', 'label', dan semua fitur
    return   : dict { nama_sektor: trained_pipeline }
    """
    models = {}

    for sektor in df_latih["sektor"].unique():
        df_s = df_latih[df_latih["sektor"] == sektor].copy()

        # Pastikan fitur tersedia
        fitur_ada = [f for f in SEMUA_FITUR if f in df_s.columns]
        if len(df_s) < 100 or len(fitur_ada) < 10:
            print(f"[Training] Sektor {sektor}: data kurang, skip")
            continue

        X = df_s[fitur_ada].values
        y = df_s["label"].values

        # Split 80/20 dengan urutan waktu
        split     = int(len(X) * 0.8)
        X_tr, X_te = X[:split], X[split:]
        y_tr, y_te = y[:split], y[split:]

        model = buat_model_xgboost()
        model.fit(X_tr, y_tr)

        acc_tr = accuracy_score(y_tr, model.predict(X_tr))
        acc_te = accuracy_score(y_te, model.predict(X_te))
        gap    = acc_tr - acc_te

        print(f"[Training] Sektor {sektor:12s} | "
              f"n={len(df_s):5,} | "
              f"Train acc={acc_tr:.2%} | "
              f"Test acc={acc_te:.2%} | "
              f"Gap={gap:.2%} {'⚠️ overfit' if gap > 0.1 else '✓'}")

        models[sektor] = {
            "pipeline"   : model,
            "fitur"      : fitur_ada,
            "acc_test"   : acc_te,
            "trained_at" : str(datetime.now()),
            "n_samples"  : len(df_s),
        }

    return models


def simpan_model(models: dict, versi: str = "latest"):
    """Simpan semua model ke disk."""
    os.makedirs(PATHS["model_dir"], exist_ok=True)
    path = os.path.join(PATHS["model_dir"], f"models_{versi}.pkl")
    with open(path, "wb") as f:
        pickle.dump(models, f)
    print(f"[Model] Disimpan: {path}")


def muat_model(versi: str = "latest") -> dict:
    """Muat model dari disk."""
    path = os.path.join(PATHS["model_dir"], f"models_{versi}.pkl")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Model tidak ditemukan: {path}")
    with open(path, "rb") as f:
        return pickle.load(f)


# ════════════════════════════════════════════════════════════
#  FEATURE IMPORTANCE — TEMUKAN BOBOT YANG DIPELAJARI
# ════════════════════════════════════════════════════════════

def tampilkan_feature_importance(models: dict, top_n: int = 15):
    """Tampilkan fitur terpenting per sektor."""
    for sektor, info in models.items():
        pipeline = info["pipeline"]
        fitur    = info["fitur"]
        try:
            estimator = pipeline.named_steps["model"]
            importance = estimator.feature_importances_
            df_imp = pd.DataFrame({
                "fitur"     : fitur,
                "importance": importance,
            }).sort_values("importance", ascending=False).head(top_n)

            print(f"\n── Feature Importance: {sektor} ──")
            for _, row in df_imp.iterrows():
                bar = "█" * int(row["importance"] * 100)
                print(f"  {row['fitur']:25s} {bar} {row['importance']:.3f}")
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
#  SCORING HARIAN — HITUNG SKOR 0-100 PER SAHAM
# ════════════════════════════════════════════════════════════

def hitung_skor_saham(fitur_dict: dict, models: dict,
                       sektor: str = "lainnya") -> dict:
    """
    Hitung skor 0-100 untuk 1 saham berdasarkan model per sektor.
    fitur_dict : dict fitur dari buat_fitur_harian()
    models     : dict model yang sudah dilatih
    return     : dict skor per komponen dan skor total
    """
    # Ambil model sektor yang sesuai, fallback ke sektor lainnya
    model_key = sektor if sektor in models else list(models.keys())[0]
    info      = models[model_key]
    pipeline  = info["pipeline"]
    fitur     = info["fitur"]

    # Susun fitur sebagai array
    X = np.array([[fitur_dict.get(f, 0.0) for f in fitur]])

    # Probabilitas naik dari model
    try:
        proba_naik = float(pipeline.predict_proba(X)[0][1])
    except Exception:
        proba_naik = 0.5

    # ── Skor per komponen (0-100) ─────────────────────────
    # Supply/Demand
    volume_ratio = fitur_dict.get("volume_ratio", 1.0)
    akumulasi    = fitur_dict.get("akumulasi", 0)
    is_breakout  = fitur_dict.get("is_breakout", 0)
    skor_sd      = min(100, (
        (min(volume_ratio, 5) / 5 * 40) +
        (akumulasi * 35) +
        (is_breakout * 25)
    ))

    # Teknikal
    rsi          = fitur_dict.get("rsi", 50)
    macd_bull    = fitur_dict.get("macd_bullish", 0)
    above_ma20   = fitur_dict.get("above_ma20", 0)
    rsi_rev      = fitur_dict.get("rsi_reversal", 0)
    skor_teknikal = min(100, (
        (max(0, 70 - abs(rsi - 50)) / 70 * 30) +
        (macd_bull * 30) +
        (above_ma20 * 25) +
        (rsi_rev * 15)
    ))

    # Sentimen
    skor_sentimen_raw = fitur_dict.get("skor_sentimen", 0.0)
    skor_sentimen = min(100, max(0, (skor_sentimen_raw + 1) / 2 * 100))

    # Kalender
    is_ramadan    = fitur_dict.get("is_ramadan", 0)
    days_after_lb = fitur_dict.get("days_after_lebaran", 0)
    is_januari    = fitur_dict.get("is_januari", 0)
    is_win_dress  = fitur_dict.get("is_window_dressing", 0)
    skor_kalender = min(100, (
        (min(days_after_lb, 7) / 7 * 40) +  # post-lebaran bonus
        (is_januari * 30) +
        (is_win_dress * 20) -
        (is_ramadan * 20)                    # ramadan = lebih rendah
    ))
    skor_kalender = max(0, skor_kalender)

    # Komoditas (sesuai sektor)
    coal_pct   = fitur_dict.get("coal_pct",   0.0)
    nickel_pct = fitur_dict.get("nickel_pct", 0.0)
    cpo_pct    = fitur_dict.get("cpo_pct",    0.0)
    oil_pct    = fitur_dict.get("oil_pct",    0.0)

    if sektor in ["tambang", "energi"]:
        skor_komoditas = min(100, max(0, 50 + (coal_pct + nickel_pct) * 500))
    elif sektor == "agribisnis":
        skor_komoditas = min(100, max(0, 50 + cpo_pct * 500))
    else:
        # Sektor lain: minyak naik = negatif (inflasi)
        skor_komoditas = min(100, max(0, 50 - oil_pct * 300))

    # ── Skor total (weighted average) ────────────────────
    skor_total = (
        skor_sd        * 0.35 +
        skor_teknikal  * 0.25 +
        skor_komoditas * 0.20 +
        skor_sentimen  * 0.12 +
        skor_kalender  * 0.08
    )

    # Bobot dengan probabilitas model (ensemble sederhana)
    skor_final = (skor_total * 0.6) + (proba_naik * 100 * 0.4)
    skor_final = min(100, max(0, round(skor_final, 1)))

    return {
        "skor_total"      : skor_final,
        "skor_sd"         : round(skor_sd, 1),
        "skor_teknikal"   : round(skor_teknikal, 1),
        "skor_komoditas"  : round(skor_komoditas, 1),
        "skor_sentimen"   : round(skor_sentimen, 1),
        "skor_kalender"   : round(skor_kalender, 1),
        "proba_naik"      : round(proba_naik, 3),
        "sinyal"          : (
            "BELI KUAT" if skor_final >= 75 else
            "PANTAU"    if skor_final >= 55 else
            "SKIP"
        ),
    }


def ranking_saham_hari_ini(dict_fitur: dict, models: dict,
                            dict_sektor: dict) -> pd.DataFrame:
    """
    Hitung skor semua saham dan urutkan dari terbaik.
    dict_fitur  : { ticker: dict fitur }
    models      : dict model per sektor
    dict_sektor : { ticker: nama_sektor }
    return      : DataFrame ranking saham
    """
    hasil = []
    for ticker, fitur in dict_fitur.items():
        sektor = dict_sektor.get(ticker, "lainnya")
        skor   = hitung_skor_saham(fitur, models, sektor)
        skor["ticker"] = ticker
        skor["sektor"] = sektor
        hasil.append(skor)

    df_rank = pd.DataFrame(hasil)
    df_rank = df_rank.sort_values("skor_total", ascending=False).reset_index(drop=True)
    df_rank["rank"] = df_rank.index + 1
    return df_rank


# ════════════════════════════════════════════════════════════
#  WALK-FORWARD VALIDATION & BACKTESTING
# ════════════════════════════════════════════════════════════

def walk_forward_backtest(df_semua: pd.DataFrame,
                           window_latih_bulan: int = 24,
                           window_uji_bulan: int = 1) -> pd.DataFrame:
    """
    Walk-forward backtesting:
    - Latih di bulan 1..24 → uji bulan 25
    - Latih di bulan 1..25 → uji bulan 26
    - dst...
    """
    df_semua = df_semua.copy()
    df_semua.index = pd.to_datetime(df_semua.index)
    df_semua = df_semua.sort_index()

    tanggal_unik = df_semua.index.to_period("M").unique()
    hasil_semua  = []

    start_uji = window_latih_bulan
    if start_uji >= len(tanggal_unik):
        print("[Backtest] Data terlalu sedikit untuk walk-forward")
        return pd.DataFrame()

    print(f"\n[Backtest] Mulai walk-forward: "
          f"{len(tanggal_unik) - start_uji} putaran")

    for i in range(start_uji, len(tanggal_unik)):
        periode_latih = tanggal_unik[:i]
        periode_uji   = tanggal_unik[i]

        mask_tr = df_semua.index.to_period("M").isin(periode_latih)
        mask_te = df_semua.index.to_period("M") == periode_uji

        df_tr = df_semua[mask_tr]
        df_te = df_semua[mask_te]

        if len(df_tr) < 200 or len(df_te) < 10:
            continue

        # Latih model
        try:
            models = latih_model_per_sektor(df_tr)
        except Exception as e:
            print(f"[Backtest] Error training bulan {periode_uji}: {e}")
            continue

        # Uji di data bulan berikutnya
        for sektor in df_te["sektor"].unique():
            df_s    = df_te[df_te["sektor"] == sektor]
            model_k = sektor if sektor in models else list(models.keys())[0]
            info    = models[model_k]
            fitur   = info["fitur"]

            fitur_ada = [f for f in fitur if f in df_s.columns]
            if not fitur_ada:
                continue

            X_te = df_s[fitur_ada].values
            y_te = df_s["label"].values

            try:
                pipeline = info["pipeline"]
                y_pred   = pipeline.predict(X_te)
                acc      = accuracy_score(y_te, y_pred)
            except Exception:
                continue

            hasil_semua.append({
                "periode"  : str(periode_uji),
                "sektor"   : sektor,
                "akurasi"  : round(acc, 4),
                "n_sample" : len(df_s),
            })

        periode_str = str(periode_uji)
        bulan_hasil = [h for h in hasil_semua if h["periode"] == periode_str]
        if bulan_hasil:
            acc_rata = np.mean([h["akurasi"] for h in bulan_hasil])
            print(f"  Bulan {periode_str} | akurasi rata-rata: {acc_rata:.2%}")

    df_hasil = pd.DataFrame(hasil_semua)
    if not df_hasil.empty:
        print(f"\n[Backtest] Akurasi rata-rata keseluruhan: "
              f"{df_hasil['akurasi'].mean():.2%}")
    return df_hasil


def simulasi_profit(df_ranking_harian: pd.DataFrame,
                     df_harga: dict,
                     modal_awal: float = 100_000_000) -> dict:
    """
    Simulasi profit/loss dari ranking harian.
    Asumsi: beli di harga open, jual di harga close atau saat TP/SL tercapai.
    """
    modal    = modal_awal
    jurnal   = []
    tp_pct   = TRADING_CONFIG["take_profit_pct"]
    sl_pct   = abs(TRADING_CONFIG["stop_loss_pct"])
    max_pos  = TRADING_CONFIG["max_posisi"]
    kas_min  = TRADING_CONFIG["min_kas_pct"]
    biaya    = TRADING_CONFIG["biaya_transaksi"]

    for _, baris in df_ranking_harian.iterrows():
        ticker     = baris["ticker"]
        tanggal    = baris["tanggal"]
        skor       = baris["skor_total"]

        if skor < 55:
            continue

        df_t = df_harga.get(ticker, pd.DataFrame())
        if df_t.empty:
            continue

        # Cari harga pada tanggal tersebut
        try:
            idx    = df_t.index.get_loc(tanggal)
            open_h = float(df_t["open"].iloc[idx])
            close_h= float(df_t["close"].iloc[idx])
        except Exception:
            continue

        # Hitung alokasi modal (maks 20% per saham)
        modal_tersedia = modal * (1 - kas_min)
        alokasi        = min(modal_tersedia / max_pos, modal * 0.20)

        # Simulasi: apakah TP atau SL yang tercapai?
        return_pct = (close_h / open_h) - 1
        if return_pct >= tp_pct:
            hasil_pct = tp_pct - biaya
            status    = "TP"
        elif return_pct <= -sl_pct:
            hasil_pct = -sl_pct - biaya
            status    = "SL"
        else:
            hasil_pct = return_pct - biaya
            status    = "HOLD_CLOSE"

        profit  = alokasi * hasil_pct
        modal  += profit

        jurnal.append({
            "tanggal"   : tanggal,
            "ticker"    : ticker,
            "skor"      : skor,
            "open"      : open_h,
            "close"     : close_h,
            "return_pct": round(return_pct, 4),
            "hasil_pct" : round(hasil_pct, 4),
            "profit_rp" : round(profit, 0),
            "modal"     : round(modal, 0),
            "status"    : status,
        })

    df_jurnal = pd.DataFrame(jurnal)
    if df_jurnal.empty:
        return {"modal_akhir": modal, "return_total": 0, "jurnal": df_jurnal}

    win_rate    = (df_jurnal["hasil_pct"] > 0).mean()
    return_total= (modal - modal_awal) / modal_awal
    max_dd      = _hitung_max_drawdown(df_jurnal["modal"].values)

    print(f"\n[Backtest P&L]")
    print(f"  Modal awal    : Rp {modal_awal/1e6:.1f} jt")
    print(f"  Modal akhir   : Rp {modal/1e6:.1f} jt")
    print(f"  Total return  : {return_total:.2%}")
    print(f"  Win rate      : {win_rate:.2%}")
    print(f"  Max drawdown  : {max_dd:.2%}")
    print(f"  Total trade   : {len(df_jurnal)}")

    return {
        "modal_akhir" : modal,
        "return_total": return_total,
        "win_rate"    : win_rate,
        "max_drawdown": max_dd,
        "jurnal"      : df_jurnal,
    }


def _hitung_max_drawdown(nilai_portfolio: np.ndarray) -> float:
    """Hitung maximum drawdown dari array nilai portfolio."""
    if len(nilai_portfolio) == 0:
        return 0.0
    peak   = np.maximum.accumulate(nilai_portfolio)
    dd     = (nilai_portfolio - peak) / peak
    return float(dd.min())
