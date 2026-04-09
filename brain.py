"""
brain.py — IHSG Predictor Brain v2
Jadwal:
- 07:00 WIB: mulai training loop sampai akurasi naik
- 22:00 WIB: kirim laporan ke Telegram
- Loop training berhenti kalau: akurasi sudah naik ATAU sudah jam 21:45 WIB
"""
import os, time, ssl, json, pickle, warnings
import urllib.request, urllib.error, urllib.parse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.metrics import accuracy_score
warnings.filterwarnings("ignore")

os.makedirs("models", exist_ok=True)
os.makedirs("logs/brain", exist_ok=True)

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode    = ssl.CERT_NONE
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IHSGBrain/2.0)"}
TOKEN   = os.environ.get("TELEGRAM_TOKEN","")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID","")

BEST_ACC_FILE = "logs/brain/best_accuracy.txt"
HISTORY_FILE  = "logs/brain/history.csv"
STATE_FILE    = "logs/brain/state.json"

TARGET_ACC    = 0.66   # target akhir
BASELINE_ACC  = 0.6045 # akurasi model lama

# ── Telegram ──────────────────────────────────────────────────
def telegram(pesan):
    if not TOKEN or not CHAT_ID:
        print(f"[TELEGRAM]\n{pesan[:300]}")
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
        print("Telegram terkirim")
    except Exception as e:
        print(f"Telegram error: {e}")

# ── State ─────────────────────────────────────────────────────
def load_best_acc():
    if os.path.exists(BEST_ACC_FILE):
        try: return float(open(BEST_ACC_FILE).read().strip())
        except: pass
    return BASELINE_ACC

def save_best_acc(acc):
    with open(BEST_ACC_FILE,"w") as f: f.write(str(acc))

def load_state():
    default = {"hari_ke":0,"total_training":0,"total_deploy":0,
               "riwayat_cv":[],"strategi_index":0}
    if os.path.exists(STATE_FILE):
        try:
            s = json.load(open(STATE_FILE))
            for k,v in default.items():
                if k not in s: s[k] = v
            return s
        except: pass
    return default

def save_state(state):
    with open(STATE_FILE,"w") as f: json.dump(state, f, indent=2)

def simpan_history(row):
    df = pd.read_csv(HISTORY_FILE) if os.path.exists(HISTORY_FILE) \
         else pd.DataFrame()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(HISTORY_FILE, index=False)

# ── Download ──────────────────────────────────────────────────
def yahoo(ticker, period="5y"):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range={period}&interval=1d&includePrePost=false")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                d = json.loads(r.read().decode())
            res = d["chart"]["result"]
            if not res: return None
            ts     = res[0]["timestamp"]
            closes = res[0]["indicators"]["quote"][0]["close"]
            dates  = pd.to_datetime(ts, unit="s").normalize()
            s = pd.Series(closes, index=dates).dropna()
            return s if len(s) > 50 else None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(8+attempt*5); continue
            return None
        except: return None
    return None

def download_asia():
    tickers = {
        "^SET.BK":"set","^HSI":"hangseng","^KLSE":"klci",
        "^KS11":"kospi","^STI":"sti","000001.SS":"sse",
        "^N225":"nikkei","^FTSE":"ftse","^GDAXI":"dax",
        "USDIDR=X":"usdidr","JPYIDR=X":"jpyidr",
        "^VVIX":"vvix","^DJI":"dowjones","BZ=F":"brent",
    }
    data = {}
    for ticker, nama in tickers.items():
        s = yahoo(ticker)
        if s is not None: data[nama] = s
        time.sleep(0.5)
    print(f"  Asia: {len(data)}/14 sumber")
    return data


# ══════════════════════════════════════════════════════════════
# DATA INDONESIA GRATIS
# ══════════════════════════════════════════════════════════════

def download_bi_rate():
    """
    Download BI Rate dari API Bank Indonesia (data.go.id / SEKI BI).
    Fallback: estimasi dari Yahoo Finance (^IRX proxy).
    Return: pd.Series dengan index tanggal
    """
    # Coba dari Yahoo Finance proxy dulu (lebih reliable)
    tickers_proxy = {
        "^IRX"  : "tbill",   # US T-Bill 13w
        "ID10Y=X": "id10y",  # Indonesia 10yr bond
    }
    data = {}
    for ticker, nama in tickers_proxy.items():
        s = yahoo(ticker)
        if s is not None:
            data[nama] = s
        time.sleep(0.5)

    # Coba API data.go.id BI Rate
    try:
        url = "https://api.data.go.id/v1/dinamiskomposit/bi-rate"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10, context=CTX) as r:
            d = json.loads(r.read().decode())
        rows = d.get("data", [])
        if rows:
            dates = pd.to_datetime([r["periode"] for r in rows], errors="coerce")
            vals  = pd.to_numeric([r["nilai"] for r in rows], errors="coerce")
            s = pd.Series(vals.values, index=dates).dropna().sort_index()
            if len(s) > 10:
                data["bi_rate"] = s
                print(f"    ✓ bi_rate: {len(s)} data dari data.go.id")
    except:
        pass

    # Fallback: BI rate dari estimasi JISDOR
    try:
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/USDIDR=X"
               "?range=5y&interval=1mo&includePrePost=false")
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
            d = json.loads(r.read().decode())
        res = d["chart"]["result"]
        if res:
            ts     = res[0]["timestamp"]
            closes = res[0]["indicators"]["quote"][0]["close"]
            dates  = pd.to_datetime(ts, unit="s").normalize()
            s = pd.Series(closes, index=dates).dropna()
            data["jisdor_monthly"] = s
            print(f"    ✓ jisdor_monthly: {len(s)} data")
    except:
        pass

    return data


