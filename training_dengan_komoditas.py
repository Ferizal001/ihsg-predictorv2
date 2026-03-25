"""
training_dengan_komoditas.py
Training ulang model dengan fitur komoditas real terintegrasi
"""
import pandas as pd
import numpy as np
import os
import pickle
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score

os.makedirs("models", exist_ok=True)
os.makedirs("logs", exist_ok=True)

# ── 1. Muat data komoditas ────────────────────────────────────
print("Muat data komoditas...")
komoditas_path = "data/KOMODITAS_GABUNGAN.csv"
df_kom = pd.read_csv(komoditas_path, index_col=0)
df_kom.index = pd.to_datetime(df_kom.index)
print(f"  Komoditas: {len(df_kom)} hari, {len(df_kom.columns)} fitur")

# ── 2. Muat semua data saham ──────────────────────────────────
print("Muat data saham...")
SECTORS = {
    "tambang"  : ["ADRO","PTBA","ITMG","INCO","ANTM","TINS","MEDC","HRUM","MDKA"],
    "perbankan": ["BBRI","BMRI","BBCA","BBNI","BRIS","BNGA","BBTN","PNBN"],
    "konsumer" : ["UNVR","ICBP","MYOR","KLBF","KAEF","CPIN","SIDO"],
    "agribisnis": ["AALI","SIMP","LSIP"],
    "energi"   : ["PGAS","MEDC","AKRA"],
    "lainnya"  : ["ASII","AUTO","TLKM","EXCL","ISAT","TOWR","MTEL",
                  "INDF","INTP","SMGR","WIKA","PTPP","WSKT","ADHI",
                  "GOTO","EMTK","BUKA","DMMX","SMSM","UNTR","BRPT","TPIA"],
}

def get_sektor(kode):
    for s, emiten in SECTORS.items():
        if kode in emiten:
            return s
    return "lainnya"

def hitung_teknikal(df):
    close = df["close"]
    volume = df["volume"]
    df["ma5"]   = close.rolling(5).mean()
    df["ma20"]  = close.rolling(20).mean()
    df["ma50"]  = close.rolling(50).mean()
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta).clip(lower=0).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["rsi"]   = 100 - (100 / (1 + rs))
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"]      = ema12 - ema26
    df["macd_hist"] = df["macd"] - df["macd"].ewm(span=9, adjust=False).mean()
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bb_pct"]  = (close - (sma20 - 2*std20)) / (4*std20).replace(0, np.nan)
    df["vol_ratio"] = volume / volume.rolling(20).mean().replace(0, np.nan)
    for lag in [1, 3, 5]:
        df[f"return_lag{lag}"] = close.pct_change(lag)
    df["volatility_5d"]  = close.pct_change().rolling(5).std()
    df["volatility_20d"] = close.pct_change().rolling(20).std()
    df["above_ma20"] = (close > df["ma20"]).astype(int)
    df["above_ma50"] = (close > df["ma50"]).astype(int)
    df["volume_spike"] = (df["vol_ratio"] > 2.0).astype(int)
    df["akumulasi"] = ((close > close.shift(1)) & (volume > volume.shift(1))).astype(int)
    df["label"] = (close.pct_change().shift(-1) > 0).astype(int)
    return df

# Kumpulkan semua data
semua = []
for f in os.listdir("data"):
    if not f.endswith(".csv") or f.startswith("KOMODITAS"):
        continue
    kode = f.replace(".csv","")
    try:
        df = pd.read_csv(f"data/{f}")
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        if len(df) < 100:
            continue
        # Filter saham layak
        if df["close"].iloc[-1] < 100:
            continue
        vol_nilai = df["close"].iloc[-1] * df["volume"].iloc[-1]
        if vol_nilai < 500_000_000:
            continue
        df = hitung_teknikal(df)
        df["ticker"] = kode
        df["sektor"] = get_sektor(kode)
        # Gabungkan komoditas
        df = df.join(df_kom, how="left")
        df = df.ffill().dropna(subset=["label","rsi","macd"])
        semua.append(df)
    except Exception as e:
        pass

df_all = pd.concat(semua, ignore_index=False)
df_all = df_all.replace([np.inf, -np.inf], np.nan).dropna()
print(f"  Dataset: {len(df_all):,} baris | {df_all['ticker'].nunique()} saham")

# ── 3. Fitur yang dipakai ─────────────────────────────────────
FITUR_TEKNIKAL = [
    "rsi","macd","macd_hist","bb_pct","vol_ratio",
    "return_lag1","return_lag3","return_lag5",
    "volatility_5d","volatility_20d",
    "above_ma20","above_ma50","volume_spike","akumulasi",
]
FITUR_KOMODITAS = [c for c in df_kom.columns if c in df_all.columns]
SEMUA_FITUR = FITUR_TEKNIKAL + FITUR_KOMODITAS
FITUR_ADA   = [f for f in SEMUA_FITUR if f in df_all.columns]
print(f"  Fitur teknikal: {len(FITUR_TEKNIKAL)} | Fitur komoditas: {len(FITUR_KOMODITAS)}")
print(f"  Total fitur   : {len(FITUR_ADA)}")

# ── 4. Training per sektor ────────────────────────────────────
print("\nTraining model per sektor...")
models = {}

for sektor in df_all["sektor"].unique():
    df_s = df_all[df_all["sektor"] == sektor].copy()
    if len(df_s) < 100:
        continue

    fitur_ada = [f for f in FITUR_ADA if f in df_s.columns]
    X = df_s[fitur_ada].values
    y = df_s["label"].values

    split    = int(len(X) * 0.8)
    X_tr, X_te = X[:split], X[split:]
    y_tr, y_te = y[:split], y[split:]

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", GradientBoostingClassifier(
            n_estimators=100,
            max_depth=3,        # lebih kecil = kurang overfit
            learning_rate=0.05,
            subsample=0.7,
            min_samples_leaf=20, # regularisasi
            random_state=42,
        ))
    ])
    model.fit(X_tr, y_tr)

    acc_tr = accuracy_score(y_tr, model.predict(X_tr))
    acc_te = accuracy_score(y_te, model.predict(X_te))
    gap    = acc_tr - acc_te
    flag   = "overfit" if gap > 0.1 else "OK"

    print(f"  {sektor:12s} | n={len(df_s):5,} | "
          f"Train={acc_tr:.2%} | Test={acc_te:.2%} | "
          f"Gap={gap:.2%} {'⚠️' if flag=='overfit' else '✓'}")

    # Feature importance
    imp = model.named_steps["clf"].feature_importances_
    top3 = sorted(zip(fitur_ada, imp), key=lambda x: -x[1])[:3]
    print(f"    Top fitur: {', '.join([f'{n}={v:.3f}' for n,v in top3])}")

    models[sektor] = {
        "pipeline"  : model,
        "fitur"     : fitur_ada,
        "acc_test"  : acc_te,
        "n_samples" : len(df_s),
    }

# ── 5. Simpan model ───────────────────────────────────────────
print("\nSimpan model...")
with open("models/models_latest.pkl","wb") as f:
    pickle.dump(models, f)
with open("models/models_dengan_komoditas.pkl","wb") as f:
    pickle.dump(models, f)

print(f"Selesai! {len(models)} model tersimpan")
avg_acc = sum(v["acc_test"] for v in models.values()) / len(models)
print(f"Akurasi test rata-rata: {avg_acc:.2%}")
