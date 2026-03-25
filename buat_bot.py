code = """import os
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

async def start(update, ctx):
    await update.message.reply_text("Selamat datang di IHSG Bot! Ketik /help")

async def lampu(update, ctx):
    await update.message.reply_text("LAMPU: HIJAU - Kondisi pasar normal.")

async def status(update, ctx):
    await update.message.reply_text("Status: Online 24 jam! Model: 5 sektor, 23 saham aktif.")

async def ranking(update, ctx):
    baris = [
        "TOP 5 SAHAM HARI INI (26 Mar 2026):",
        "",
        "1. PTBA  | Skor: 51 | Proba: 47% | Tambang",
        "2. BMRI  | Skor: 51 | Proba: 65% | Perbankan",
        "3. ITMG  | Skor: 50 | Proba: 47% | Tambang",
        "4. ADRO  | Skor: 48 | Proba: 47% | Tambang",
        "5. SIMP  | Skor: 45 | Proba: 73% | Agribisnis",
        "",
        "Catatan: Skor masih rendah karena",
        "data komoditas belum real-time.",
        "Update: 2026-03-26",
    ]
    await update.message.reply_text(chr(10).join(baris))

async def help_cmd(update, ctx):
    await update.message.reply_text("/start /lampu /ranking /status /help")

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
"""

with open("bot_simple.py", "w") as f:
    f.write(code)
print("bot_simple.py berhasil dibuat!")