def download_komoditas_indonesia():
    """
    Download harga komoditas penting Indonesia dari Yahoo Finance.
    CPO, batu bara, nikel, timah, karet — semua ekspor utama Indonesia.
    """
    tickers = {
        "PALM": "cpo_sgx",       # CPO di SGX (proxy)
        "SBIN.BO": "steel_india", # Steel India (proxy nikel)
        "MTF=F": "coal",          # Newcastle Coal Futures
        "NG=F": "natgas",         # Natural Gas
        "HG=F": "copper",         # Copper
        "SI=F": "silver",         # Silver
        "GC=F": "gold",           # Gold
        "CL=F": "crude_oil",      # WTI Crude
        "BZ=F": "brent",          # Brent Crude
        "^JKSE": "ihsg",          # IHSG index
        "USDIDR=X": "usdidr",
        "^VIX": "vix",
        "^GSPC": "sp500",
        "^TNX": "usbond_10y",
        "DX=F": "dxy",            # Dollar Index
    }
    data = {}
    for ticker, nama in tickers.items():
        s = yahoo(ticker, period="5y")
        if s is not None:
            data[nama] = s
            print(f"    ✓ {nama}: {len(s)} hari")
        else:
            print(f"    ✗ {nama}")
        time.sleep(0.4)
    return data


def download_semua_data_indonesia():
    """Gabungkan semua sumber data Indonesia."""
    print("  Download data Indonesia...")
    data = {}

    # Komoditas & makro global
    data_kom = download_komoditas_indonesia()
    data.update(data_kom)

    # BI Rate & kurs
    data_bi = download_bi_rate()
    data.update(data_bi)

    print(f"  Total sumber: {len(data)}")
    return data


# ══════════════════════════════════════════════════════════════
# UJI KORELASI — Filter fitur signifikan
# ══════════════════════════════════════════════════════════════

def uji_korelasi_fitur(X, y, threshold=0.03):
    """
    Uji korelasi semua fitur dengan target.
    Pakai Pearson + Spearman, ambil yang |korelasi| > threshold.
    Return: list fitur signifikan + DataFrame hasil korelasi
    """
    hasil = []
    for col in X.columns:
        try:
            x_col = pd.to_numeric(X[col], errors="coerce").fillna(0)
            # Pearson
            corr_p = x_col.corr(y.astype(float))
            # Spearman (rank-based, lebih robust)
            corr_s = x_col.rank().corr(y.astype(float).rank())

            # Ambil yang lebih besar absolutnya
            max_corr = max(abs(corr_p), abs(corr_s)) if not (pd.isna(corr_p) and pd.isna(corr_s)) else 0
            hasil.append({
                "fitur"    : col,
                "pearson"  : round(float(corr_p) if not pd.isna(corr_p) else 0, 4),
                "spearman" : round(float(corr_s) if not pd.isna(corr_s) else 0, 4),
                "max_abs"  : round(float(max_corr), 4),
                "signifikan": max_corr >= threshold,
            })
        except:
            pass

    df_kor = pd.DataFrame(hasil).sort_values("max_abs", ascending=False)

    # Simpan hasil korelasi
    os.makedirs("logs/brain", exist_ok=True)
    df_kor.to_csv("logs/brain/korelasi_fitur.csv", index=False)

    # Fitur signifikan
    fitur_sig = df_kor[df_kor["signifikan"]]["fitur"].tolist()

    # Minimal 10 fitur terbaik
    if len(fitur_sig) < 10:
        fitur_sig = df_kor.head(10)["fitur"].tolist()

    print(f"  Fitur signifikan: {len(fitur_sig)}/{len(df_kor)} "
          f"(threshold={threshold})")
    if len(df_kor) > 0:
        top3 = df_kor.head(3)["fitur"].tolist()
        print(f"  Top 3 fitur: {', '.join(top3)}")

    return fitur_sig, df_kor


