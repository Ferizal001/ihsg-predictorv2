"""
scoring_dengan_berita.py
Scoring harian dengan sentimen berita real-time
Jalankan setiap pagi setelah jam 09:00
"""
import pandas as pd, numpy as np, os, pickle
from datetime import datetime
import requests
from xml.etree import ElementTree as ET

# ── Kamus sentimen ────────────────────────────────────────────
POSITIF = [
    "naik","tumbuh","meningkat","rekor","tertinggi","laba","untung",
    "dividen","akuisisi","kontrak","ekspansi","investasi","rally",
    "bullish","upgrade","buy","profit","surplus","optimis","pulih",
    "top gainer","menguat","apresiasi","solid","positif","bertumbuh",
    "capex","right issue","buyback","stock split","bonus saham",
]
NEGATIF = [
    "turun","merosot","anjlok","rugi","kerugian","bangkrut","pailit",
    "suspensi","delisting","gagal","default","korupsi","kasus",
    "bearish","downgrade","sell","tekanan","krisis","inflasi",
    "resesi","perang","bencana","banjir","kebakaran","longsor",
    "penyelidikan","tersangka","penyidikan","pembekuan","sanksi",
]

SAHAM = [
    "BBCA","BBRI","BMRI","BBNI","BRIS","BNGA","BBTN","ARTO","PNBN",
    "TLKM","EXCL","ISAT","TOWR","MTEL","TBIG","LINK",
    "ADRO","PTBA","ITMG","INCO","ANTM","TINS","MEDC","HRUM","MDKA",
    "UNVR","ICBP","MYOR","KLBF","KAEF","CPIN","SIDO","GGRM","HMSP",
    "AALI","SIMP","LSIP",
    "ASII","AUTO","SMSM","UNTR",
    "SMGR","INTP","WIKA","PTPP","WSKT","ADHI",
    "GOTO","EMTK","BUKA","DMMX",
    "AKRA","PGAS","ESSA","ELSA",
    "SMRA","BSDE","CTRA","PWON","LPKR",
    "ACES","MAPI","LPPF","RALS",
    "MIKA","SILO","HEAL",
    "SCMA","MNCN",
]

SEKTOR_SAHAM = {
    "BBCA":"perbankan","BBRI":"perbankan","BMRI":"perbankan","BBNI":"perbankan",
    "BRIS":"perbankan","BNGA":"perbankan","BBTN":"perbankan","PNBN":"perbankan",
    "TLKM":"telekomunikasi","EXCL":"telekomunikasi","ISAT":"telekomunikasi",
    "TOWR":"telekomunikasi","MTEL":"telekomunikasi","TBIG":"telekomunikasi",
    "ADRO":"tambang","PTBA":"tambang","ITMG":"tambang","ANTM":"tambang",
    "INCO":"tambang","TINS":"tambang","MEDC":"tambang","HRUM":"tambang","MDKA":"tambang",
    "UNVR":"konsumer","ICBP":"konsumer","MYOR":"konsumer","KLBF":"konsumer",
    "CPIN":"konsumer","GGRM":"konsumer","HMSP":"konsumer","KAEF":"konsumer",
    "AALI":"agribisnis","SIMP":"agribisnis","LSIP":"agribisnis",
    "SMGR":"properti","BSDE":"properti","CTRA":"properti","PWON":"properti",
    "SMRA":"properti","LPKR":"properti","WIKA":"properti","PTPP":"properti",
    "MIKA":"kesehatan","SILO":"kesehatan","HEAL":"kesehatan",
    "PGAS":"energi","AKRA":"energi","ESSA":"energi","ELSA":"energi",
    "SCMA":"media","MNCN":"media","EMTK":"media",
    "ACES":"ritel","MAPI":"ritel","LPPF":"ritel","RALS":"ritel",
}

def ambil_sentimen_berita():
    SUMBER = {
        "IDX Channel"   : "https://www.idxchannel.com/rss",
        "CNBC Indonesia": "https://www.cnbcindonesia.com/rss",
        "Detik Finance" : "https://finance.detik.com/rss",
    }
    skor_saham  = {}
    skor_sektor = {}
    skor_global = 0
    total_berita = 0

    for nama_sumber, url in SUMBER.items():
        try:
            r    = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            root = ET.fromstring(r.text)
            items = root.findall(".//item")
            total_berita += len(items)
            for item in items:
                judul = item.find("title")
                if judul is None:
                    continue
                teks = judul.text.upper()
                skor = 0
                for k in POSITIF:
                    if k.upper() in teks:
                        skor += 1
                for k in NEGATIF:
                    if k.upper() in teks:
                        skor -= 1
                skor_global += skor
                saham_disebut = [s for s in SAHAM if s in teks]
                for s in saham_disebut:
                    skor_saham[s]  = skor_saham.get(s, 0) + skor
                    sektor = SEKTOR_SAHAM.get(s, "lainnya")
                    skor_sektor[sektor] = skor_sektor.get(sektor, 0) + skor
        except:
            pass

    return skor_saham, skor_sektor, skor_global, total_berita

