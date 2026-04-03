"""
brain.py — IHSG Predictor Brain
Sistem AI yang belajar sendiri setiap hari.

Jadwal otomatis di Railway:
08:00 WIB - Download data saham terbaru
08:15 WIB - Scoring + kirim sinyal ke Telegram
21:00 WIB - Evaluasi prediksi kemarin (akurasi real)
22:00 WIB - Auto learning: coba strategi baru
23:00 WIB - Update model jika lebih baik
23:30 WIB - Laporan harian ke Telegram

Loop belajar:
1. Setiap hari: evaluasi prediksi vs kenyataan
2. Setiap hari: coba 1 strategi baru (rotasi)
3. Setiap minggu: analisis fitur mana paling berguna
4. Setiap bulan: retrain dari nol dengan semua insight
"""
import os, time, ssl, json, pickle, warnings, math
import urllib.request, urllib.error, urllib.parse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.metrics import accuracy_score, precision_score, recall_score
warnings.filterwarnings("ignore")

# ── Setup ─────────────────────────────────────────────────────
os.makedirs("models", exist_ok=True)
os.makedirs("logs/brain", exist_ok=True)
os.makedirs("data", exist_ok=True)

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode    = ssl.CERT_NONE
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IHSGBrain/1.0)"}
TOKEN   = os.environ.get("TELEGRAM_TOKEN","")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID","")

# ── File state otak ───────────────────────────────────────────
BRAIN_STATE = "logs/brain/state.json"
BEST_ACC    = "logs/brain/best_accuracy.txt"
HISTORY     = "logs/brain/history.csv"
PRED_LOG    = "logs/brain/predictions.csv"

def load_state():
    default = {
        "hari_ke": 0,
        "akurasi_terbaik": 0.6045,
        "strategi_index": 0,
        "total_training": 0,
        "total_deploy": 0,
        "akurasi_7hari": [],
        "fitur_terbaik": [],
        "catatan": []
    }
    if os.path.exists(BRAIN_STATE):
        try:
            with open(BRAIN_STATE) as f:
                state = json.load(f)
                for k, v in default.items():
                    if k not in state:
                        state[k] = v
                return state
        except:
            pass
    return default

def save_state(state):
    with open(BRAIN_STATE,"w") as f:
        json.dump(state, f, indent=2)

def load_best_acc():
    if os.path.exists(BEST_ACC):
        try:
            return float(open(BEST_ACC).read().strip())
        except:
            pass
    return 0.6045

def save_best_acc(acc):
    with open(BEST_ACC,"w") as f:
        f.write(str(acc))

# ── Telegram ──────────────────────────────────────────────────
def telegram(pesan):
    if not TOKEN or not CHAT_ID:
        print(f"[TELEGRAM]\n{pesan[:200]}")
        return
    try:
        url  = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": CHAT_ID,
            "text": pesan,
            "parse_mode": "HTML"
        }).encode()
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=15, context=CTX)
    except Exception as e:
        print(f"Telegram error: {e}")

# ── Download Yahoo Finance ────────────────────────────────────
def yahoo(ticker, period="5y", full=False):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range={period}&interval=1d&includePrePost=false")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                d = json.loads(r.read().decode())
            res = d["chart"]["result"]
            if not res: return None
            ts = res[0]["timestamp"]
            q  = res[0]["indicators"]["quote"][0]
            dates = pd.to_datetime(ts, unit="s").normalize()
            if full:
                df = pd.DataFrame({
                    "close" : q.get("close",[]),
                    "high"  : q.get("high",[]),
                    "low"   : q.get("low",[]),
                    "volume": q.get("volume",[]),
                }, index=dates).dropna(subset=["close"])
                return df if len(df)>50 else None
            else:
                s = pd.Series(q.get("close",[]), index=dates).dropna()
                return s if len(s)>50 else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(8+attempt*5); continue
            return None
        except: return None
    return None