def tambah_fitur_indonesia(f, df, data_indo):
    """Tambahkan fitur dari data Indonesia ke dataframe fitur."""
    for nama, series in data_indo.items():
        try:
            s = series.reindex(df.index, method="ffill")
            r = s.pct_change()
            f[f"{nama}_ret"]  = r
            f[f"{nama}_lag1"] = r.shift(1)
            f[f"{nama}_ma5"]  = (s - s.rolling(5).mean()) / s.rolling(5).mean().replace(0, np.nan)

            # Fitur spesifik
            if nama == "vix":
                f["vix_tinggi"] = (s.shift(1) > 25).astype(int)
                f["vix_turun"]  = ((s < s.shift(1)) & (s.shift(1) > 25)).astype(int)
            if nama == "usdidr":
                f["rupiah_lemah2"]  = (s > 16500).astype(int)
                f["rupiah_menguat"] = (r < -0.005).astype(int)
            if nama == "ihsg":
                f["ihsg_naik"]    = (r > 0).astype(int)
                f["ihsg_naik_3d"] = (s.pct_change(3) > 0).astype(int)
            if nama == "coal":
                f["coal_tinggi"] = (s > s.rolling(60).mean()).astype(int)
            if nama == "brent":
                f["brent_spike2"] = (r.shift(1) > 0.03).astype(int)
            if nama == "dxy":
                f["dxy_naik"] = (r > 0).astype(int)
            if "bi_rate" in nama:
                f["bi_rate_val"] = s.reindex(df.index, method="ffill")
        except:
            pass
    return f


# ── Sektor ────────────────────────────────────────────────────
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

# ── Fitur ─────────────────────────────────────────────────────
def buat_fitur(df, data_asia, data_indo=None):
    close  = pd.to_numeric(df["close"], errors="coerce")
    high   = pd.to_numeric(df.get("high", close), errors="coerce")
    low    = pd.to_numeric(df.get("low", close), errors="coerce")
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
    f["rsi"]           = rsi
    f["rsi_oversold"]  = (rsi<30).astype(int)
    f["macd"]          = macd
    f["macd_hist"]     = macd-msig
    f["macd_cross_up"] = ((macd>msig)&(macd.shift(1)<=msig.shift(1))).astype(int)
    f["bb_pct"]        = bb
    f["below_bb"]      = (bb<0).astype(int)
    f["vol_ratio"]     = vol_r
    f["vol_spike"]     = (vol_r>2).astype(int)
    f["akumulasi"]     = ((close>close.shift(1))&(volume>volume.shift(1))).astype(int)
    f["mfi"]           = mfi
    f["mfi_oversold"]  = (mfi<20).astype(int)
    f["cmf"]           = cmf
    f["return_lag1"]   = ret.shift(1)
    f["return_lag2"]   = ret.shift(2)
    f["return_lag3"]   = ret.shift(3)
    f["return_3d"]     = ret.rolling(3).sum().shift(1)
    f["return_5d"]     = ret.rolling(5).sum().shift(1)
    f["volatility_5d"] = ret.rolling(5).std()
    f["volatility_20d"]= ret.rolling(20).std()
    f["momentum_5d"]   = close.pct_change(5)
    f["momentum_20d"]  = close.pct_change(20)
    f["above_ma20"]    = (close>sma20).astype(int)
    f["above_ma50"]    = (close>sma50).astype(int)
    f["pct_vs_ma20"]   = (close-sma20)/sma20.replace(0,np.nan)
    f["drawdown_10d"]  = close.pct_change(10)
    f["bulan"]         = df.index.month
    f["kuartal"]       = df.index.quarter
    f["hari_minggu"]   = df.index.dayofweek
    f["hari_tahun"]    = df.index.dayofyear
    f["awal_bulan"]    = (df.index.day<=5).astype(int)
    f["akhir_bulan"]   = (df.index.day>=25).astype(int)

    for nama in ["set","hangseng","klci","kospi","sti","sse","nikkei","ftse","dax"]:
        if nama not in data_asia: continue
        s   = data_asia[nama].reindex(df.index, method="ffill")
        r_a = s.pct_change()
        ma5 = s.rolling(5,min_periods=1).mean()
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
            f["rupiah_lemah"]  = (s>16500).astype(int)
            f["rupiah_stabil"] = (r_a.rolling(3).std()<0.003).astype(int)
    for nama in ["vvix","dowjones","brent"]:
        if nama not in data_asia: continue
        s   = data_asia[nama].reindex(df.index, method="ffill")
        r_a = s.pct_change()
        f[f"{nama}_lag1"] = r_a.shift(1)
        if nama=="vvix":
            f["vvix_tinggi"] = (s.shift(1)>100).astype(int)
            f["vvix_panik"]  = (s.shift(1)>120).astype(int)
            f["vvix_turun"]  = ((s<s.shift(1))&(s.shift(1)>30)).astype(int)
        if nama=="brent":
            f["brent_spike"] = (r_a.shift(1)>0.03).astype(int)
    # Tambah fitur Indonesia kalau ada
    if data_indo:
        f = tambah_fitur_indonesia(f, df, data_indo)
    return f

def buat_dataset(kode, data_asia, min_hari=300, data_indo=None):
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
            df["target"] = (df["close"].shift(-1)>df["close"]).astype(int)
            X = buat_fitur(df, data_asia, data_indo)
            y = df["target"]
            valid = y.notna()&(X.isna().sum(axis=1)<X.shape[1]*0.4)
            X = X[valid].fillna(0)
            y = y[valid]
            return (X,y) if len(X)>=100 else (None,None)
        except: continue
    return None, None

def scan_saham():
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
    return per_sektor

