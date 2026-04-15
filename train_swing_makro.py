#!/usr/bin/env python3
"""
train_swing_makro.py
====================
Retrain model swing 1-3 hari dengan tambahan 17 fitur makro global:
- STI Singapore, Nikkei, Sensex, KOSPI, FTSE100
- SP500, Dow Jones, Nasdaq, MSCI EM, MSCI World
- VIX, ASX200, Hang Seng, Emas
- Oil/Gas ratio, Fear/Greed proxy, Beras

Fitur makro ditambahkan sebagai:
1. Return harian (pct_change)
2. Return lag-1 (kemarin) → prediktif
3. Z-score 20 hari → posisi relatif
"""

import os, pickle, warnings
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.metrics import accuracy_score

warnings.filterwarnings("ignore")
os.makedirs("models", exist_ok=True)
os.makedirs("logs", exist_ok=True)

print("="*65)
print("TRAINING MODEL SWING + MAKRO GLOBAL")
print("Target: naik >= 1.5% dalam 1-3 hari")
print("Tambahan: 17 fitur makro global")
print("="*65)

# ── LOAD DATA MAKRO ───────────────────────────────────────────
MAKRO_LAYAK = [
    "sti_singapore", "nikkei", "sensex", "kospi", "ftse100",
    "emas", "msci_world", "sp500", "nasdaq", "dow_jones",
    "oil_gas_ratio", "fear_greed_proxy", "vix", "asx200",
    "msci_em", "hang_seng", "beras"
]

print("\n[1/5] Load data makro global...")
makro_data = {}
for nama in MAKRO_LAYAK:
    path = f"data/makro/{nama}.csv"
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            makro_data[nama] = df["close"]
            print(f"  ✓ {nama:<25} {len(df)} hari")
        except Exception as e:
            print(f"  ✗ {nama}: {e}")
    else:
        print(f"  ✗ {nama}: file tidak ada")

if makro_data:
    df_makro = pd.DataFrame(makro_data)
    df_makro.index = pd.to_datetime(df_makro.index).normalize()
    print(f"\n  Total makro: {len(df_makro.columns)} variabel | {len(df_makro)} hari")
else:
    print("  WARNING: Tidak ada data makro! Jalankan download_makro_global.py dulu")
    df_makro = pd.DataFrame()

# ── FUNGSI FITUR TEKNIKAL ─────────────────────────────────────
def hitung_fitur_teknikal(df):
    close  = pd.to_numeric(df["close"],  errors="coerce")
    high   = pd.to_numeric(df.get("high",  close), errors="coerce")
    low    = pd.to_numeric(df.get("low",   close), errors="coerce")
    volume = pd.to_numeric(df.get("volume",
             pd.Series(1e6, index=df.index)), errors="coerce").fillna(1e6)
    ret = close.pct_change()
    f   = pd.DataFrame(index=df.index)

    # RSI
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta).clip(lower=0).rolling(14).mean()
    rsi   = 100 - (100 / (1 + gain/loss.replace(0, np.nan)))
    f["rsi"]          = rsi
    f["rsi_oversold"] = (rsi < 30).astype(int)
    f["rsi_naik"]     = ((rsi > rsi.shift(1)) & (rsi < 50)).astype(int)
    f["rsi_cross50"]  = ((rsi > 50) & (rsi.shift(1) <= 50)).astype(int)

    # MACD
    ema12  = close.ewm(span=12).mean()
    ema26  = close.ewm(span=26).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    f["macd"]        = macd
    f["macd_hist"]   = macd - signal
    f["macd_cross"]  = ((macd > signal) & (macd.shift(1) <= signal.shift(1))).astype(int)
    f["macd_positif"]= (macd > 0).astype(int)

    # Bollinger
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_lo = sma20 - 2*std20
    f["bb_pct"]    = (close - bb_lo) / (4*std20).replace(0, np.nan)
    f["below_bb"]  = (close < bb_lo).astype(int)
    f["bb_squeeze"]= (std20 < std20.rolling(20).mean()*0.8).astype(int)

    # Moving Average
    s5  = close.rolling(5).mean()
    s10 = close.rolling(10).mean()
    s50 = close.rolling(50).mean()
    f["close_vs_sma5"]  = close/s5.replace(0, np.nan)  - 1
    f["close_vs_sma10"] = close/s10.replace(0, np.nan) - 1
    f["close_vs_sma50"] = close/s50.replace(0, np.nan) - 1
    f["sma5_cross10"]   = ((s5>s10)&(s5.shift(1)<=s10.shift(1))).astype(int)
    f["golden_cross"]   = ((s5>s10)&(s10>s50)).astype(int)

    # Volume
    vma = volume.rolling(20).mean().replace(0, np.nan)
    f["vol_ratio"]   = volume / vma
    f["vol_spike"]   = (f["vol_ratio"] > 2).astype(int)
    f["vol_naik"]    = (volume > volume.shift(1)).astype(int)
    f["akumulasi"]   = ((close>close.shift(1))&(f["vol_ratio"]>1.5)).astype(int)
    f["akumulasi_2d"]= f["akumulasi"].rolling(2).sum()

    # Breakout
    h20 = high.rolling(20).max()
    l20 = low.rolling(20).min()
    f["breakout_up"] = ((close>h20.shift(1))&(f["vol_ratio"]>1.5)).astype(int)
    f["near_high20"] = ((close/h20.replace(0, np.nan))>0.97).astype(int)
    f["range_pct"]   = (h20-l20)/l20.replace(0, np.nan)

    # Stochastic
    l14   = low.rolling(14).min()
    h14   = high.rolling(14).max()
    stoch = (close-l14)/(h14-l14).replace(0, np.nan)*100
    std   = stoch.rolling(3).mean()
    f["stoch_k"]       = stoch
    f["stoch_oversold"]= (stoch<20).astype(int)
    f["stoch_cross"]   = ((stoch>std)&(stoch.shift(1)<=std.shift(1))&(stoch<40)).astype(int)

    # Candle
    body   = abs(close - close.shift(1))
    shadow = high - low
    f["hammer"]       = ((shadow>body*2)&(close>close.shift(1))).astype(int)
    f["doji"]         = (body<shadow*0.1).astype(int)
    f["strong_candle"]= ((close-close.shift(1))>close.shift(1)*0.02).astype(int)

    # Return lags
    for lag in [1,2,3,5]:
        f[f"ret_{lag}d"] = ret.shift(lag)
    f["ret_5d_sum"]    = ret.shift(1).rolling(5).sum()
    f["volatility_5d"] = ret.rolling(5).std()
    f["volatility_10d"]= ret.rolling(10).std()

    # MFI
    tp  = (high+low+close)/3
    mf  = tp*volume
    pmf = mf.where(tp>tp.shift(1), 0).rolling(14).sum()
    nmf = mf.where(tp<tp.shift(1), 0).rolling(14).sum()
    mfi = 100-(100/(1+pmf/nmf.replace(0, np.nan)))
    f["mfi"]         = mfi
    f["mfi_oversold"]= (mfi<20).astype(int)

    # Kalender
    f["hari"]  = df.index.dayofweek
    f["bulan"] = df.index.month
    f["senin"] = (df.index.dayofweek==0).astype(int)
    f["jumat"] = (df.index.dayofweek==4).astype(int)

    return f