def hitung_skor_teknikal(df):
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta).clip(lower=0).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb    = (close - (sma20 - 2*std20)) / (4*std20).replace(0, np.nan)

    vol_ratio = volume / volume.rolling(20).mean().replace(0, np.nan)

    # Normalisasi ke 0-100
    rsi_n  = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
    macd_n = 50 + float(macd.iloc[-1]) * 1000 if not pd.isna(macd.iloc[-1]) else 50
    bb_n   = float(bb.iloc[-1]) * 100 if not pd.isna(bb.iloc[-1]) else 50
    vol_n  = min(100, float(vol_ratio.iloc[-1]) * 50) if not pd.isna(vol_ratio.iloc[-1]) else 50

    macd_n = max(0, min(100, macd_n))
    bb_n   = max(0, min(100, bb_n))

    skor = (rsi_n * 0.3 + macd_n * 0.3 + bb_n * 0.2 + vol_n * 0.2)
    return round(skor, 1), round(rsi_n, 1)

# ── Main scoring ──────────────────────────────────────────────
def main():
    tanggal = datetime.now().strftime("%Y-%m-%d")
    print(f"SCORING HARIAN DENGAN BERITA — {tanggal}")
    print("="*60)

    # 1. Ambil sentimen berita
    print("1. Ambil sentimen berita real-time...")
    skor_saham, skor_sektor, skor_global, total = ambil_sentimen_berita()
    print(f"   {total} berita dianalisis")
    print(f"   Skor global pasar: {skor_global:+d}")

    if skor_global > 3:
        sentimen_global = "POSITIF"
        bobot_berita    = 1.1
    elif skor_global < -3:
        sentimen_global = "NEGATIF"
        bobot_berita    = 0.9
    else:
        sentimen_global = "NETRAL"
        bobot_berita    = 1.0

    print(f"   Sentimen global: {sentimen_global}")

    # 2. Muat model
    print("2. Muat model...")
    try:
        with open("models/models_latest.pkl","rb") as f:
            models = pickle.load(f)
        print(f"   {len(models)} model sektor dimuat")
    except:
        print("   ERROR: model tidak ditemukan")
        return

    # 3. Scoring per saham
    print("3. Hitung skor per saham...")
    hasil = []
    for fname in os.listdir("data"):
        if not fname.endswith(".csv") or fname.startswith("KOMODITAS"):
            continue
        kode = fname.replace(".csv","")
        try:
            df = pd.read_csv(f"data/{fname}")
            df.columns = [c.lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()

            if len(df) < 50:
                continue
            if df["close"].iloc[-1] < 100:
                continue
            if df["close"].iloc[-1] * df["volume"].iloc[-1] < 500_000_000:
                continue
            if "high" not in df.columns:
                continue

            skor_tek, rsi = hitung_skor_teknikal(df)
            sektor = SEKTOR_SAHAM.get(kode, "lainnya")

            # Skor berita per saham
            skor_berita_saham  = skor_saham.get(kode, 0)
            skor_berita_sektor = skor_sektor.get(sektor, 0)
            skor_berita_total  = skor_berita_saham * 3 + skor_berita_sektor

            # Normalisasi skor berita ke 0-100
            skor_berita_norm = 50 + min(20, max(-20, skor_berita_total * 5))

            # Proba dari model
            model_sektor = models.get(sektor, models.get("lainnya"))
            proba = 0.5
            if model_sektor:
                try:
                    fitur = model_sektor["fitur"]
                    # Ambil fitur yang tersedia
                    X = pd.DataFrame([{f: 0 for f in fitur}])
                    proba = float(model_sektor["pipeline"].predict_proba(X)[0][1])
                except:
                    proba = 0.5

            # Skor final gabungan
            skor_final = (
                skor_tek          * 0.40 +
                skor_berita_norm  * 0.30 +
                proba * 100       * 0.30
            ) * bobot_berita

            skor_final = round(min(100, max(0, skor_final)), 1)

            if skor_final >= 75:
                sinyal = "BELI"
            elif skor_final >= 55:
                sinyal = "PANTAU"
            else:
                sinyal = "SKIP"

            hasil.append({
                "ticker"        : kode,
                "sektor"        : sektor,
                "skor_final"    : skor_final,
                "skor_teknikal" : skor_tek,
                "skor_berita"   : skor_berita_norm,
                "skor_berita_raw": skor_berita_total,
                "proba_naik"    : round(proba, 3),
                "rsi"           : rsi,
                "sinyal"        : sinyal,
            })
        except:
            pass

    df_hasil = pd.DataFrame(hasil).sort_values("skor_final", ascending=False)
    df_hasil.to_csv(f"logs/ranking_berita_{tanggal}.csv", index=False)

    # 4. Tampilkan hasil
    print(f"\nTOP 10 SAHAM HARI INI ({tanggal}):")
    print(f"{'Rank':4} {'Ticker':6} {'Skor':6} {'Sinyal':8} {'Teknikal':9} {'Berita':7} {'Proba':6} {'Sektor'}")
    print("-"*70)
    for i, (_, r) in enumerate(df_hasil.head(10).iterrows(), 1):
        berita_str = f"{r['skor_berita_raw']:+.0f}"
        print(f"{i:4} {r['ticker']:6} {r['skor_final']:6.1f} {r['sinyal']:8} "
              f"{r['skor_teknikal']:9.1f} {berita_str:7} "
              f"{r['proba_naik']:6.3f} {r['sektor']}")

    beli   = df_hasil[df_hasil['sinyal']=='BELI']
    pantau = df_hasil[df_hasil['sinyal']=='PANTAU']
    print(f"\nRingkasan:")
    print(f"  BELI  : {len(beli)} saham")
    print(f"  PANTAU: {len(pantau)} saham")
    print(f"  Sentimen berita: {sentimen_global} (skor global: {skor_global:+d})")

    if len(beli) > 0:
        print(f"\nSaham BELI: {', '.join(beli['ticker'].tolist())}")

if __name__ == "__main__":
    main()