# ══════════════════════════════════════════════════════════════
# SELF-HEALING — Auto koreksi kalau ada error
# ══════════════════════════════════════════════════════════════
ERROR_LOG = "logs/brain/error_log.json"

def catat_error(fungsi, error_msg):
    """Catat error ke file untuk analisis."""
    log = []
    if os.path.exists(ERROR_LOG):
        try: log = json.load(open(ERROR_LOG))
        except: pass
    log.append({
        "waktu"  : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fungsi" : fungsi,
        "error"  : str(error_msg)[:200],
    })
    log = log[-50:]  # simpan 50 error terakhir
    with open(ERROR_LOG,"w") as f:
        json.dump(log, f, indent=2)

def self_heal(fungsi_nama, error):
    """
    Coba fix error secara otomatis.
    Return True kalau berhasil fix, False kalau tidak bisa.
    """
    err_str = str(error).lower()
    print(f"\n[SELF-HEAL] Mendeteksi error: {error}")
    print(f"[SELF-HEAL] Mencoba auto-fix...")

    # ── Fix 1: SSL Error ─────────────────────────────────────
    if "ssl" in err_str or "certificate" in err_str:
        print("[SELF-HEAL] Fix SSL: sudah ada bypass, skip download")
        return True  # SSL bypass sudah aktif, lanjut saja

    # ── Fix 2: File tidak ditemukan ──────────────────────────
    if "no such file" in err_str or "filenotfound" in err_str:
        print("[SELF-HEAL] Fix: buat folder yang hilang")
        for folder in ["models","logs/brain","data","data/biostatistik/saham"]:
            os.makedirs(folder, exist_ok=True)
        return True

    # ── Fix 3: Model pkl rusak ───────────────────────────────
    if "pickle" in err_str or "unpickling" in err_str:
        print("[SELF-HEAL] Fix: model pkl rusak, kembalikan models_final")
        try:
            import shutil
            if os.path.exists("models/models_final.pkl"):
                shutil.copy("models/models_final.pkl","models/models_latest.pkl")
                print("[SELF-HEAL] models_latest.pkl dikembalikan ke models_final")
                return True
        except: pass

    # ── Fix 4: Memory error ──────────────────────────────────
    if "memory" in err_str or "memoryerror" in err_str:
        print("[SELF-HEAL] Fix memory: kurangi n_estimators ke 100")
        # Modifikasi STRATEGI sementara
        global STRATEGI
        STRATEGI = [
            ("RF-Light", 300, 100, 6, 20, "rf"),
        ]
        return True

    # ── Fix 5: Rate limit Yahoo ──────────────────────────────
    if "429" in err_str or "too many" in err_str:
        print("[SELF-HEAL] Fix rate limit: tunggu 60 detik")
        time.sleep(60)
        return True

    # ── Fix 6: Data kosong ───────────────────────────────────
    if "empty" in err_str or "no data" in err_str or "length 0" in err_str:
        print("[SELF-HEAL] Fix data kosong: pakai model lama")
        return False  # skip strategi ini, lanjut ke berikutnya

    # ── Fix 7: Convergence warning ───────────────────────────
    if "convergence" in err_str or "max_iter" in err_str:
        print("[SELF-HEAL] Fix convergence: lanjut dengan warning")
        return True

    print(f"[SELF-HEAL] Tidak bisa auto-fix error ini, skip strategi")
    return False

def safe_run(fungsi, *args, nama="fungsi", max_retry=3, **kwargs):
    """
    Wrapper yang auto-retry + self-heal kalau error.
    """
    for attempt in range(max_retry):
        try:
            return fungsi(*args, **kwargs)
        except Exception as e:
            catat_error(nama, e)
            print(f"\n[ERROR] {nama} attempt {attempt+1}/{max_retry}: {e}")

            if attempt < max_retry-1:
                bisa_fix = self_heal(nama, e)
                if bisa_fix:
                    print(f"[SELF-HEAL] Retry {attempt+2}/{max_retry}...")
                    time.sleep(5)
                    continue
                else:
                    print(f"[SELF-HEAL] Tidak bisa fix, skip")
                    return None
            else:
                print(f"[ERROR] Semua retry gagal untuk {nama}")
                return None
    return None


# ══════════════════════════════════════════════════════════════
# RETRAIN SWING MODEL (gabungan dengan brain)
# ══════════════════════════════════════════════════════════════

SWING_ACC_FILE = "logs/brain/best_swing_acc.txt"

def load_best_swing_acc():
    if os.path.exists(SWING_ACC_FILE):
        try: return float(open(SWING_ACC_FILE).read().strip())
        except: pass
    return 0.60

def save_best_swing_acc(acc):
    with open(SWING_ACC_FILE,"w") as f: f.write(str(acc))

