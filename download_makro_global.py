#!/usr/bin/env python3
"""
download_makro_global.py
========================
Download 50 data makro harian (komoditas + kurs + indeks global)
dan uji korelasi ke pergerakan IHSG.

Sumber: Yahoo Finance (gratis, otomatis)
Kategori:
  - Komoditas utama Indonesia & global (no. 46-70)
  - Kurs mata uang (no. 71-80)
  - Indeks saham global & regional (no. 81-95)
  - Faktor eksternal (no. 96-100)
"""

import os, warnings, time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy import stats

warnings.filterwarnings("ignore")
os.makedirs("data/makro", exist_ok=True)
os.makedirs("logs", exist_ok=True)

# ── DAFTAR 50 TICKER ─────────────────────────────────────────
MAKRO = {
    # === KOMODITAS (46-70) ===
    "minyak_brent"      : "BZ=F",
    "minyak_wti"        : "CL=F",
    "cpo"               : "FCPO.KL",     # CPO Bursa Malaysia
    "batubara"          : "MTF=F",       # Newcastle coal futures
    "nikel"             : "NI=F",
    "timah"             : "SN=F",
    "emas"              : "GC=F",
    "perak"             : "SI=F",
    "tembaga"           : "HG=F",
    "gas_alam"          : "NG=F",
    "kopi"              : "KC=F",
    "gula"              : "SB=F",
    "kedelai"           : "ZS=F",
    "jagung"            : "ZC=F",
    "beras"             : "ZR=F",
    "baja_hrc"          : "HR=F",        # Hot rolled coil steel

    # === KURS (71-80) ===
    "usd_idr"           : "IDR=X",
    "eur_idr"           : "EURIDR=X",
    "jpy_idr"           : "JPYIDR=X",
    "cny_idr"           : "CNYIDR=X",
    "sgd_idr"           : "SGDIDR=X",
    "dxy"               : "DX-Y.NYB",   # Indeks dolar AS
    "eur_usd"           : "EURUSD=X",
    "usd_cny"           : "USDCNY=X",
    "usd_jpy"           : "USDJPY=X",
    "emerging_fx"       : "CEW",         # ETF Emerging market FX

    # === INDEKS SAHAM GLOBAL (81-95) ===
    "sp500"             : "^GSPC",
    "dow_jones"         : "^DJI",
    "nasdaq"            : "^IXIC",
    "nikkei"            : "^N225",
    "hang_seng"         : "^HSI",
    "shanghai"          : "000001.SS",
    "kospi"             : "^KS11",
    "sti_singapore"     : "^STI",
    "ftse100"           : "^FTSE",
    "dax"               : "^GDAXI",
    "asx200"            : "^AXJO",
    "sensex"            : "^BSESN",
    "vix"               : "^VIX",
    "msci_em"           : "EEM",         # ETF MSCI Emerging Markets
    "msci_world"        : "URTH",        # ETF MSCI World

    # === FAKTOR EKSTERNAL (96-100) ===
    "us_10yr_yield"     : "^TNX",        # US Treasury 10Y yield
    "us_2yr_yield"      : "^IRX",        # US Treasury 2Y
    "gold_silver_ratio" : None,          # dihitung dari emas/perak
    "fear_greed_proxy"  : "^VIX",        # VIX sebagai proxy fear
    "oil_gas_ratio"     : None,          # dihitung dari minyak/gas
}

# ── DOWNLOAD DATA ─────────────────────────────────────────────
def download_yfinance(ticker, nama, period="2y"):
    """Download data dari Yahoo Finance tanpa library yfinance."""
    import urllib.request, json, ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE

    end   = int(datetime.now().timestamp())
    start = int((datetime.now() - timedelta(days=730)).timestamp())

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={start}&period2={end}&interval=1d"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        r   = urllib.request.urlopen(req, timeout=15, context=ctx)
        data= json.loads(r.read())

        result = data["chart"]["result"][0]
        ts     = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]

        df = pd.DataFrame({
            "date" : pd.to_datetime(ts, unit="s").strftime("%Y-%m-%d"),
            "close": closes,
        }).dropna()

        df.to_csv(f"data/makro/{nama}.csv", index=False)
        return df
    except Exception as e:
        return None

