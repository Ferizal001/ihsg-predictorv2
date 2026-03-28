"""
update_main_final.py
Update main.py dengan:
1. Kamus sentimen kontekstual yang benar
2. Jadwal jam 08:00 WIB (01:00 UTC) bukan jam 08:00 UTC (15:00 WIB)
"""
import re

with open("main.py", "r") as f:
    isi = f.read()

# ── 1. Update kamus sentimen kontekstual ─────────────────────
POSITIF_BARU = '''POSITIF = [
    "laba naik","laba tumbuh","laba meningkat","laba bersih naik",
    "pendapatan naik","revenue naik","omzet naik",
    "dividen","buyback","right issue","stock split",
    "kontrak baru","akuisisi","ekspansi","investasi masuk",
    "top gainer","rally","menguat","rebound","pulih","recovery",
    "batu bara naik","coal naik","harga batu bara",
    "minyak naik","crude naik","harga minyak naik",
    "emas naik","gold naik","harga emas naik",
    "perak naik","nikel naik","tembaga naik",
    "komoditas naik","energi naik",
    "inflasi turun","deflasi","suku bunga turun","fed cut",
    "rupiah menguat","rupiah apresiasi",
    "ekspor naik","neraca dagang surplus",
    "IPO","listing baru","right issue",
]'''

NEGATIF_BARU = '''NEGATIF = [
    "rugi","kerugian","laba turun","laba merosot","laba anjlok",
    "pendapatan turun","revenue turun",
    "bangkrut","pailit","gagal bayar","default","delisting","suspensi",
    "korupsi","tersangka","penyidikan","penyelidikan","kasus hukum",
    "perang","serangan","rudal","bom","militer","konflik bersenjata",
    "Iran","Hormuz","blokade","embargo","sanksi",
    "eskalasi","geopolitik panas","ketegangan militer",
    "minyak naik inflasi","bbm naik","harga bbm naik",
    "inflasi naik","inflasi tinggi","harga pangan naik",
    "suku bunga naik","fed naik","bi rate naik",
    "rupiah melemah","rupiah anjlok","dolar naik",
    "resesi","krisis","stagflasi","perlambatan ekonomi",
    "PHK","pemutusan kerja","tutup pabrik",
    "banjir","gempa","tsunami","bencana alam",
    "IHSG turun","IHSG melemah","IHSG anjlok",
    "asing jual","foreign sell","net sell asing",
    "cpo turun","sawit turun",
]'''

isi = re.sub(r'POSITIF = \[.*?\]', POSITIF_BARU, isi, flags=re.DOTALL)
isi = re.sub(r'NEGATIF = \[.*?\]', NEGATIF_BARU, isi, flags=re.DOTALL)
print("Kamus sentimen diupdate")

# ── 2. Update jadwal ke WIB (UTC+7) ──────────────────────────
# 08:00 WIB = 01:00 UTC
# 08:15 WIB = 01:15 UTC
# 08:30 WIB = 01:30 UTC (tidak dipakai, digabung dengan scoring)
# 15:30 WIB = 08:30 UTC

isi = isi.replace(
    'schedule.every().day.at("08:00").do(download_data)',
    'schedule.every().day.at("01:00").do(download_data)'
)
isi = isi.replace(
    'schedule.every().day.at("08:15").do(scoring_harian)',
    'schedule.every().day.at("01:15").do(scoring_harian)'
)
isi = isi.replace(
    'schedule.every().day.at("15:30").do(evaluasi)',
    'schedule.every().day.at("08:30").do(evaluasi)'
)

# Update print jadwal
isi = isi.replace(
    'print("Jadwal aktif: 08:00 download | 08:15 scoring | 15:30 evaluasi")',
    'print("Jadwal aktif: 08:00 WIB download | 08:15 WIB scoring | 15:30 WIB evaluasi")'
)

# Update status command
isi = isi.replace(
    '"Jadwal   : 08:00 download | 08:15 scoring",',
    '"Jadwal   : 08:00 WIB download | 08:15 WIB scoring",',
)
isi = isi.replace(
    '"           08:30 kirim ranking | 15:30 evaluasi",',
    '"           Ranking masuk Telegram jam 08:15 WIB",',
)

print("Jadwal diupdate ke WIB (UTC+7)")

# Simpan
with open("main.py", "w") as f:
    f.write(isi)

print("main.py berhasil diupdate")

# ── 3. Verifikasi ─────────────────────────────────────────────
print("\nVerifikasi jadwal di main.py:")
for line in open("main.py"):
    if "schedule.every" in line:
        print(f"  {line.strip()}")

print("\nVerifikasi kamus — kata kunci baru:")
for line in open("main.py"):
    if "batu bara naik" in line or "Hormuz" in line:
        print(f"  {line.strip()}")
        break
