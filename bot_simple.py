import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

async def start(update, ctx):
    keyboard = [
        [InlineKeyboardButton("Ranking", callback_data="ranking"),
         InlineKeyboardButton("Lampu", callback_data="lampu")],
        [InlineKeyboardButton("Status", callback_data="status")],
    ]
    await update.message.reply_text(
        "Selamat datang di IHSG Predictor Bot! Ketik /help",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def lampu(update, ctx):
    await update.message.reply_text("LAMPU: HIJAU - Kondisi pasar normal.")

async def status(update, ctx):
    await update.message.reply_text("Status: Online - Bot berjalan di Railway 24 jam!")

async def ranking(update, ctx):
    await update.message.reply_text("Ranking: Model belum ditraining.")

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
