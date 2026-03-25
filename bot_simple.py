import os
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

async def start(update, ctx):
    await update.message.reply_text("Selamat datang di IHSG Bot! Ketik /help")

async def lampu(update, ctx):
    await update.message.reply_text("LAMPU: HIJAU - Kondisi pasar normal.")

async def status(update, ctx):
    baris = [
        "Status Sistem IHSG Predictor:",
        "",
        "Bot     : Online 24 jam di Railway",
        "Model   : 6 sektor tersimpan",
        "Saham   : 23 saham aktif",
        "Akurasi : 59.96% (naik dari 52%)",
        "Fitur   : 30 (termasuk komoditas)",
        "",
        "Komoditas aktif:",
        "- Batu bara (COAL)",
        "- Minyak Brent (OIL)",
        "- Emas (GOLD)",
        "- CPO/Sawit (CPO)",
    ]
    await update.message.reply_text(chr(10).join(baris))

async def ranking(update, ctx):
    baris = [
        "TOP 10 SAHAM HARI INI (26 Mar 2026):",
        "",
        "1. PTBA  | Skor: 49 | Proba: 41% | Tambang",
        "2. ITMG  | Skor: 47 | Proba: 41% | Tambang",
        "3. ADRO  | Skor: 46 | Proba: 41% | Tambang",
        "4. BMRI  | Skor: 43 | Proba: 44% | Perbankan",
        "5. ASII  | Skor: 41 | Proba: 36% | Lainnya",
        "6. AKRA  | Skor: 40 | Proba: 60% | Energi",
        "7. PGAS  | Skor: 39 | Proba: 60% | Energi",
        "8. TLKM  | Skor: 39 | Proba: 36% | Lainnya",
        "9. MEDC  | Skor: 39 | Proba: 60% | Energi",
        "10. ISAT | Skor: 37 | Proba: 36% | Lainnya",
        "",
        "Akurasi model: 59.96%",
        "Semua skor di bawah 55 = SKIP hari ini",
        "Lampu: HIJAU",
        "Update: 2026-03-26",
    ]
    await update.message.reply_text(chr(10).join(baris))

async def help_cmd(update, ctx):
    baris = [
        "Daftar Perintah IHSG Bot:",
        "",
        "/start   - Menu utama",
        "/ranking - Top 10 saham hari ini",
        "/lampu   - Status kondisi pasar",
        "/status  - Info model dan sistem",
        "/help    - Menu ini",
    ]
    await update.message.reply_text(chr(10).join(baris))

async def tombol(update, ctx):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("OK")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lampu", lampu))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("ranking", ranking))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(tombol))
    print("Bot siap!")
    app.run_polling()

if __name__ == "__main__":
    main()
