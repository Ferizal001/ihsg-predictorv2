import yfinance as yf
import pandas as pd
import os

os.makedirs("data", exist_ok=True)

# Daftar 50 saham IDX paling aktif
SAHAM_IDX = [
    "ADRO","PTBA","ITMG","INCO","ANTM","TINS","MEDC","PGAS",
    "BBRI","BMRI","BBCA","BBNI","BRIS","BNGA","BBTN","ARTO",
    "TLKM","EXCL","ISAT","TOWR",
    "UNVR","ICBP","MYOR","SIDO","KLBF","KAEF","SIDO","CPIN",
    "AALI","SIMP","LSIP","PALM",
    "ASII","AUTO","SMSM","INDF","UNTR","PNBN",
    "GOTO","EMTK","BUKA","MTEL","DMMX",
    "SMGR","INTP","WIKA","PTPP","WSKT","ADHI",
]

print(f"Download data {len(SAHAM_IDX)} saham IDX...")
print("Ini butuh 3-5 menit, mohon tunggu...\n")

berhasil = 0
gagal    = 0

for kode in SAHAM_IDX:
    ticker = f"{kode}.JK"
    try:
        df = yf.download(ticker, period="3y", progress=False)
        if len(df) > 50:
            df.columns = [c.lower() for c in df.columns]
            df.to_csv(f"data/{kode}.csv")
            print(f"  ✓ {kode:6s} — {len(df)} hari data")
            berhasil += 1
        else:
            print(f"  ✗ {kode:6s} — data kurang")
            gagal += 1
    except Exception as e:
        print(f"  ✗ {kode:6s} — error: {e}")
        gagal += 1

print(f"\n{'='*40}")
print(f"Selesai! Berhasil: {berhasil} | Gagal: {gagal}")
print(f"Data tersimpan di folder: data/")