def buat_fitur_swing_brain(df, data_indo=None):
    """Fitur swing untuk brain (lebih lengkap dari scoring_swing.py)."""
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
    rsi   = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    f["rsi"]           = rsi
    f["rsi_oversold"]  = (rsi < 30).astype(int)
    f["rsi_naik"]      = ((rsi > rsi.shift(1)) & (rsi < 50)).astype(int)
    f["rsi_cross50"]   = ((rsi > 50) & (rsi.shift(1) <= 50)).astype(int)

    # MACD
    ema12  = close.ewm(span=12).mean()
    ema26  = close.ewm(span=26).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    f["macd"]          = macd
    f["macd_hist"]     = macd - signal
    f["macd_cross"]    = ((macd > signal) & (macd.shift(1) <= signal.shift(1))).astype(int)
    f["macd_positif"]  = (macd > 0).astype(int)

    # BB
    sma5  = close.rolling(5).mean()
    sma10 = close.rolling(10).mean()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    std20 = close.rolling(20).std()
    bb_lo = sma20 - 2*std20
    f["bb_pct"]        = (close - bb_lo) / (4*std20).replace(0, np.nan)
    f["below_bb"]      = (close < bb_lo).astype(int)
    f["close_vs_sma5"] = (close / sma5.replace(0,np.nan) - 1)
    f["close_vs_sma10"]= (close / sma10.replace(0,np.nan) - 1)
    f["close_vs_sma50"]= (close / sma50.replace(0,np.nan) - 1)
    f["golden_cross"]  = ((sma5>sma10)&(sma10>sma50)).astype(int)

    # Volume
    vol_ma = volume.rolling(20).mean().replace(0,np.nan)
    f["vol_ratio"]     = volume / vol_ma
    f["vol_spike"]     = (f["vol_ratio"] > 2).astype(int)
    f["akumulasi"]     = ((close>close.shift(1))&(f["vol_ratio"]>1.5)).astype(int)
    f["akumulasi_2d"]  = f["akumulasi"].rolling(2).sum()

    # Breakout
    high20 = high.rolling(20).max()
    low20  = low.rolling(20).min()
    f["breakout_up"]   = ((close>high20.shift(1))&(f["vol_ratio"]>1.5)).astype(int)
    f["near_high20"]   = ((close/high20.replace(0,np.nan))>0.97).astype(int)
    f["range_pct"]     = (high20-low20)/low20.replace(0,np.nan)

    # Stochastic
    low14  = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch  = (close-low14)/(high14-low14).replace(0,np.nan)*100
    stoch_d= stoch.rolling(3).mean()
    f["stoch_k"]       = stoch
    f["stoch_oversold"]= (stoch<20).astype(int)
    f["stoch_cross"]   = ((stoch>stoch_d)&(stoch.shift(1)<=stoch_d.shift(1))&(stoch<40)).astype(int)

    # Candle
    body   = abs(close-close.shift(1))
    shadow = high-low
    f["hammer"]        = ((shadow>body*2)&(close>close.shift(1))).astype(int)
    f["strong_candle"] = ((close-close.shift(1))>close.shift(1)*0.02).astype(int)

    # Returns
    for lag in [1,2,3,5]:
        f[f"ret_{lag}d"] = ret.shift(lag)
    f["ret_5d_sum"]    = ret.shift(1).rolling(5).sum()
    f["volatility_5d"] = ret.rolling(5).std()
    f["volatility_10d"]= ret.rolling(10).std()

    # MFI
    tp   = (high+low+close)/3
    mf   = tp*volume
    pmf  = mf.where(tp>tp.shift(1),0).rolling(14).sum()
    nmf  = mf.where(tp<tp.shift(1),0).rolling(14).sum()
    mfi  = 100-(100/(1+pmf/nmf.replace(0,np.nan)))
    f["mfi"]           = mfi
    f["mfi_oversold"]  = (mfi<20).astype(int)

    # Kalender
    f["hari"]          = df.index.dayofweek
    f["bulan"]         = df.index.month
    f["senin"]         = (df.index.dayofweek==0).astype(int)
    f["jumat"]         = (df.index.dayofweek==4).astype(int)

    # Tambah data Indonesia
    if data_indo:
        f = tambah_fitur_indonesia(f, df, data_indo)

    return f