# ── Download data saham terbaru ───────────────────────────────
SAHAM_LIST = [
    "BBCA","BBRI","BMRI","BBNI","BRIS","BNGA","BBTN","PNBN","BDMN","MEGA",
    "BJBR","NISP","ARTO","BTPS","AGRO","TLKM","EXCL","ISAT","TOWR","MTEL",
    "TBIG","LINK","ADRO","PTBA","ITMG","INCO","ANTM","TINS","MEDC","HRUM",
    "MDKA","PTRO","DOID","MBAP","GEMS","BUMI","BYAN","MYOH","INDY","DEWA",
    "ELSA","ESSA","PGAS","AKRA","ENRG","RUIS",
    "UNVR","ICBP","MYOR","CPIN","GGRM","HMSP","INDF","ULTJ","DLTA","MLBI",
    "KLBF","SIDO","ROTI","GOOD","ADES",
    "AALI","SIMP","LSIP","SSMS","SGRO","BWPT",
    "BSDE","CTRA","PWON","LPKR","SMRA","ASRI","MKPI","BEST","WSBP","TOTL",
    "SMGR","INTP","WIKA","PTPP","WSKT","ADHI","NRCA","KRAS","IDPR",
    "MIKA","SILO","HEAL","TSPC","KAEF","PRDA",
    "SCMA","MNCN","EMTK","BMTR",
    "GOTO","BUKA","MTDL",
    "ACES","MAPI","LPPF","RALS","AMRT","CSAP",
    "ASII","AUTO","SMSM","UNTR","INDS","GJTL",
    "ADMF","BFIN","SMMA","TRIM","VINS","ASRM",
    "JSMR","CMNP","META","GIAA","TMAS",
]

SEKTOR = {
    "BBCA":"perbankan","BBRI":"perbankan","BMRI":"perbankan","BBNI":"perbankan",
    "BRIS":"perbankan","BNGA":"perbankan","BBTN":"perbankan","PNBN":"perbankan",
    "BDMN":"perbankan","MEGA":"perbankan","BJBR":"perbankan","NISP":"perbankan",
    "ARTO":"perbankan","BTPS":"perbankan","AGRO":"perbankan",
    "TLKM":"telekomunikasi","EXCL":"telekomunikasi","ISAT":"telekomunikasi",
    "TOWR":"telekomunikasi","MTEL":"telekomunikasi","TBIG":"telekomunikasi",
    "LINK":"telekomunikasi",
    "ADRO":"tambang","PTBA":"tambang","ITMG":"tambang","INCO":"tambang",
    "ANTM":"tambang","TINS":"tambang","MEDC":"tambang","HRUM":"tambang",
    "MDKA":"tambang","PTRO":"tambang","DOID":"tambang","MBAP":"tambang",
    "GEMS":"tambang","BUMI":"tambang","BYAN":"tambang","MYOH":"tambang",
    "INDY":"tambang","DEWA":"tambang",
    "ELSA":"energi","ESSA":"energi","PGAS":"energi","AKRA":"energi",
    "ENRG":"energi","RUIS":"energi",
    "UNVR":"konsumer","ICBP":"konsumer","MYOR":"konsumer","CPIN":"konsumer",
    "GGRM":"konsumer","HMSP":"konsumer","INDF":"konsumer","ULTJ":"konsumer",
    "DLTA":"konsumer","MLBI":"konsumer","KLBF":"konsumer","SIDO":"konsumer",
    "ROTI":"konsumer","GOOD":"konsumer","ADES":"konsumer",
    "AALI":"agribisnis","SIMP":"agribisnis","LSIP":"agribisnis",
    "SSMS":"agribisnis","SGRO":"agribisnis","BWPT":"agribisnis",
    "BSDE":"properti","CTRA":"properti","PWON":"properti","LPKR":"properti",
    "SMRA":"properti","ASRI":"properti","MKPI":"properti","BEST":"properti",
    "WSBP":"properti","TOTL":"properti","SMGR":"properti","INTP":"properti",
    "WIKA":"properti","PTPP":"properti","WSKT":"properti","ADHI":"properti",
    "NRCA":"properti","KRAS":"properti","IDPR":"properti",
    "MIKA":"kesehatan","SILO":"kesehatan","HEAL":"kesehatan","TSPC":"kesehatan",
    "KAEF":"kesehatan","PRDA":"kesehatan",
    "SCMA":"media","MNCN":"media","EMTK":"media","BMTR":"media",
    "GOTO":"teknologi","BUKA":"teknologi","MTDL":"teknologi",
    "ACES":"ritel","MAPI":"ritel","LPPF":"ritel","RALS":"ritel",
    "AMRT":"ritel","CSAP":"ritel",
    "ASII":"otomotif","AUTO":"otomotif","SMSM":"otomotif","UNTR":"otomotif",
    "INDS":"otomotif","GJTL":"otomotif",
    "ADMF":"keuangan","BFIN":"keuangan","SMMA":"keuangan","TRIM":"keuangan",
    "VINS":"keuangan","ASRM":"keuangan",
    "JSMR":"infrastruktur","CMNP":"infrastruktur","META":"infrastruktur",
    "GIAA":"infrastruktur","TMAS":"infrastruktur",
}

