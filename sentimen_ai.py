"""
sentimen_ai.py
Analisis sentimen berita pakai Groq AI (gratis)
Model: llama-3.1-8b-instant
Akurasi jauh lebih baik dari kamus kata kunci
"""
import requests, json, os, time
import pandas as pd
from datetime import datetime
from xml.etree import ElementTree as ET

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.1-8b-instant"
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

SUMBER_BERITA = {
    "IDX"  : "https://www.idxchannel.com/rss",
    "CNBC" : "https://www.cnbcindonesia.com/rss",
    "Detik": "https://finance.detik.com/rss",
}

SAHAM_LIST = [
    "BBCA","BBRI","BMRI","BBNI","BRIS","BNGA","BBTN","PNBN",
    "TLKM","EXCL","ISAT","TOWR","MTEL","TBIG",
    "ADRO","PTBA","ITMG","INCO","ANTM","TINS","MEDC","HRUM","MDKA",
    "UNVR","ICBP","MYOR","KLBF","KAEF","CPIN","SIDO","GGRM","HMSP",
    "AALI","SIMP","LSIP","ASII","AUTO","UNTR",
    "SMGR","BSDE","CTRA","PWON","LPKR","SMRA",
    "GOTO","EMTK","BUKA","AKRA","PGAS","ESSA",
    "ACES","MAPI","LPPF","RALS","MIKA","SILO","HEAL","SCMA","MNCN",
]

def ambil_berita():
    berita = []
    for nama, url in SUMBER_BERITA.items():
        try:
            r    = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            root = ET.fromstring(r.text)
            for item in root.findall(".//item")[:25]:
                judul = item.find("title")
                if judul is None:
                    continue
                teks  = judul.text.upper()
                saham = [s for s in SAHAM_LIST if s in teks]
                berita.append({"sumber":nama, "judul":judul.text, "saham":saham})
        except Exception as e:
            print(f"  ERROR {nama}: {e}")
    return berita

def analisis_batch(berita_list):
    if not berita_list:
        return {}
    daftar = "\n".join([f"{i+1}. [{b['sumber']}] {b['judul']}" for i,b in enumerate(berita_list)])
    prompt = f"""Kamu adalah analis pasar modal Indonesia berpengalaman 20 tahun.

Analisis dampak setiap berita terhadap harga saham di Bursa Efek Indonesia (IHSG).

SKORING:
+2 = Sangat positif untuk IHSG
+1 = Positif untuk IHSG
 0 = Netral
-1 = Negatif untuk IHSG
-2 = Sangat negatif untuk IHSG

PANDUAN KONTEKS (WAJIB DIIKUTI):
- "Inflasi turun" = +1 (bukan negatif)
- "Suku bunga naik" = -1 (bukan positif)
- "Batu bara naik" = +2 untuk PTBA/ADRO/ITMG
- "Minyak naik" = +1 untuk PGAS/MEDC, -1 untuk konsumer
- "Emas naik" = +1 safe haven
- "Perang/Iran/Hormuz/rudal" = -2 semua saham
- "Laba naik" = +1 atau +2
- "Rugi/bangkrut" = -1 atau -2
- "IHSG turun" = -1
- "Ramadan/Lebaran" = +1 ritel/konsumer
- Berita politik tanpa dampak ekonomi = 0

BERITA:
{daftar}

Jawab HANYA JSON ini tanpa penjelasan:
{{
  "hasil": [
    {{"no": 1, "skor": -1, "alasan": "max 5 kata", "sektor": "semua"}},
    {{"no": 2, "skor": 2, "alasan": "max 5 kata", "sektor": "tambang"}}
  ],
  "rata_rata": -0.3,
  "sentimen": "NEGATIF"
}}
rata_rata = rata-rata semua skor (bukan jumlah).
sentimen: POSITIF jika >0.3, NEGATIF jika <-0.3, NETRAL jika di antaranya."""

    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"},
            json={"model":GROQ_MODEL,"messages":[{"role":"user","content":prompt}],
                  "max_tokens":2000,"temperature":0.1},
            timeout=30)
        if r.status_code != 200:
            print(f"  ERROR Groq {r.status_code}: {r.text[:100]}")
            return {}
        teks  = r.json()["choices"][0]["message"]["content"]
        start = teks.find("{")
        end   = teks.rfind("}") + 1
        if start == -1:
            return {}
        return json.loads(teks[start:end])
    except Exception as e:
        print(f"  ERROR: {e}")
        return {}