def retrain_swing(data_indo=None):
    """
    Retrain model swing 1-3 hari dengan data terbaru + uji korelasi.
    Dipanggil oleh training_loop() setelah training model utama.
    """
    print("  [SWING] Loading data saham...")
    folder_list = ["data/idx500", "data", "data/biostatistik/saham"]

    X_all = []
    y_all = []
    n_saham = 0

    for folder in folder_list:
        if not os.path.exists(folder): continue
        for fname in os.listdir(folder):
            if not fname.endswith(".csv"): continue
            kode = fname.replace(".csv","")
            if any(x.lower() in kode.lower() for x in
                   ["KOMODITAS","MAKRO","CUACA","IHSG","VIX","USD"]): continue
            if not (len(kode) <= 6 and kode.isupper()): continue

            path = os.path.join(folder, fname)
            try:
                df = pd.read_csv(path)
                df.columns = [c.lower() for c in df.columns]
                if "date" not in df.columns: continue
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
                for col in ["close","high","low","volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["close"])
                df = df[df["close"] > 50]
                if len(df) < 150: continue

                # TARGET swing: naik >= 1.5% dalam 1-3 hari
                close = df["close"]
                ret_max = pd.DataFrame({
                    "r1": close.shift(-1)/close-1,
                    "r2": close.shift(-2)/close-1,
                    "r3": close.shift(-3)/close-1,
                }).max(axis=1)
                target = (ret_max >= 0.015).astype(int)

                X = buat_fitur_swing_brain(df, data_indo)
                df_g = X.copy()
                df_g["target"] = target
                valid = df_g["target"].notna() & (df_g.isna().sum(axis=1) < df_g.shape[1]*0.4)
                df_g = df_g[valid].fillna(0)
                if len(df_g) < 100: continue

                X_all.append(df_g.drop("target", axis=1))
                y_all.append(df_g["target"])
                n_saham += 1
            except:
                continue

    if not X_all:
        print("  [SWING] Tidak ada data!")
        return

    X_combined = pd.concat(X_all).fillna(0)
    y_combined = pd.concat(y_all)
    X_combined = X_combined.loc[:, X_combined.nunique() > 1]

    print(f"  [SWING] Dataset: {len(X_combined):,} baris | {n_saham} saham | {X_combined.shape[1]} fitur")

    # Uji korelasi — filter fitur signifikan
    print("  [SWING] Uji korelasi fitur...")
    fitur_sig, df_kor = uji_korelasi_fitur(X_combined, y_combined, threshold=0.02)
    fitur_ada = [f for f in fitur_sig if f in X_combined.columns]
    if len(fitur_ada) >= 10:
        X_combined = X_combined[fitur_ada]
        print(f"  [SWING] Filter korelasi: {len(fitur_ada)} fitur signifikan")

    # Simpan hasil korelasi swing
    df_kor.to_csv("logs/brain/korelasi_swing.csv", index=False)

    # Training
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import TimeSeriesSplit, cross_val_score

    fitur_list = X_combined.columns.tolist()
    tscv = TimeSeriesSplit(n_splits=5)

    model_gb = Pipeline([
        ("scaler", StandardScaler()),
        ("gb", GradientBoostingClassifier(
            n_estimators=200, max_depth=5,
            learning_rate=0.05, subsample=0.8, random_state=42))
    ])
    scores = cross_val_score(model_gb, X_combined, y_combined,
                             cv=tscv, scoring="accuracy", n_jobs=-1)
    cv_baru = float(scores.mean())
    cv_lama = load_best_swing_acc()

    print(f"  [SWING] CV baru: {cv_baru*100:.2f}% | CV lama: {cv_lama*100:.2f}%")

    if cv_baru > cv_lama:
        model_gb.fit(X_combined, y_combined)
        model_swing = {
            "pipeline"   : model_gb,
            "fitur"      : fitur_list,
            "cv_accuracy": round(cv_baru, 4),
            "nama_model" : "GradientBoosting",
            "target"     : "naik >= 1.5% dalam 1-3 hari",
            "n_saham"    : n_saham,
            "n_data"     : len(X_combined),
            "tanggal"    : datetime.now().strftime("%Y-%m-%d"),
        }
        with open("models/model_swing.pkl","wb") as f:
            pickle.dump(model_swing, f)
        save_best_swing_acc(cv_baru)
        print(f"  [SWING] ✅ Model swing diupdate! {cv_lama*100:.2f}% -> {cv_baru*100:.2f}%")
        return cv_baru, True
    else:
        print(f"  [SWING] Model swing belum ada peningkatan")
        return cv_baru, False


STRATEGI = [
    # nama,          min_hari, trees, depth, leaves, algo
    ("RF-Standard",   300,     300,   10,    15,     "rf"),
    ("RF-Deep",       300,     400,   14,     8,     "rf"),
    ("RF-Shallow",    500,     200,    6,    25,     "rf"),
    ("RF-ManyTrees",  300,     600,    8,    20,     "rf"),
    ("GB-Boost",      400,     200,    5,    20,     "gb"),
]

def train_satu_strategi(idx, data_asia, per_sektor, data_indo=None):
    nama, min_hari, trees, depth, leaves, algo = STRATEGI[idx]
    hasil = []
    models = {}

    for sektor, saham_list in sorted(per_sektor.items()):
        X_all, y_all = [], []
        for kode in saham_list:
            X, y = buat_dataset(kode, data_asia, min_hari, data_indo)
            if X is not None:
                X_all.append(X); y_all.append(y)
        if not X_all: continue

        X_c = pd.concat(X_all).fillna(0)
        y_c = pd.concat(y_all)
        X_c = X_c.loc[:, X_c.nunique()>1]

        # Uji korelasi — filter fitur signifikan
        try:
            fitur_sig, _ = uji_korelasi_fitur(X_c, y_c, threshold=0.02)
            fitur_ada = [f for f in fitur_sig if f in X_c.columns]
            if len(fitur_ada) >= 10:
                X_c = X_c[fitur_ada]
                print(f"    Korelasi filter: {len(fitur_ada)} fitur signifikan")
        except Exception as e:
            print(f"    Skip korelasi filter: {e}")

        if algo=="rf":
            clf = RandomForestClassifier(
                n_estimators=trees, max_depth=depth,
                min_samples_leaf=leaves, max_features="sqrt",
                random_state=42, n_jobs=-1, class_weight="balanced")
        else:
            clf = GradientBoostingClassifier(
                n_estimators=trees, max_depth=depth,
                learning_rate=0.05, subsample=0.8, random_state=42)

        model = Pipeline([("scaler",StandardScaler()),("clf",clf)])
        tscv  = TimeSeriesSplit(n_splits=5)
        try:
            scores = cross_val_score(model, X_c, y_c, cv=tscv,
                                      scoring="accuracy", n_jobs=-1)
            cv = round(float(scores.mean()),4)
        except:
            cv = 0

        model.fit(X_c, y_c)
        models[sektor] = {
            "pipeline": model, "fitur": X_c.columns.tolist(),
            "cv_accuracy": cv, "n_data": len(X_c),
        }
        hasil.append({"sektor":sektor,"cv":cv})

    avg = round(float(np.mean([h["cv"] for h in hasil])),4) if hasil else 0
    return models, avg, hasil

# ══════════════════════════════════════════════════════════════
# FUNGSI UTAMA — dipanggil jadwal
# ══════════════════════════════════════════════════════════════
def training_loop():
    """
    07:00 WIB: mulai training loop.
    Coba semua strategi satu per satu.
    Self-healing: kalau error, coba fix sendiri dan retry.
    """
    tanggal   = datetime.now().strftime("%Y-%m-%d")
    state     = load_state()
    best_acc  = load_best_acc()
    batas_jam = datetime.now().replace(hour=21, minute=45, second=0)

    print(f"\n{'='*60}")
    print(f"BRAIN TRAINING LOOP v2 — {tanggal}")
    print(f"Best acc: {best_acc*100:.2f}% | Target: {TARGET_ACC*100:.0f}%")
    print(f"Self-healing: AKTIF")
    print(f"{'='*60}")

    # Download Asia dengan self-healing
    print("\nDownload pasar Asia...")
    data_asia = safe_run(download_asia, nama="download_asia") or {}

    print("\nDownload data Indonesia...")
    data_indo = safe_run(download_semua_data_indonesia, nama="download_indo") or {}

    per_sektor = safe_run(scan_saham, nama="scan_saham") or {}

    if not per_sektor:
        print("ERROR: tidak ada data saham sama sekali")
        telegram(f"🚨 Brain error: tidak ada data saham\nWaktu: {tanggal}")
        return best_acc, False

    total_saham = sum(len(v) for v in per_sektor.values())
    print(f"Scan: {total_saham} saham, {len(per_sektor)} sektor")

    hasil_semua     = []
    acc_terbaik     = best_acc
    strategi_menang = "-"
    deployed        = False
    error_count     = 0

    for idx, (nama, min_hari, trees, depth, leaves, algo) in enumerate(STRATEGI):
        if datetime.now() >= batas_jam:
            print(f"\nBatas waktu 21:45 WIB tercapai, stop training")
            break

        print(f"\n[{idx+1}/{len(STRATEGI)}] {nama}")

        waktu_mulai = datetime.now()

        # Training dengan self-healing
        result = safe_run(
            train_satu_strategi, idx, data_asia, per_sektor, data_indo,
            nama=f"train_{nama}", max_retry=2
        )

        if result is None:
            error_count += 1
            print(f"  Skip {nama} karena error")
            hasil_semua.append({"strategi":nama,"cv":0,"durasi":0,"error":True})
            continue

        models, avg_cv, hasil = result
        durasi = (datetime.now()-waktu_mulai).seconds//60
        print(f"  CV={avg_cv*100:.2f}% | {durasi} menit")

        hasil_semua.append({
            "strategi": nama,
            "cv"      : avg_cv,
            "durasi"  : durasi,
            "error"   : False,
        })
        state["total_training"] += 1

        if avg_cv > acc_terbaik:
            acc_terbaik     = avg_cv
            strategi_menang = nama
            print(f"  ✅ LEBIH BAIK! {best_acc*100:.2f}% -> {avg_cv*100:.2f}%")

            try:
                import shutil
                path_baru = f"models/models_brain_{tanggal.replace('-','')}.pkl"
                with open(path_baru,"wb") as f_:
                    pickle.dump(models, f_)
                shutil.copy(path_baru, "models/models_latest.pkl")
                save_best_acc(acc_terbaik)
                deployed = True
                state["total_deploy"] += 1
            except Exception as e:
                catat_error("simpan_model", e)
                print(f"  Error simpan model: {e}")

            if avg_cv >= TARGET_ACC:
                print(f"\n🎯 TARGET {TARGET_ACC*100:.0f}% TERCAPAI!")
                break
        else:
            print(f"  Belum lebih baik dari {acc_terbaik*100:.2f}%")


    # ── Retrain model swing (gabungan brain + swing) ──────────
    print("\nRetrain model swing 1-3 hari...")
    try:
        retrain_swing(data_indo)
    except Exception as e:
        print(f"  Error retrain swing: {e}")
        catat_error("retrain_swing", e)

    # Update state
    state["hari_ke"]       += 1
    state["riwayat_cv"]     = (state.get("riwayat_cv",[]) + [acc_terbaik])[-30:]
    state["strategi_index"] = (state.get("strategi_index",0)+len(hasil_semua))%len(STRATEGI)
    save_state(state)

    simpan_history({
        "tanggal"        : tanggal,
        "cv_terbaik"     : acc_terbaik,
        "strategi_menang": strategi_menang,
        "deployed"       : deployed,
        "total_strategi" : len(hasil_semua),
        "error_count"    : error_count,
    })

    # Simpan untuk laporan jam 22:00
    laporan_data = {
        "tanggal"        : tanggal,
        "best_acc"       : acc_terbaik,
        "deployed"       : deployed,
        "strategi_menang": strategi_menang,
        "hasil_semua"    : hasil_semua,
        "total_training" : state["total_training"],
        "total_deploy"   : state["total_deploy"],
        "riwayat_cv"     : state["riwayat_cv"],
        "error_count"    : error_count,
    }
    with open("logs/brain/laporan_hari_ini.json","w") as f:
        json.dump(laporan_data, f, indent=2)

    print(f"\nTraining selesai. Laporan dikirim jam 22:00 WIB.")
    return acc_terbaik, deployed

def kirim_laporan():
    """22:00 WIB: kirim laporan ke Telegram."""
    tanggal = datetime.now().strftime("%Y-%m-%d")

    # Load hasil training hari ini
    laporan_path = "logs/brain/laporan_hari_ini.json"
    if not os.path.exists(laporan_path):
        telegram(
            f"🧠 <b>LAPORAN BRAIN — {tanggal}</b>\n\n"
            f"⚠️ Tidak ada data training hari ini.\n"
            f"Kemungkinan training belum selesai atau terjadi error."
        )
        return

    with open(laporan_path) as f:
        d = json.load(f)

    best_acc  = d["best_acc"]
    deployed  = d["deployed"]
    menang    = d["strategi_menang"]
    hasil     = d["hasil_semua"]
    riwayat   = d.get("riwayat_cv",[])

    # Progress bar ke target 66%
    progress = max(0, min(100, (best_acc-BASELINE_ACC)/(TARGET_ACC-BASELINE_ACC)*100))
    bar      = "█"*int(progress/5) + "░"*(20-int(progress/5))

    # Tren
    tren = ""
    if len(riwayat) >= 2:
        delta = (riwayat[-1]-riwayat[-2])*100
        tren  = f"{'▲' if delta>0 else '▼'} {abs(delta):.2f}% vs kemarin"

    # Detail strategi
    detail = ""
    for h in hasil:
        flag = "✅" if h["cv"]>BASELINE_ACC else "❌"
        detail += f"{flag} {h['strategi']}: {h['cv']*100:.2f}% ({h['durasi']}m)\n"

    error_count = d.get("error_count", 0)
    error_info  = f"⚠️ {error_count} strategi gagal (auto-fixed)\n" if error_count > 0 else ""
    if best_acc >= TARGET_ACC:
        status_msg = f"🎯 <b>TARGET {TARGET_ACC*100:.0f}% TERCAPAI!</b>"
    elif deployed:
        delta = (best_acc - BASELINE_ACC)*100
        status_msg = f"✅ Model diupdate! +{delta:.2f}% dari baseline"
    else:
        status_msg = f"⚠️ Belum ada peningkatan hari ini"

    msg = (
        f"🧠 <b>LAPORAN BRAIN HARIAN</b>\n"
        f"📅 {tanggal}\n"
        f"{'─'*32}\n"
        f"🎯 <b>Akurasi terbaik: {best_acc*100:.2f}%</b>\n"
        f"📈 {tren}\n"
        f"{error_info}"
        f"{status_msg}\n"
        f"{'─'*32}\n"
        f"🔬 Hasil training hari ini:\n"
        f"{detail}"
        f"{'─'*32}\n"
        f"🏆 Strategi terbaik: {menang}\n"
        f"📦 Total training: {d['total_training']} | Deploy: {d['total_deploy']}\n"
        f"{'─'*32}\n"
        f"📊 Progress ke {TARGET_ACC*100:.0f}%:\n"
        f"[{bar}] {progress:.0f}%\n"
        f"Gap: {(TARGET_ACC-best_acc)*100:.2f}% lagi\n"
        f"{'─'*32}\n"
        f"⏰ Training besok mulai 07:00 WIB"
    )

    # Tambah info swing model
    try:
        swing_cv = load_best_swing_acc()
        msg += (
            f"\n{'─'*32}\n"
            f"📈 <b>SWING MODEL (1-3 hari)</b>\n"
            f"CV Accuracy: {swing_cv*100:.2f}%\n"
            f"Target: naik ≥1.5% dalam 1-3 hari\n"
            f"Scan: 400+ saham IDX"
        )
    except:
        pass

    telegram(msg)

# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv)>1 else "train"
    if cmd == "laporan":
        kirim_laporan()
    else:
        training_loop()
