#!/usr/bin/env python3
"""
fix_scoring_selektif.py
=======================
Patch scoring_swing.py agar HANYA beli saham yang model
sangat yakin akan naik. Yang ragu-ragu atau turun = SKIP.

Perubahan:
  1. Threshold naik: hanya top 10% proba (bukan 25%)
  2. Filter: skip kalau ret_1d < -1% (saham lagi turun)
  3. Filter: skip kalau volume turun (tidak ada minat beli)
  4. Sinyal hanya 2: BELI KUAT atau SKIP (tidak ada PANTAU)
"""

import os, pickle, warnings
import pandas as pd
import numpy as np
from datetime import datetime

warnings.filterwarnings("ignore")

TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def hitung_fitur_swing(df):
    close  = pd.to_numeric(df["close"],  errors="coerce")
    high   = pd.to_numeric(df.get("high",  close), errors="coerce")
    low    = pd.to_numeric(df.get("low",   close), errors="coerce")
    volume = pd.to_numeric(df.get("volume",
             pd.Series(1e6, index=df.index)), errors="coerce").fillna(1e6)
    ret = close.pct_change()
    f   = pd.DataFrame(index=df.index)

    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta).clip(lower=0).rolling(14).mean()
    rsi   = 100 - (100 / (1 + gain/loss.replace(0, np.nan)))
    f["rsi"]          = rsi
    f["rsi_oversold"] = (rsi < 30).astype(int)
    f["rsi_naik"]     = ((rsi > rsi.shift(1)) & (rsi < 50)).astype(int)
    f["rsi_cross50"]  = ((rsi > 50) & (rsi.shift(1) <= 50)).astype(int)

    ema12  = close.ewm(span=12).mean()
    ema26  = close.ewm(span=26).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    f["macd"]        = macd
    f["macd_hist"]   = macd - signal
    f["macd_cross"]  = ((macd > signal) & (macd.shift(1) <= signal.shift(1))).astype(int)
    f["macd_positif"]= (macd > 0).astype(int)

    sma20  = close.rolling(20).mean()
    std20  = close.rolling(20).std()
    bb_lo  = sma20 - 2*std20
    f["bb_pct"]    = (close - bb_lo) / (4*std20).replace(0, np.nan)
    f["below_bb"]  = (close < bb_lo).astype(int)
    f["bb_squeeze"]= (std20 < std20.rolling(20).mean()*0.8).astype(int)

    s5  = close.rolling(5).mean()
    s10 = close.rolling(10).mean()
    s50 = close.rolling(50).mean()
    f["close_vs_sma5"]  = close/s5.replace(0,np.nan)  - 1
    f["close_vs_sma10"] = close/s10.replace(0,np.nan) - 1
    f["close_vs_sma50"] = close/s50.replace(0,np.nan) - 1
    f["sma5_cross10"]   = ((s5>s10)&(s5.shift(1)<=s10.shift(1))).astype(int)
    f["golden_cross"]   = ((s5>s10)&(s10>s50)).astype(int)

    vma = volume.rolling(20).mean().replace(0, np.nan)
    f["vol_ratio"]   = volume / vma
    f["vol_spike"]   = (f["vol_ratio"] > 2).astype(int)
    f["vol_naik"]    = (volume > volume.shift(1)).astype(int)
    f["akumulasi"]   = ((close>close.shift(1))&(f["vol_ratio"]>1.5)).astype(int)
    f["akumulasi_2d"]= f["akumulasi"].rolling(2).sum()

    h20 = high.rolling(20).max()
    l20 = low.rolling(20).min()
    f["breakout_up"] = ((close>h20.shift(1))&(f["vol_ratio"]>1.5)).astype(int)
    f["near_high20"] = ((close/h20.replace(0,np.nan))>0.97).astype(int)
    f["range_pct"]   = (h20-l20)/l20.replace(0,np.nan)

    l14   = low.rolling(14).min()
    h14   = high.rolling(14).max()
    stoch = (close-l14)/(h14-l14).replace(0,np.nan)*100
    std   = stoch.rolling(3).mean()
    f["stoch_k"]       = stoch
    f["stoch_oversold"]= (stoch<20).astype(int)
    f["stoch_cross"]   = ((stoch>std)&(stoch.shift(1)<=std.shift(1))&(stoch<40)).astype(int)

    body   = abs(close - close.shift(1))
    shadow = high - low
    f["hammer"]       = ((shadow>body*2)&(close>close.shift(1))).astype(int)
    f["doji"]         = (body<shadow*0.1).astype(int)
    f["strong_candle"]= ((close-close.shift(1))>close.shift(1)*0.02).astype(int)

    for lag in [1,2,3,5]:
        f[f"ret_{lag}d"] = ret.shift(lag)
    f["ret_5d_sum"]    = ret.shift(1).rolling(5).sum()
    f["volatility_5d"] = ret.rolling(5).std()
    f["volatility_10d"]= ret.rolling(10).std()

    tp  = (high+low+close)/3
    mf  = tp*volume
    pmf = mf.where(tp>tp.shift(1),0).rolling(14).sum()
    nmf = mf.where(tp<tp.shift(1),0).rolling(14).sum()
    mfi = 100-(100/(1+pmf/nmf.replace(0,np.nan)))
    f["mfi"]         = mfi
    f["mfi_oversold"]= (mfi<20).astype(int)

    f["hari"]  = df.index.dayofweek
    f["bulan"] = df.index.month
    f["senin"] = (df.index.dayofweek==0).astype(int)
    f["jumat"] = (df.index.dayofweek==4).astype(int)
    return f