def update_data_saham():
    """Download data saham terbaru dan update file CSV."""
    ok = 0
    for kode in SAHAM_LIST:
        path = f"data/{kode}.csv"
        df_baru = yahoo(f"{kode}.JK", period="3mo", full=True)
        if df_baru is not None:
            df_baru = df_baru.reset_index()
            df_baru.columns = ["date","close","high","low","volume"]
            df_baru["date"] = df_baru["date"].dt.strftime("%Y-%m-%d")
            if os.path.exists(path):
                df_lama = pd.read_csv(path)
                df_g = pd.concat([df_lama,df_baru]).drop_duplicates(
                    "date").sort_values("date")
                df_g.to_csv(path, index=False)
            else:
                df_baru.to_csv(path, index=False)
            ok += 1
        time.sleep(0.3)
    return ok

# ── Fitur ─────────────────────────────────────────────────────
def buat_fitur(df, data_asia, fitur_aktif=None):
    close  = pd.to_numeric(df["close"], errors="coerce")
    high   = pd.to_numeric(df.get("high",close), errors="coerce")
    low    = pd.to_numeric(df.get("low",close), errors="coerce")
    volume = pd.to_numeric(df.get("volume",
             pd.Series(1e6,index=df.index)), errors="coerce").fillna(1e6)
    ret    = close.pct_change()
    delta  = close.diff()
    gain   = delta.clip(lower=0).rolling(14).mean()
    loss   = (-delta).clip(lower=0).rolling(14).mean()
    rsi    = 100-(100/(1+gain/loss.replace(0,np.nan)))
    ema12  = close.ewm(span=12).mean()
    ema26  = close.ewm(span=26).mean()
    macd   = ema12-ema26
    msig   = macd.ewm(span=9).mean()
    sma20  = close.rolling(20).mean()
    sma50  = close.rolling(50).mean()
    std20  = close.rolling(20).std()
    bb     = (close-(sma20-2*std20))/(4*std20).replace(0,np.nan)
    vol_r  = volume/volume.rolling(20).mean().replace(0,np.nan)
    tp     = (high+low+close)/3
    mf     = tp*volume
    pmf    = mf.where(tp>tp.shift(1),0).rolling(14).sum()
    nmf    = mf.where(tp<tp.shift(1),0).rolling(14).sum()
    mfi    = 100-(100/(1+pmf/nmf.replace(0,np.nan)))
    mfv    = ((close-low)-(high-close))/(high-low).replace(0,np.nan)*volume
    cmf    = mfv.rolling(20).sum()/volume.rolling(20).sum().replace(0,np.nan)

    f = pd.DataFrame(index=df.index)
    # Teknikal dasar
    f["rsi"]             = rsi
    f["rsi_oversold"]    = (rsi<30).astype(int)
    f["rsi_overbought"]  = (rsi>70).astype(int)
    f["macd"]            = macd
    f["macd_hist"]       = macd-msig
    f["macd_cross_up"]   = ((macd>msig)&(macd.shift(1)<=msig.shift(1))).astype(int)
    f["bb_pct"]          = bb
    f["below_bb"]        = (bb<0).astype(int)
    f["vol_ratio"]       = vol_r
    f["vol_spike"]       = (vol_r>2).astype(int)
    f["akumulasi"]       = ((close>close.shift(1))&(volume>volume.shift(1))).astype(int)
    f["mfi"]             = mfi
    f["mfi_oversold"]    = (mfi<20).astype(int)
    f["cmf"]             = cmf
    # Return & momentum
    f["return_lag1"]     = ret.shift(1)
    f["return_lag2"]     = ret.shift(2)
    f["return_lag3"]     = ret.shift(3)
    f["return_3d"]       = ret.rolling(3).sum().shift(1)
    f["return_5d"]       = ret.rolling(5).sum().shift(1)
    f["volatility_5d"]   = ret.rolling(5).std()
    f["volatility_20d"]  = ret.rolling(20).std()
    f["momentum_5d"]     = close.pct_change(5)
    f["momentum_20d"]    = close.pct_change(20)
    f["above_ma20"]      = (close>sma20).astype(int)
    f["above_ma50"]      = (close>sma50).astype(int)
    f["pct_vs_ma20"]     = (close-sma20)/sma20.replace(0,np.nan)
    f["drawdown_5d"]     = close.pct_change(5)
    f["drawdown_10d"]    = close.pct_change(10)
    # Kalender
    f["bulan"]           = df.index.month
    f["kuartal"]         = df.index.quarter
    f["hari_minggu"]     = df.index.dayofweek
    f["hari_tahun"]      = df.index.dayofyear
    f["awal_bulan"]      = (df.index.day<=5).astype(int)
    f["akhir_bulan"]     = (df.index.day>=25).astype(int)
    # Asia (terbukti korelasi dari biostatistik)
    for nama in ["set","hangseng","klci","kospi","sti","sse","nikkei","ftse","dax"]:
        if nama not in data_asia: continue
        s    = data_asia[nama].reindex(df.index, method="ffill")
        r_a  = s.pct_change()
        ma5  = s.rolling(5,min_periods=1).mean()
        f[f"{nama}_ret"]   = r_a
        f[f"{nama}_lag1"]  = r_a.shift(1)
        f[f"{nama}_trend"] = (s-ma5)/ma5.replace(0,np.nan)
    for nama in ["usdidr","jpyidr"]:
        if nama not in data_asia: continue
        s   = data_asia[nama].reindex(df.index, method="ffill")
        r_a = s.pct_change()
        f[f"{nama}_ret"]  = r_a
        f[f"{nama}_lag1"] = r_a.shift(1)
        if nama=="usdidr":
            f["rupiah_lemah"]   = (s>16500).astype(int)
            f["rupiah_stabil"]  = (r_a.rolling(3).std()<0.003).astype(int)
    for nama in ["vvix","dowjones","brent"]:
        if nama not in data_asia: continue
        s   = data_asia[nama].reindex(df.index, method="ffill")
        r_a = s.pct_change()
        f[f"{nama}_lag1"] = r_a.shift(1)
        if nama=="vvix":
            f["vvix_level"]  = s
            f["vvix_tinggi"] = (s.shift(1)>100).astype(int)
            f["vvix_panik"]  = (s.shift(1)>120).astype(int)
            f["vvix_turun"]  = ((s<s.shift(1))&(s.shift(1)>30)).astype(int)
        if nama=="brent":
            f["brent_spike"] = (r_a.shift(1)>0.03).astype(int)

    # Filter fitur aktif jika ada
    if fitur_aktif:
        cols = [c for c in fitur_aktif if c in f.columns]
        return f[cols]
    return f