print("="*65)
print("DOWNLOAD DATA MAKRO GLOBAL (50 indikator)")
print("Komoditas + Kurs + Indeks Global + Faktor Eksternal")
print("="*65)

berhasil = []
gagal    = []

for nama, ticker in MAKRO.items():
    if ticker is None:
        continue  # akan dihitung manual nanti
    df = download_yfinance(ticker, nama)
    if df is not None and len(df) > 100:
        print(f"  ✓ {nama:<25} {len(df)} hari | last: {df['close'].iloc[-1]:.4f}")
        berhasil.append(nama)
    else:
        print(f"  ✗ {nama:<25} gagal ({ticker})")
        gagal.append(nama)
    time.sleep(0.3)

# Hitung derived indicators
print("\n  Hitung derived indicators...")
try:
    df_emas  = pd.read_csv("data/makro/emas.csv").set_index("date")
    df_perak = pd.read_csv("data/makro/perak.csv").set_index("date")
    df_gs    = (df_emas["close"] / df_perak["close"]).reset_index()
    df_gs.columns = ["date", "close"]
    df_gs.to_csv("data/makro/gold_silver_ratio.csv", index=False)
    berhasil.append("gold_silver_ratio")
    print(f"  ✓ gold_silver_ratio    dihitung dari emas/perak")
except: pass

try:
    df_oil = pd.read_csv("data/makro/minyak_wti.csv").set_index("date")
    df_gas = pd.read_csv("data/makro/gas_alam.csv").set_index("date")
    df_og  = (df_oil["close"] / df_gas["close"]).reset_index()
    df_og.columns = ["date", "close"]
    df_og.to_csv("data/makro/oil_gas_ratio.csv", index=False)
    berhasil.append("oil_gas_ratio")
    print(f"  ✓ oil_gas_ratio        dihitung dari minyak/gas")
except: pass

print(f"\n  Berhasil: {len(berhasil)} | Gagal: {len(gagal)}")
if gagal:
    print(f"  Gagal: {', '.join(gagal)}")

# ── UJI KORELASI KE IHSG ─────────────────────────────────────
print(f"\n{'='*65}")
print("UJI KORELASI DATA MAKRO GLOBAL vs IHSG")
print("="*65)

# Load proxy IHSG (pakai BBCA atau BBRI sebagai proxy)
ihsg = None
for proxy in ["data/BBCA.csv","data/BBRI.csv","data/BMRI.csv"]:
    if os.path.exists(proxy):
        df = pd.read_csv(proxy)
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.set_index("date").sort_index()
        ihsg = df["close"].pct_change().dropna()
        print(f"  Proxy IHSG: {proxy}")
        break

