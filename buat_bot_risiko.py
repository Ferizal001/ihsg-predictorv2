code = """import os
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

MODAL_DEFAULT = 100_000_000  # Rp 100 juta default

def hitung_posisi(modal, skor):
    tp  = 0.020   # target profit +2%
    sl  = 0.010   # stop loss -1%
    kas = 0.20    # cadangan kas 20%
    biaya = 0.004 # biaya transaksi 0.4%

    modal_aktif = modal * (1 - kas)
    if skor >= 80:
        faktor = 1.00
    elif skor >= 70:
        faktor = 0.75
    elif skor >= 60:
        faktor = 0.50
    else:
        faktor = 0.25

    alokasi = (modal_aktif / 5) * faktor
    risiko  = alokasi * sl
    target  = alokasi * (tp - biaya)
    return alokasi, risiko, target

async def start(update, ctx):
    keyboard = [
        [InlineKeyboardButton("Ranking", callback_data="ranking"),
         InlineKeyboardButton("Lampu",   callback_data="lampu")],
        [InlineKeyboardButton("Status",  callback_data="status"),
         InlineKeyboardButton("Risiko",  callback_data="risiko")],
        [InlineKeyboardButton("Help",    callback_data="help")],
    ]
    await update.message.reply_text(
        "Selamat datang di IHSG Predictor Bot!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def lampu(update, ctx):
    baris = [
        "STATUS LAMPU HARI INI:",
        "",
        "LAMPU: HIJAU",
        "Akurasi model: 58.74%",
        "Kondisi: Trading normal",
        "",
        "Kriteria lampu:",
        "HIJAU  - Akurasi > 60%, VIX normal",
        "KUNING - Akurasi 50-60%, waspada",
        "MERAH  - Akurasi < 50%, stop trading",
        "",
        "Aksi hari ini:",
        "Ambil Top 5 saham dengan skor > 55",
        "Semua skor < 55 = tidak ada sinyal kuat",
    ]
    await update.message.reply_text(chr(10).join(baris))

async def status(update, ctx):
    baris = [
        "Status Sistem IHSG Predictor:",
        "",
        "Bot        : Online 24 jam di Railway",
        "Model      : 11 sektor (RandomForest)",
        "Saham scan : 38 saham aktif",
        "Akurasi    : 58.74% rata-rata",
        "Overfit    : Tidak ada (gap < 10%)",
        "Fitur      : 30 (teknikal + komoditas)",
        "",
        "Komoditas aktif:",
        "- Batu bara - Minyak Brent",
        "- Emas - CPO/Sawit",
        "",
        "Update: 2026-03-26",
    ]
    await update.message.reply_text(chr(10).join(baris))

async def ranking(update, ctx):
    baris = [
        "TOP 10 SAHAM (26 Mar 2026):",
        "",
        "1.  PTBA | Skor:50 | Proba:42% | Tambang",
        "2.  ITMG | Skor:48 | Proba:42% | Tambang",
        "3.  ADRO | Skor:46 | Proba:42% | Tambang",
        "4.  ASII | Skor:42 | Proba:37% | Lainnya",
        "5.  TLKM | Skor:39 | Proba:38% | Telekomunikasi",
        "6.  BMRI | Skor:38 | Proba:33% | Perbankan",
        "7.  ISAT | Skor:38 | Proba:38% | Telekomunikasi",
        "8.  AKRA | Skor:33 | Proba:42% | Energi",
        "9.  ANTM | Skor:33 | Proba:42% | Tambang",
        "10. ABMM | Skor:32 | Proba:38% | Lainnya",
        "",
        "Semua skor < 55 = SKIP hari ini",
        "Model: 11 sektor | Akurasi: 58.74%",
    ]
    await update.message.reply_text(chr(10).join(baris))

async def risiko(update, ctx):
    modal = MODAL_DEFAULT
    baris = [
        "MANAJEMEN RISIKO:",
        f"Modal diasumsikan: Rp {modal/1e6:.0f} juta",
        "",
        "Aturan wajib:",
        "- Max risiko per trade: 2% modal",
        "- Stop loss: -1% dari harga beli",
        "- Take profit: +2% dari harga beli",
        "- Rasio risk/reward: 1:2",
        "- Max 5 saham sekaligus",
        "- Kas minimum: 20% modal",
        "",
        "Simulasi posisi per saham:",
        "",
    ]

    saham_contoh = [
        ("PTBA", 50),
        ("ITMG", 48),
        ("ADRO", 46),
    ]

    for nama, skor in saham_contoh:
        alokasi, risiko_rp, target_rp = hitung_posisi(modal, skor)
        baris.append(f"{nama} (Skor:{skor}):")
        baris.append(f"  Alokasi : Rp {alokasi/1e6:.1f} jt")
        baris.append(f"  SL      : -{10000*alokasi/1e6:.0f}rb (1%)")
        baris.append(f"  TP      : +{16000*alokasi/1e6:.0f}rb (net ~1.6%)")
        baris.append("")

    baris.append("Filosofi: profit kecil konsisten")
    baris.append("lebih baik dari profit besar berisiko.")
    await update.message.reply_text(chr(10).join(baris))

async def posisi_cmd(update, ctx):
    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Format: /posisi [modal_juta] [skor]"
            + chr(10) + "Contoh: /posisi 100 75"
        )
        return

    try:
        modal = float(args[0]) * 1_000_000
        skor  = float(args[1])
        alokasi, risiko_rp, target_rp = hitung_posisi(modal, skor)

        if skor < 55:
            sinyal = "SKIP - skor terlalu rendah"
        elif skor < 70:
            sinyal = "PANTAU - posisi 50%"
        else:
            sinyal = "BELI - posisi penuh"

        baris = [
            f"Kalkulasi Posisi:",
            f"Modal    : Rp {modal/1e6:.0f} juta",
            f"Skor     : {skor}",
            f"Sinyal   : {sinyal}",
            "",
            f"Alokasi  : Rp {alokasi/1e6:.1f} juta",
            f"Stop loss: Rp {alokasi*0.01/1e3:.0f} ribu (-1%)",
            f"Target   : Rp {alokasi*0.016/1e3:.0f} ribu (+1.6% net)",
            f"Kas sisa : Rp {modal*0.2/1e6:.0f} juta (20%)",
            "",
            "TP: +2% | SL: -1% | Rasio 1:2",
        ]
        await update.message.reply_text(chr(10).join(baris))
    except Exception:
        await update.message.reply_text("Format salah. Contoh: /posisi 100 75")

async def help_cmd(update, ctx):
    baris = [
        "Daftar Perintah IHSG Bot:",
        "",
        "/start        - Menu utama",
        "/ranking      - Top 10 saham hari ini",
        "/lampu        - Status kondisi pasar",
        "/status       - Info model dan sistem",
        "/risiko       - Panduan manajemen risiko",
        "/posisi 100 75 - Hitung posisi",
        "               (modal juta, skor)",
        "/help         - Menu ini",
        "",
        "Contoh posisi:",
        "/posisi 50 80",
        "= modal Rp 50jt, skor saham 80",
    ]
    await update.message.reply_text(chr(10).join(baris))

async def tombol(update, ctx):
    q = update.callback_query
    await q.answer()
    if q.data == "ranking":
        baris = [
            "TOP 5 SAHAM:",
            "1. PTBA | Skor:50 | Tambang",
            "2. ITMG | Skor:48 | Tambang",
            "3. ADRO | Skor:46 | Tambang",
            "4. ASII | Skor:42 | Lainnya",
            "5. TLKM | Skor:39 | Telekomunikasi",
            "Semua SKIP - skor < 55",
        ]
        await q.edit_message_text(chr(10).join(baris))
    elif q.data == "lampu":
        await q.edit_message_text("LAMPU: HIJAU - Akurasi 58.74%")
    elif q.data == "status":
        await q.edit_message_text("Model: 11 sektor | 38 saham | RF tanpa overfit")
    elif q.data == "risiko":
        await q.edit_message_text("Ketik /risiko untuk panduan lengkap")
    elif q.data == "help":
        await q.edit_message_text("Ketik /help untuk semua perintah")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("lampu",   lampu))
    app.add_handler(CommandHandler("status",  status))
    app.add_handler(CommandHandler("ranking", ranking))
    app.add_handler(CommandHandler("risiko",  risiko))
    app.add_handler(CommandHandler("posisi",  posisi_cmd))
    app.add_handler(CommandHandler("help",    help_cmd))
    app.add_handler(CallbackQueryHandler(tombol))
    print("Bot siap!")
    app.run_polling()

if __name__ == "__main__":
    main()
"""

with open("bot_simple.py", "w") as f:
    f.write(code)
print("bot_simple.py berhasil dibuat!")