# ── Dataset ───────────────────────────────────────────────────
def buat_dataset_kode(kode, data_asia, min_hari=300, fitur_aktif=None):
    for path in [f"data/{kode}.csv",f"data/biostatistik/saham/{kode}.csv"]:
        if not os.path.exists(path): continue
        try:
            df = pd.read_csv(path)
            df.columns = [c.lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            for col in ["close","high","low","volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            if len(df) < min_hari: return None, None
            df["target"] = (df["close"].shift(-1) > df["close"]).astype(int)
            X = buat_fitur(df, data_asia, fitur_aktif)
            y = df["target"]
            valid = y.notna() & (X.isna().sum(axis=1) < X.shape[1]*0.4)
            X = X[valid].fillna(0)
            y = y[valid]
            return (X,y) if len(X)>=100 else (None,None)
        except: continue
    return None, None

# ══════════════════════════════════════════════════════════════
# 5 STRATEGI BERBEDA — ROTASI SETIAP HARI
# ══════════════════════════════════════════════════════════════
STRATEGI = [
    # (nama, min_hari, trees, depth, leaves, algo)
    ("RF-Standard",   300,  300, 10, 15, "rf"),
    ("RF-Deep",       300,  400, 14,  8, "rf"),
    ("RF-Shallow",    500,  200,  6, 25, "rf"),
    ("RF-ManyTrees",  300,  600,  8, 20, "rf"),
    ("GB-Boost",      400,  200,  5, 20, "gb"),
]

def train_dengan_strategi(idx_strategi, data_asia, fitur_aktif=None):
    nama, min_hari, trees, depth, leaves, algo = STRATEGI[idx_strategi]
    print(f"  Strategi: {nama} | min_hari={min_hari} trees={trees} depth={depth}")

    # Scan saham
    SKIP = ["KOMODITAS","MAKRO","CUACA","ENSO","KALENDER","GABUNGAN",
            "BDI","IHSG","KOSPI","STI_","KLCI","Nikkei","HangSeng",
            "SSE","SET_","SP500","DowJones","NASDAQ","FTSE","DAX",
            "VIX","USD","EUR","JPY","SGD","AUD","DXY","USBond",
            "Bitcoin","Ethereum","iShares","MSCI","beras","gandum",
            "jagung","kedelai","kopi","gula","kakao","kapas",
            "minyak","gas","emas","perak","tembaga","palladium"]
    semua = set()
    for folder in ["data","data/biostatistik/saham"]:
        if not os.path.exists(folder): continue
        for fname in os.listdir(folder):
            if not fname.endswith(".csv"): continue
            if any(x.lower() in fname.lower() for x in SKIP): continue
            k = fname.replace(".csv","")
            if len(k)<=6 and k.isupper(): semua.add(k)

    per_sektor = {}
    for k in sorted(semua):
        sek = SEKTOR.get(k,"lainnya")
        per_sektor.setdefault(sek,[]).append(k)

    models  = {}
    hasil   = []
    imp_all = []

    for sektor, saham_list in sorted(per_sektor.items()):
        X_all, y_all = [], []
        for kode in saham_list:
            X, y = buat_dataset_kode(kode, data_asia, min_hari, fitur_aktif)
            if X is not None:
                X_all.append(X); y_all.append(y)
        if not X_all: continue

        X_c = pd.concat(X_all).fillna(0)
        y_c = pd.concat(y_all)
        X_c = X_c.loc[:, X_c.nunique()>1]

        if algo == "rf":
            clf = RandomForestClassifier(
                n_estimators=trees, max_depth=depth,
                min_samples_leaf=leaves, max_features="sqrt",
                random_state=42, n_jobs=-1, class_weight="balanced")
        else:
            clf = GradientBoostingClassifier(
                n_estimators=trees, max_depth=depth,
                learning_rate=0.05, subsample=0.8, random_state=42)

        model = Pipeline([("scaler",StandardScaler()),("clf",clf)])

        tscv = TimeSeriesSplit(n_splits=5)
        try:
            scores = cross_val_score(model, X_c, y_c, cv=tscv,
                                      scoring="accuracy", n_jobs=-1)
            cv = round(float(scores.mean()),4)
        except:
            cv = 0

        model.fit(X_c, y_c)

        # Feature importance
        try:
            imp = model.named_steps["clf"].feature_importances_
            for fname_i, imp_i in zip(X_c.columns, imp):
                imp_all.append({"fitur":fname_i,"importance":imp_i,"sektor":sektor})
        except: pass

        models[sektor] = {
            "pipeline": model, "fitur": X_c.columns.tolist(),
            "cv_accuracy": cv, "n_data": len(X_c), "n_saham": len(X_all)
        }
        hasil.append({"sektor":sektor,"cv":cv,"n":len(X_all)})
        print(f"    {sektor}: CV={cv:.4f} ({len(X_all)} saham)")

    avg = round(float(np.mean([h["cv"] for h in hasil])),4) if hasil else 0

    # Rekap feature importance global
    df_imp = pd.DataFrame(imp_all)
    if len(df_imp) > 0:
        df_imp = df_imp.groupby("fitur")["importance"].mean().sort_values(
            ascending=False).reset_index()
        df_imp.to_csv("logs/brain/feature_importance.csv", index=False)

    return models, avg, hasil, df_imp if len(df_imp)>0 else pd.DataFrame()

# ══════════════════════════════════════════════════════════════
# EVALUASI PREDIKSI KEMARIN
# ══════════════════════════════════════════════════════════════
def evaluasi_prediksi_kemarin():
    """Bandingkan prediksi kemarin dengan harga aktual hari ini."""
    if not os.path.exists(PRED_LOG):
        return None

    df_pred = pd.read_csv(PRED_LOG)
    if len(df_pred) == 0:
        return None

    kemarin = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    df_k    = df_pred[df_pred["tanggal_prediksi"] == kemarin]
    if len(df_k) == 0:
        return None

    benar = 0
    total = 0
    hasil = []
    for _, row in df_k.iterrows():
        kode = row["ticker"]
        path = f"data/{kode}.csv"
        if not os.path.exists(path): continue
        df_s = pd.read_csv(path)
        df_s["date"] = pd.to_datetime(df_s["date"])
        df_s = df_s.set_index("date").sort_index()
        hari_ini = datetime.now().strftime("%Y-%m-%d")
        if hari_ini not in df_s.index.strftime("%Y-%m-%d"): continue
        close_kemarin = float(row["harga"])
        close_hari_ini= float(df_s["close"].iloc[-1])
        aktual_naik   = close_hari_ini > close_kemarin
        pred_naik     = row["sinyal"] in ["BELI","PANTAU"]
        cocok = aktual_naik == pred_naik
        if cocok: benar += 1
        total += 1
        hasil.append({
            "ticker"  : kode,
            "pred"    : row["sinyal"],
            "aktual"  : "NAIK" if aktual_naik else "TURUN",
            "chg_pct" : round((close_hari_ini-close_kemarin)/close_kemarin*100,2),
            "benar"   : cocok,
        })

    acc_real = benar/total if total > 0 else 0
    return {"acc_real": acc_real, "total": total, "benar": benar, "detail": hasil}

# ── Simpan prediksi hari ini ──────────────────────────────────
def simpan_prediksi(tanggal, ticker, harga, sinyal, skor):
    row = pd.DataFrame([{
        "tanggal_prediksi": tanggal,
        "ticker": ticker,
        "harga": harga,
        "sinyal": sinyal,
        "skor": skor
    }])
    if os.path.exists(PRED_LOG):
        df = pd.read_csv(PRED_LOG)
        df = pd.concat([df,row]).tail(500)  # simpan 500 prediksi terakhir
    else:
        df = row
    df.to_csv(PRED_LOG, index=False)

# ══════════════════════════════════════════════════════════════
# FUNGSI UTAMA — dipanggil oleh jadwal
# ══════════════════════════════════════════════════════════════
def download_data():
    """08:00 WIB — Update data saham."""
    print(f"[{datetime.now().strftime('%H:%M')}] Download data saham...")
    ok = update_data_saham()
    print(f"  {ok} saham diupdate")

def scoring_harian():
    """08:15 WIB — Scoring dan kirim sinyal ke Telegram."""
    # Import dari main.py yang sudah ada
    try:
        from main import scoring_harian as scoring_lama
        scoring_lama()
    except:
        print("Scoring tidak bisa dijalankan dari brain.py")

def evaluasi_dan_belajar():
    """21:00-23:30 WIB — Evaluasi + belajar + laporan."""
    tanggal = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"BRAIN AUTO LEARNING — {tanggal}")
    print(f"{'='*60}")

    state      = load_state()
    best_acc   = load_best_acc()
    hari_ke    = state["hari_ke"]
    idx_strat  = state["strategi_index"] % len(STRATEGI)

    # ── Step 1: Evaluasi prediksi kemarin ────────────────────
    print("\n[1/4] Evaluasi prediksi kemarin...")
    eval_result = evaluasi_prediksi_kemarin()
    if eval_result:
        acc_real = eval_result["acc_real"]
        print(f"  Akurasi real: {acc_real*100:.1f}% "
              f"({eval_result['benar']}/{eval_result['total']})")
        state["akurasi_7hari"].append(round(acc_real,4))
        state["akurasi_7hari"] = state["akurasi_7hari"][-7:]
    else:
        acc_real = None
        print("  Tidak ada data evaluasi kemarin")

    # ── Step 2: Download data Asia ────────────────────────────
    print("\n[2/4] Download pasar Asia...")
    tickers_asia = {
        "^SET.BK":"set","^HSI":"hangseng","^KLSE":"klci",
        "^KS11":"kospi","^STI":"sti","000001.SS":"sse",
        "^N225":"nikkei","^FTSE":"ftse","^GDAXI":"dax",
        "USDIDR=X":"usdidr","JPYIDR=X":"jpyidr",
        "^VVIX":"vvix","^DJI":"dowjones","BZ=F":"brent",
    }
    data_asia = {}
    for ticker, nama in tickers_asia.items():
        s = yahoo(ticker)
        if s is not None: data_asia[nama] = s
        time.sleep(0.5)
    print(f"  {len(data_asia)}/14 sumber berhasil")

    # ── Step 3: Pilih fitur terbaik (dari history) ───────────
    fitur_aktif = None
    imp_path = "logs/brain/feature_importance.csv"
    if os.path.exists(imp_path) and hari_ke > 0:
        df_imp = pd.read_csv(imp_path)
        if len(df_imp) > 20:
            # Ambil top 80% fitur berdasarkan importance
            df_imp = df_imp.sort_values("importance",ascending=False)
            cum_imp = df_imp["importance"].cumsum() / df_imp["importance"].sum()
            cutoff  = df_imp[cum_imp <= 0.95].index[-1]
            fitur_aktif = df_imp.loc[:cutoff,"fitur"].tolist()
            print(f"  Pakai {len(fitur_aktif)} fitur terbaik "
                  f"(dari {len(df_imp)} total)")

    # ── Step 4: Training dengan strategi hari ini ────────────
    nama_strat = STRATEGI[idx_strat][0]
    print(f"\n[3/4] Training strategi {idx_strat+1}/{len(STRATEGI)}: {nama_strat}...")
    waktu_mulai = datetime.now()

    models_baru, avg_cv, hasil_sektor, df_imp = train_dengan_strategi(
        idx_strat, data_asia, fitur_aktif)

    durasi_menit = (datetime.now()-waktu_mulai).seconds//60
    print(f"  Akurasi CV rata-rata: {avg_cv*100:.2f}%")
    print(f"  Durasi: {durasi_menit} menit")

    # ── Step 5: Update model jika lebih baik ─────────────────
    print(f"\n[4/4] Evaluasi dan simpan...")
    deployed = False
    catatan  = ""

    if avg_cv > best_acc:
        import shutil
        path_baru = f"models/models_brain_{tanggal.replace('-','')}.pkl"
        with open(path_baru,"wb") as f:
            pickle.dump(models_baru, f)
        shutil.copy(path_baru, "models/models_latest.pkl")
        save_best_acc(avg_cv)
        deployed = True
        delta = (avg_cv - best_acc)*100
        catatan = f"✅ NAIK {delta:+.2f}% ({best_acc*100:.2f}%→{avg_cv*100:.2f}%)"
        print(f"  {catatan}")
        best_acc = avg_cv
    else:
        import shutil
        if os.path.exists("models/models_final.pkl"):
            shutil.copy("models/models_final.pkl","models/models_latest.pkl")
        delta = (avg_cv - best_acc)*100
        catatan = f"⚠️ Belum naik ({delta:.2f}%), model terbaik tetap"
        print(f"  {catatan}")

    # ── Update state ──────────────────────────────────────────
    state["hari_ke"]        += 1
    state["strategi_index"] += 1
    state["total_training"] += 1
    if deployed: state["total_deploy"] += 1
    state["catatan"] = ([catatan] + state.get("catatan",[]  ))[:30]
    save_state(state)

    # Simpan ke history
    row = {
        "tanggal"    : tanggal,
        "strategi"   : nama_strat,
        "cv_accuracy": avg_cv,
        "acc_real"   : acc_real,
        "deployed"   : deployed,
        "durasi"     : durasi_menit,
    }
    df_hist = pd.read_csv(HISTORY) if os.path.exists(HISTORY) else pd.DataFrame()
    df_hist = pd.concat([df_hist, pd.DataFrame([row])], ignore_index=True)
    df_hist.to_csv(HISTORY, index=False)

    # ── Laporan Telegram ──────────────────────────────────────
    sektor_sorted = sorted(hasil_sektor, key=lambda x:-x["cv"])
    best_s  = sektor_sorted[0] if sektor_sorted else {"sektor":"-","cv":0}
    worst_s = sektor_sorted[-1] if sektor_sorted else {"sektor":"-","cv":0}

    # Tren 7 hari
    akurasi_7h = state.get("akurasi_7hari",[])
    tren_str = ""
    if len(akurasi_7h) >= 2:
        delta_7 = (akurasi_7h[-1] - akurasi_7h[0])*100 if len(akurasi_7h)>1 else 0
        tren_str = f"Tren 7 hari: {'▲' if delta_7>0 else '▼'} {abs(delta_7):.2f}%\n"

    # Progress bar
    target = 0.66
    progress = max(0,min(100,(avg_cv-0.6045)/(target-0.6045)*100))
    bar = "█"*int(progress/5) + "░"*(20-int(progress/5))

    # Hari berikutnya
    next_strat = STRATEGI[(idx_strat+1)%len(STRATEGI)][0]

    # Top fitur
    top_fitur = ""
    if len(df_imp) > 0:
        top3 = df_imp.head(3)["fitur"].tolist()
        top_fitur = f"🔍 Top fitur: {', '.join(top3)}\n"

    # Evaluasi real kemarin
    eval_str = ""
    if acc_real is not None:
        eval_str = (f"📊 Akurasi real kemarin: {acc_real*100:.1f}%\n"
                    f"   ({eval_result['benar']}/{eval_result['total']} prediksi benar)\n")

    msg = (
        f"🧠 <b>BRAIN LAPORAN HARIAN</b>\n"
        f"📅 {tanggal} | Hari ke-{state['hari_ke']}\n"
        f"{'─'*32}\n"
        f"🎯 <b>CV Akurasi: {avg_cv*100:.2f}%</b>\n"
        f"{eval_str}"
        f"{tren_str}"
        f"{'─'*32}\n"
        f"🔬 Strategi hari ini: {nama_strat}\n"
        f"📈 Terbaik: {best_s['sektor']} ({best_s['cv']*100:.1f}%)\n"
        f"📉 Perlu perhatian: {worst_s['sektor']} ({worst_s['cv']*100:.1f}%)\n"
        f"{top_fitur}"
        f"{'─'*32}\n"
        f"💾 {catatan}\n"
        f"🏆 Akurasi terbaik: {best_acc*100:.2f}%\n"
        f"📦 Total training: {state['total_training']} | Deploy: {state['total_deploy']}\n"
        f"{'─'*32}\n"
        f"Progress ke 66%:\n"
        f"[{bar}] {progress:.0f}%\n"
        f"Gap: {(target-avg_cv)*100:.2f}% lagi\n"
        f"{'─'*32}\n"
        f"🔮 Strategi besok: {next_strat}\n"
        f"⏰ Laporan berikut: besok 23:30 WIB"
    )
    telegram(msg)
    print(f"\nLaporan terkirim ke Telegram!")
    return avg_cv

# ── Entry point langsung ──────────────────────────────────────
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv)>1 else "learn"
    if cmd == "download":
        download_data()
    elif cmd == "learn":
        evaluasi_dan_belajar()
    else:
        evaluasi_dan_belajar()