def scoring_sentimen_ai(api_key=None):
    global GROQ_API_KEY
    if api_key:
        GROQ_API_KEY = api_key
    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY tidak tersedia")
        return None

    tanggal = datetime.now().strftime("%Y-%m-%d")
    print(f"Analisis sentimen AI — {tanggal}")
    print("="*60)

    print("1. Ambil berita...")
    berita = ambil_berita()
    print(f"   {len(berita)} berita dari 3 sumber")

    print("2. Analisis dengan Groq AI (llama-3.1-8b-instant)...")
    semua_hasil  = []
    skor_rata_list = []
    BATCH = 15

    for i in range(0, min(len(berita), 60), BATCH):
        batch = berita[i:i+BATCH]
        print(f"   Batch {i//BATCH+1} ({len(batch)} berita)...")
        data = analisis_batch(batch)
        if not data or "hasil" not in data:
            continue
        for h in data["hasil"]:
            idx = i + h["no"] - 1
            if idx < len(berita):
                semua_hasil.append({
                    "judul"  : berita[idx]["judul"],
                    "sumber" : berita[idx]["sumber"],
                    "saham"  : berita[idx]["saham"],
                    "skor"   : h["skor"],
                    "alasan" : h.get("alasan",""),
                    "sektor" : h.get("sektor","semua"),
                })
        if "rata_rata" in data:
            skor_rata_list.append(data["rata_rata"])
        time.sleep(0.5)

    if not semua_hasil:
        print("Tidak ada hasil")
        return None

    skor_global = sum(skor_rata_list)/len(skor_rata_list) if skor_rata_list else 0
    sentimen = "POSITIF" if skor_global>0.3 else "NEGATIF" if skor_global<-0.3 else "NETRAL"
    lampu    = "HIJAU"   if skor_global>0.3 else "MERAH"   if skor_global<-0.3 else "KUNING"
    bobot    = 1.1       if skor_global>0.3 else 0.9       if skor_global<-0.3 else 1.0

    print(f"\nHASIL ANALISIS AI:")
    print(f"  Skor global : {skor_global:+.2f} (skala -2 sampai +2)")
    print(f"  Sentimen    : {sentimen}")
    print(f"  Lampu       : {lampu}")

    positif = sorted([h for h in semua_hasil if h["skor"]>0], key=lambda x:-x["skor"])
    negatif = sorted([h for h in semua_hasil if h["skor"]<0], key=lambda x:x["skor"])

    print(f"\nBERITA POSITIF TERKUAT:")
    for h in positif[:5]:
        saham_str = f" [{','.join(h['saham'])}]" if h["saham"] else ""
        print(f"  +{h['skor']} [{h['sumber']}] {h['judul'][:60]}{saham_str}")
        print(f"     Alasan: {h['alasan']} | Sektor: {h['sektor']}")

    print(f"\nBERITA NEGATIF TERKUAT:")
    for h in negatif[:5]:
        saham_str = f" [{','.join(h['saham'])}]" if h["saham"] else ""
        print(f"  {h['skor']} [{h['sumber']}] {h['judul'][:60]}{saham_str}")
        print(f"     Alasan: {h['alasan']} | Sektor: {h['sektor']}")

    skor_saham = {}
    for h in semua_hasil:
        for s in h["saham"]:
            skor_saham[s] = skor_saham.get(s,0) + h["skor"]
    if skor_saham:
        print(f"\nSAHAM YANG DISEBUT:")
        for s,skor in sorted(skor_saham.items(), key=lambda x:-x[1]):
            label = "POSITIF" if skor>0 else "NEGATIF" if skor<0 else "NETRAL"
            print(f"  {s:6s} | {skor:+2d} | {label}")

    os.makedirs("data/berita", exist_ok=True)
    df = pd.DataFrame(semua_hasil)
    df["saham"] = df["saham"].apply(lambda x: ",".join(x))
    df.to_csv(f"data/berita/sentimen_ai_{tanggal}.csv", index=False)
    print(f"\nFile: data/berita/sentimen_ai_{tanggal}.csv")
    print(f"KESIMPULAN: Lampu {lampu} — {sentimen} ({skor_global:+.2f})")

    return {"skor_global":skor_global,"sentimen":sentimen,"lampu":lampu,
            "bobot":bobot,"skor_saham":skor_saham}

if __name__ == "__main__":
    key = os.environ.get("GROQ_API_KEY","")
    scoring_sentimen_ai(api_key=key)