def tambah_fitur_makro(f_teknikal, df_makro):
    """Tambahkan fitur makro global ke dataframe fitur teknikal."""
    if df_makro.empty:
        return f_teknikal

    f = f_teknikal.copy()
    idx = pd.to_datetime(f.index).normalize()
    f.index = idx

    for nama in df_makro.columns:
        seri = df_makro[nama].dropna()
        ret  = seri.pct_change()

        # Return hari ini
        r_today = ret.reindex(idx, method="ffill")
        f[f"makro_{nama}_ret"]  = r_today.values

        # Return kemarin (lag-1) — PREDIKTIF
        r_lag = ret.shift(1).reindex(idx, method="ffill")
        f[f"makro_{nama}_lag1"] = r_lag.values

        # Z-score 20 hari (posisi relatif)
        zscore = ((seri - seri.rolling(20).mean()) /
                  seri.rolling(20).std().replace(0, np.nan))
        z_today = zscore.reindex(idx, method="ffill")
        f[f"makro_{nama}_z20"]  = z_today.values

    return f


# ── LOAD DATA SAHAM ───────────────────────────────────────────
print("\n[2/5] Load data saham...")
X_all, y_all, meta = [], [], []

for folder in ["data/idx500", "data"]:
    if not os.path.exists(folder):
        continue
    files = [f for f in os.listdir(folder) if f.endswith(".csv")]
    for fname in files:
        kode = fname.replace(".csv", "")
        if any(kode == m["kode"] for m in meta):
            continue
        path = os.path.join(folder, fname)
        try:
            df = pd.read_csv(path)
            df.columns = [c.lower() for c in df.columns]
            if "date" not in df.columns: continue
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            df.index = pd.to_datetime(df.index).normalize()

            for col in ["close","high","low","volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            df = df[df["close"] > 50]
            if len(df) < 150: continue

            # Target
            close = df["close"]
            ret_max = pd.DataFrame({
                "r1": close.shift(-1)/close - 1,
                "r2": close.shift(-2)/close - 1,
                "r3": close.shift(-3)/close - 1,
            }).max(axis=1)
            target = (ret_max >= 0.015).astype(int)

            # Fitur teknikal
            X_tek = hitung_fitur_teknikal(df)

            # Tambah fitur makro
            X_full = tambah_fitur_makro(X_tek, df_makro)

            df_g = X_full.copy()
            df_g["target"] = target

            valid = (df_g["target"].notna() &
                     (df_g.isna().sum(axis=1) < df_g.shape[1]*0.5))
            df_g = df_g[valid].fillna(0)

            if len(df_g) < 100: continue

            X_all.append(df_g.drop("target", axis=1))
            y_all.append(df_g["target"])
            meta.append({"kode": kode, "n": len(df_g)})

        except Exception as e:
            continue

print(f"  Total saham : {len(meta)}")
print(f"  Total baris : {sum(m['n'] for m in meta):,}")

if not X_all:
    print("ERROR: Tidak ada data!")
    exit()

# ── TRAINING ──────────────────────────────────────────────────
print("\n[3/5] Gabungkan dataset...")
X_combined = pd.concat(X_all).fillna(0)
y_combined = pd.concat(y_all)
X_combined = X_combined.loc[:, X_combined.nunique() > 1]
fitur_list = X_combined.columns.tolist()

n_teknikal = sum(1 for f in fitur_list if not f.startswith("makro_"))
n_makro    = sum(1 for f in fitur_list if f.startswith("makro_"))

print(f"  Dataset    : {len(X_combined):,} baris | {len(fitur_list)} fitur")
print(f"  → Teknikal : {n_teknikal} fitur")
print(f"  → Makro    : {n_makro} fitur")
print(f"  Positif    : {y_combined.mean()*100:.1f}%")

print("\n[4/5] Training model...")

pipe_gb = Pipeline([
    ("sc", StandardScaler()),
    ("gb", GradientBoostingClassifier(
        n_estimators=200, max_depth=5,
        learning_rate=0.05, subsample=0.8,
        random_state=42,
    ))
])
pipe_rf = Pipeline([
    ("sc", StandardScaler()),
    ("rf", RandomForestClassifier(
        n_estimators=300, max_depth=10,
        min_samples_leaf=8, max_features="sqrt",
        random_state=42, n_jobs=-1, class_weight="balanced",
    ))
])

tscv = TimeSeriesSplit(n_splits=5)

print("  GradientBoosting...")
cv_gb = cross_val_score(pipe_gb, X_combined, y_combined,
                        cv=tscv, scoring="accuracy", n_jobs=-1)
print(f"    CV: {cv_gb.mean()*100:.2f}% ± {cv_gb.std()*100:.2f}%")

print("  RandomForest...")
cv_rf = cross_val_score(pipe_rf, X_combined, y_combined,
                        cv=tscv, scoring="accuracy", n_jobs=-1)
print(f"    CV: {cv_rf.mean()*100:.2f}% ± {cv_rf.std()*100:.2f}%")

if cv_gb.mean() >= cv_rf.mean():
    model_final = pipe_gb; nama = "GradientBoosting"; cv = cv_gb.mean()
else:
    model_final = pipe_rf; nama = "RandomForest";     cv = cv_rf.mean()

print(f"\n  Model terpilih: {nama} (CV={cv*100:.2f}%)")
model_final.fit(X_combined, y_combined)
train_acc = accuracy_score(y_combined, model_final.predict(X_combined))
print(f"  Train accuracy: {train_acc*100:.2f}%")

# Feature importance
if nama == "GradientBoosting":
    imp = model_final.named_steps["gb"].feature_importances_
else:
    imp = model_final.named_steps["rf"].feature_importances_

df_imp = pd.DataFrame({
    "fitur": fitur_list, "importance": imp
}).sort_values("importance", ascending=False)

print(f"\n  TOP 20 FITUR:")
for _, r in df_imp.head(20).iterrows():
    tag = "🌍" if r["fitur"].startswith("makro_") else "📊"
    bar = "█" * int(r["importance"]*300)
    print(f"  {tag} {r['fitur']:<35} {r['importance']:.4f} {bar}")

# ── SIMPAN ────────────────────────────────────────────────────
print("\n[5/5] Simpan model...")

model_swing = {
    "pipeline"   : model_final,
    "fitur"      : fitur_list,
    "cv_accuracy": round(float(cv), 4),
    "train_acc"  : round(float(train_acc), 4),
    "nama_model" : nama,
    "target"     : "naik >= 1.5% dalam 1-3 hari",
    "n_saham"    : len(meta),
    "n_data"     : len(X_combined),
    "tanggal"    : datetime.now().strftime("%Y-%m-%d"),
    "fitur_makro": [f for f in fitur_list if f.startswith("makro_")],
    "makro_layak": MAKRO_LAYAK,
}

with open("models/model_swing.pkl", "wb") as f:
    pickle.dump(model_swing, f)

df_imp.to_csv("logs/fitur_swing_makro.csv", index=False)

print(f"\n{'='*65}")
print(f"SELESAI!")
print(f"  Model    : models/model_swing.pkl")
print(f"  CV Acc   : {cv*100:.2f}%")
print(f"  Saham    : {len(meta)} saham")
print(f"  Fitur    : {len(fitur_list)} total ({n_teknikal} teknikal + {n_makro} makro)")
print(f"{'='*65}")

# Bandingkan dengan model lama
print(f"\nPerbandingan:")
print(f"  Model lama (teknikal saja) : 66.16%")
print(f"  Model baru (+ makro global): {cv*100:.2f}%")
delta = cv*100 - 66.16
if delta > 0:
    print(f"  Peningkatan               : +{delta:.2f}% ✅")
else:
    print(f"  Perubahan                 : {delta:.2f}% ⚠️")
print(f"\nLangkah berikutnya: jalankan scoring_selektif.py")