if ihsg is None:
    # Pakai IHSG dari idx500
    for proxy in ["data/idx500/BBCA.csv","data/idx500/BBRI.csv"]:
        if os.path.exists(proxy):
            df = pd.read_csv(proxy)
            df.columns = [c.lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df.set_index("date").sort_index()
            ihsg = df["close"].pct_change().dropna()
            print(f"  Proxy IHSG: {proxy}")
            break

if ihsg is None:
    print("ERROR: Tidak ada data IHSG proxy!")
    exit()

# Uji korelasi semua variabel
hasil = []

print(f"\n{'Variabel':<25} {'Pearson':>8} {'p-val':>8} {'Spearman':>9} {'Lag1_r':>8} {'Signifikan'}")
print("─"*75)

for nama in berhasil:
    path = f"data/makro/{nama}.csv"
    if not os.path.exists(path):
        continue
    try:
        df = pd.read_csv(path)
        df["date"]  = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.set_index("date").sort_index()
        seri = df["close"].pct_change().dropna()

        # Align
        gabung = pd.concat([ihsg, seri], axis=1).dropna()
        gabung.columns = ["ihsg", nama]
        if len(gabung) < 30:
            continue

        # Pearson & Spearman (same day)
        r_p, p_p = stats.pearsonr(gabung["ihsg"], gabung[nama])
        r_s, _   = stats.spearmanr(gabung["ihsg"], gabung[nama])

        # Lag 1 (kemarin vs hari ini)
        gabung_lag = pd.concat([ihsg, seri.shift(1)], axis=1).dropna()
        gabung_lag.columns = ["ihsg", nama]
        r_lag, p_lag = stats.pearsonr(gabung_lag["ihsg"], gabung_lag[nama])

        sig = "✅" if p_p < 0.05 else ("⚡" if p_lag < 0.05 else "❌")

        print(f"{nama:<25} {r_p:>+8.4f} {p_p:>8.4f} {r_s:>+9.4f} {r_lag:>+8.4f}  {sig}")

        hasil.append({
            "variabel"      : nama,
            "pearson_r"     : round(r_p, 4),
            "pearson_p"     : round(p_p, 4),
            "spearman_r"    : round(r_s, 4),
            "lag1_r"        : round(r_lag, 4),
            "lag1_p"        : round(p_lag, 4),
            "n"             : len(gabung),
            "signifikan_d0" : p_p < 0.05,
            "signifikan_d1" : p_lag < 0.05,
        })
    except Exception as e:
        continue

print("─"*75)
print("Ket: ✅ = signifikan hari ini | ⚡ = signifikan lag-1 | ❌ = tidak signifikan")

# Simpan & rangkuman
df_hasil = pd.DataFrame(hasil)
if len(df_hasil) > 0:
    df_hasil = df_hasil.sort_values("pearson_r", key=abs, ascending=False)
    df_hasil.to_csv("logs/korelasi_makro_global.csv", index=False)

    sig_d0 = df_hasil[df_hasil["signifikan_d0"]]
    sig_d1 = df_hasil[df_hasil["signifikan_d1"]]

    print(f"\n{'='*65}")
    print("KESIMPULAN:")
    print(f"  Total diuji          : {len(df_hasil)} variabel")
    print(f"  Signifikan hari ini  : {len(sig_d0)} variabel")
    print(f"  Signifikan lag-1     : {len(sig_d1)} variabel")

    if len(sig_d0) > 0:
        print(f"\n  TOP SIGNIFIKAN (korelasi hari ini):")
        for _, r in sig_d0.head(10).iterrows():
            arah = "📈 POSITIF" if r["pearson_r"] > 0 else "📉 NEGATIF"
            print(f"    {r['variabel']:<25} r={r['pearson_r']:+.4f} {arah}")

    if len(sig_d1) > 0:
        print(f"\n  TOP SIGNIFIKAN (lag-1, prediktif):")
        for _, r in sig_d1.head(10).iterrows():
            arah = "📈 POSITIF" if r["lag1_r"] > 0 else "📉 NEGATIF"
            print(f"    {r['variabel']:<25} r={r['lag1_r']:+.4f} {arah}")

    print(f"\n  Hasil lengkap: logs/korelasi_makro_global.csv")

    # Rekomendasi untuk model
    layak = df_hasil[df_hasil["signifikan_d0"] | df_hasil["signifikan_d1"]]
    if len(layak) > 0:
        print(f"\n  VARIABEL LAYAK MASUK MODEL ({len(layak)}):")
        print(f"  {', '.join(layak['variabel'].tolist())}")
        layak[["variabel","pearson_r","lag1_r"]].to_csv(
            "logs/makro_layak_model.csv", index=False)
        print(f"  Disimpan: logs/makro_layak_model.csv")
    else:
        print(f"\n  Belum ada yang signifikan — butuh lebih banyak data")

print(f"\n{'='*65}")
print("SELESAI!")
print(f"  Data tersimpan : data/makro/ ({len(berhasil)} file)")
print(f"  Korelasi       : logs/korelasi_makro_global.csv")
print("="*65)