def scoring_selektif():
    tanggal = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"SWING SCANNER SELEKTIF — {tanggal}")
    print(f"Mode: HANYA BELI yang sangat yakin naik")
    print(f"{'='*60}")

    # Load model
    try:
        with open("models/model_swing.pkl", "rb") as f:
            rb = pickle.load(f)
        model      = rb["pipeline"]
        fitur_list = rb["fitur"]
        cv_acc     = rb.get("cv_accuracy", 0)
        print(f"  Model: {rb['nama_model']} | CV: {cv_acc*100:.1f}%")
    except Exception as e:
        print(f"  ERROR load model: {e}")
        return

    # Scan semua saham
    semua_hasil = []
    folder_list = ["data/idx500", "data"]
    scanned     = set()

    for folder in folder_list:
        if not os.path.exists(folder):
            continue
        for fname in os.listdir(folder):
            if not fname.endswith(".csv"):
                continue
            kode = fname.replace(".csv", "")
            if kode in scanned or kode.startswith("KOMODITAS"):
                continue
            scanned.add(kode)

            try:
                df = pd.read_csv(os.path.join(folder, fname))
                df.columns = [c.lower() for c in df.columns]
                if "date" not in df.columns: continue
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
                for col in ["close","high","low","volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["close"])
                if len(df) < 100: continue

                harga = float(df["close"].iloc[-1])
                if harga < 50: continue

                # ── FILTER 1: Skip kalau saham lagi turun hari ini ──
                ret_1d = float(df["close"].pct_change().iloc[-1])
                if ret_1d < -0.01:  # turun lebih dari -1%
                    continue

                # ── FILTER 2: Skip kalau volume turun ────────────────
                if "volume" in df.columns:
                    vol_now  = float(df["volume"].iloc[-1])
                    vol_ma   = float(df["volume"].rolling(20).mean().iloc[-1])
                    vol_ratio= vol_now / vol_ma if vol_ma > 0 else 1
                    if vol_ratio < 0.7:  # volume < 70% rata-rata
                        continue

                # Hitung fitur & prediksi
                X = hitung_fitur_swing(df).fillna(0)
                for col in fitur_list:
                    if col not in X.columns:
                        X[col] = 0
                X_last = X[fitur_list].iloc[[-1]]
                proba  = float(model.predict_proba(X_last)[0][1])

                rsi_now  = float(X["rsi"].iloc[-1])        if "rsi"       in X.columns else 50
                vol_r    = float(X["vol_ratio"].iloc[-1])  if "vol_ratio" in X.columns else 1
                macd_h   = float(X["macd_hist"].iloc[-1])  if "macd_hist" in X.columns else 0

                semua_hasil.append({
                    "ticker" : kode,
                    "harga"  : harga,
                    "proba"  : round(proba, 3),
                    "ret_1d" : round(ret_1d*100, 2),
                    "rsi"    : round(rsi_now, 1),
                    "vol_r"  : round(vol_r, 2),
                    "macd_h" : round(macd_h, 4),
                })
            except:
                continue

    if not semua_hasil:
        print("  Tidak ada saham yang lolos filter!")
        return

    df_hasil = pd.DataFrame(semua_hasil).sort_values("proba", ascending=False)

    # ── FILTER 3: Hanya top 10% proba ────────────────────────
    threshold_proba = df_hasil["proba"].quantile(0.90)
    df_beli = df_hasil[df_hasil["proba"] >= threshold_proba].copy()

    # Simpan
    os.makedirs("logs", exist_ok=True)
    df_beli.to_csv(f"logs/swing_selektif_{tanggal}.csv", index=False)

    # Print hasil
    print(f"\n  Total discan       : {len(scanned)} saham")
    print(f"  Lolos filter turun : {len(semua_hasil)} saham")
    print(f"  Threshold proba    : {threshold_proba:.3f}")
    print(f"  Sinyal BELI KUAT   : {len(df_beli)} saham")

    print(f"\n{'─'*65}")
    print(f"🎯 SINYAL BELI KUAT — yakin naik >= 1.5% dalam 1-3 hari:")
    print(f"{'─'*65}")
    print(f"{'Ticker':<8} {'Harga':>10} {'Proba':>7} {'Ret1d':>7} {'RSI':>6} {'VolR':>6}")
    print("─"*65)

    for _, r in df_beli.head(15).iterrows():
        print(f"{r['ticker']:<8} {r['harga']:>10,.0f} {r['proba']:>7.3f} "
              f"{r['ret_1d']:>+7.2f}% {r['rsi']:>6.1f} {r['vol_r']:>6.2f}")

    if len(df_beli) == 0:
        print("  Hari ini tidak ada saham yang memenuhi kriteria ketat.")
        print("  SKIP semua — modal aman! 💰")

    # Kirim Telegram
    if TOKEN and CHAT_ID:
        import urllib.request, urllib.parse, ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE

        baris = [
            f"🎯 SWING SELEKTIF — {tanggal}",
            f"Scan: {len(scanned)} saham | CV: {cv_acc*100:.1f}%",
            f"Filter: tidak turun + volume aktif + top 10% proba",
            "",
        ]

        if len(df_beli) > 0:
            baris.append(f"✅ BELI KUAT ({len(df_beli)} saham):")
            for _, r in df_beli.head(8).iterrows():
                baris.append(
                    f"  {r['ticker']:6} | Rp{r['harga']:,.0f} | "
                    f"prob:{r['proba']:.2f} | RSI:{r['rsi']:.0f}"
                )
        else:
            baris.append("⏭️ SKIP semua hari ini")
            baris.append("Tidak ada saham yang memenuhi kriteria ketat")
            baris.append("Modal aman, tunggu peluang lebih baik 💰")

        pesan = "\n".join(baris)
        data  = urllib.parse.urlencode({
            "chat_id"   : CHAT_ID,
            "text"      : pesan,
            "parse_mode": "HTML"
        }).encode()

        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data)
            urllib.request.urlopen(req, timeout=15, context=ctx)
            print("\n  ✓ Terkirim ke Telegram")
        except Exception as e:
            print(f"\n  ✗ Telegram error: {e}")

    return df_beli


if __name__ == "__main__":
    scoring_selektif()
