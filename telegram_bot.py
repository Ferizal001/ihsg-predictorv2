# ============================================================
#  telegram_bot.py — Bot Telegram IHSG Predictor
# ============================================================
#
#  CARA SETUP:
#  1. Chat @BotFather di Telegram → /newbot → dapat TOKEN
#  2. Chat @userinfobot → dapat CHAT_ID Anda
#  3. Isi TELEGRAM_TOKEN & CHAT_ID di config.py
#  4. pip install python-telegram-bot schedule
#  5. python telegram_bot.py
#
# ============================================================

import os
import json
import schedule
import time
import asyncio
import threading
from datetime import date, datetime
import pandas as pd

# ── Telegram library ─────────────────────────────────────────
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters,
)
from telegram.constants import ParseMode

# ── Sistem IHSG ──────────────────────────────────────────────
from config import PATHS, TRADING_CONFIG
from risk_manager import (
    hitung_akurasi_rolling, baca_jurnal,
    hitung_statistik_jurnal, perlu_retrain,
    cek_kondisi_pasar,
)


# ════════════════════════════════════════════════════════════
#  KONFIGURASI TOKEN & CHAT ID
#  → Isi di sini atau di config.py
# ════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ISI_TOKEN_ANDA_DI_SINI")
CHAT_ID        = os.environ.get("TELEGRAM_CHAT_ID", "ISI_CHAT_ID_ANDA")

# Bisa juga baca dari config.py
try:
    from config import TELEGRAM_TOKEN as TK, TELEGRAM_CHAT_ID as CID
    if TK and TK != "":
        TELEGRAM_TOKEN = TK
    if CID and CID != "":
        CHAT_ID = CID
except ImportError:
    pass


# ════════════════════════════════════════════════════════════
#  HELPER — FORMAT PESAN
# ════════════════════════════════════════════════════════════

EMOJI_LAMPU = {"HIJAU": "🟢", "KUNING": "🟡", "MERAH": "🔴"}
EMOJI_SINYAL = {"BELI KUAT": "🚀", "PANTAU": "👀", "SKIP": "⏸️"}


def format_laporan_pagi(tanggal: date = None) -> str:
    """Buat teks laporan pagi dari hasil ranking hari ini."""
    if tanggal is None:
        tanggal = date.today()

    path = os.path.join(PATHS["log_dir"], f"ranking_{tanggal}.csv")
    if not os.path.exists(path):
        return (
            f"⚠️ *Ranking {tanggal} belum tersedia*\n"
            f"Pipeline belum dijalankan hari ini.\n"
            f"Jalankan: `python main_pipeline.py --fase scoring`"
        )

    df = pd.read_csv(path)
    df_beli = df[df["sinyal"] == "BELI KUAT"].head(5)
    df_pantau = df[df["sinyal"] == "PANTAU"].head(3)

    akurasi = hitung_akurasi_rolling()
    lampu   = "HIJAU" if akurasi >= 0.60 else "KUNING" if akurasi >= 0.50 else "MERAH"

    tp  = TRADING_CONFIG["take_profit_pct"]
    sl  = abs(TRADING_CONFIG["stop_loss_pct"])
    hari = tanggal.strftime("%A, %d %b %Y")

    teks = (
        f"📊 *Laporan Pagi IHSG Predictor*\n"
        f"📅 {hari}\n"
        f"{'─' * 30}\n\n"
        f"{EMOJI_LAMPU[lampu]} *LAMPU: {lampu}*\n"
        f"🎯 Akurasi model (14h): {akurasi:.1%}\n\n"
    )

    if lampu == "MERAH":
        teks += (
            "🚫 *STOP TRADING HARI INI*\n"
            "Kondisi pasar tidak kondusif.\n"
            "Simpan kas, tidak buka posisi baru.\n"
        )
        return teks

    if df_beli.empty:
        teks += "⚠️ Tidak ada saham dengan sinyal BELI KUAT hari ini.\n"
    else:
        teks += f"🚀 *TOP {len(df_beli)} SAHAM BELI HARI INI:*\n"
        for i, (_, b) in enumerate(df_beli.iterrows(), 1):
            medal = ["🥇","🥈","🥉","4️⃣","5️⃣"][i-1]
            teks += (
                f"{medal} *{b['ticker'].replace('.JK','')}* "
                f"· Skor: {b['skor_total']:.0f}\n"
                f"   TP: +{tp:.1%} · SL: -{sl:.1%} · "
                f"Proba naik: {b.get('proba_naik',0.5):.0%}\n"
            )

    if not df_pantau.empty:
        teks += f"\n👀 *WATCHLIST:*\n"
        for _, b in df_pantau.iterrows():
            teks += f"• {b['ticker'].replace('.JK','')} · Skor {b['skor_total']:.0f}\n"

    teks += (
        f"\n{'─' * 30}\n"
        f"💡 TP: +{tp:.1%} · SL: -{sl:.1%} · Kas min: "
        f"{TRADING_CONFIG['min_kas_pct']:.0%}\n"
        f"⚠️ _Bukan saran investasi · gunakan manajemen risiko_"
    )
    return teks


def format_laporan_sore(tanggal: date = None) -> str:
    """Buat ringkasan hasil trading hari ini."""
    if tanggal is None:
        tanggal = date.today()

    df_jurnal = baca_jurnal()
    if df_jurnal.empty:
        return "📭 *Belum ada data jurnal trading.*"

    # Filter hari ini
    df_hari = df_jurnal[df_jurnal["tanggal"].astype(str) == str(tanggal)]

    if df_hari.empty:
        return f"📭 *Tidak ada trade yang dicatat hari ini ({tanggal})*"

    stats   = hitung_statistik_jurnal(df_jurnal)
    net_pct = df_hari["hasil_pct"].sum()
    hari    = tanggal.strftime("%d %b %Y")

    teks = (
        f"📈 *Ringkasan Sore · {hari}*\n"
        f"{'─' * 30}\n\n"
        f"*Hasil hari ini:*\n"
    )

    for _, r in df_hari.iterrows():
        icon = "✅" if r["hasil_pct"] > 0 else "❌"
        teks += (
            f"{icon} *{r['ticker'].replace('.JK','')}*: "
            f"{r['hasil_pct']:+.2%} "
            f"({r['status']})\n"
        )

    warna = "🟢" if net_pct > 0 else "🔴"
    teks += (
        f"\n{warna} *Net hari ini: {net_pct:+.2%}*\n\n"
        f"📊 *Statistik keseluruhan:*\n"
        f"• Total trade : {stats['total_trade']}\n"
        f"• Win rate    : {stats['win_rate']:.1%}\n"
        f"• Profit factor: {stats['profit_factor']:.2f}\n"
        f"• Total profit: Rp {stats['total_profit_rp']/1e6:.2f} jt\n"
    )

    # Cek retrain
    retrain = perlu_retrain(date.today())
    if retrain["perlu"]:
        teks += f"\n⚠️ *PERLU RETRAIN:* {retrain['alasan']}"
    else:
        teks += f"\n✅ Model masih sehat"

    return teks


def format_cek_saham(ticker: str) -> str:
    """Info detail 1 saham dari ranking terakhir."""
    tanggal = date.today()
    path    = os.path.join(PATHS["log_dir"], f"ranking_{tanggal}.csv")

    ticker_full = ticker.upper()
    if not ticker_full.endswith(".JK"):
        ticker_full += ".JK"

    if not os.path.exists(path):
        return f"⚠️ Data ranking hari ini belum tersedia."

    df  = pd.read_csv(path)
    row = df[df["ticker"] == ticker_full]

    if row.empty:
        return (
            f"⚠️ *{ticker.upper()}* tidak ditemukan di ranking hari ini.\n"
            f"Mungkin tidak lolos filter awal (illiquid/suspensi/gocap)."
        )

    r   = row.iloc[0]
    icon = EMOJI_SINYAL.get(r["sinyal"], "❓")

    return (
        f"🔍 *Detail Saham: {ticker.upper()}*\n"
        f"{'─' * 28}\n"
        f"Rank    : #{int(r['rank'])}\n"
        f"Sinyal  : {icon} {r['sinyal']}\n"
        f"Skor    : {r['skor_total']:.1f} / 100\n\n"
        f"📊 *Skor per komponen:*\n"
        f"• Supply/Demand : {r.get('skor_sd',0):.1f}\n"
        f"• Teknikal      : {r.get('skor_teknikal',0):.1f}\n"
        f"• Komoditas     : {r.get('skor_komoditas',0):.1f}\n"
        f"• Sentimen      : {r.get('skor_sentimen',0):.1f}\n"
        f"• Kalender      : {r.get('skor_kalender',0):.1f}\n\n"
        f"🎯 Proba naik: {r.get('proba_naik',0.5):.0%}\n"
        f"📅 Data: {tanggal}"
    )


# ════════════════════════════════════════════════════════════
#  COMMAND HANDLERS — RESPONS PERINTAH DARI HP
# ════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Perintah /start — tampilkan menu utama."""
    keyboard = [
        [
            InlineKeyboardButton("📊 Ranking hari ini", callback_data="ranking"),
            InlineKeyboardButton("🚦 Cek lampu",        callback_data="lampu"),
        ],
        [
            InlineKeyboardButton("📈 Laporan pagi",  callback_data="laporan_pagi"),
            InlineKeyboardButton("📉 Ringkasan sore",callback_data="laporan_sore"),
        ],
        [
            InlineKeyboardButton("📓 Jurnal trading", callback_data="jurnal"),
            InlineKeyboardButton("🤖 Status model",   callback_data="status"),
        ],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 *Selamat datang di IHSG Predictor Bot!*\n\n"
        "Bot ini membantu Anda mendapatkan rekomendasi saham IDX "
        "berdasarkan 6 sumber data setiap hari.\n\n"
        "Pilih menu di bawah atau ketik perintah:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup,
    )


async def cmd_ranking(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/ranking — tampilkan top 10 saham hari ini."""
    await update.message.reply_text("⏳ Mengambil ranking...")
    teks = format_laporan_pagi()
    await update.message.reply_text(teks, parse_mode=ParseMode.MARKDOWN)


async def cmd_lampu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/lampu — status lampu hijau/kuning/merah."""
    akurasi = hitung_akurasi_rolling()
    lampu   = (
        "HIJAU"  if akurasi >= 0.60 else
        "KUNING" if akurasi >= 0.50 else
        "MERAH"
    )
    emoji = EMOJI_LAMPU[lampu]
    aksi  = {
        "HIJAU" : "Trading normal · ambil Top 5 · posisi penuh",
        "KUNING": "Ambil 2–3 saham · posisi 50% · SL ketat",
        "MERAH" : "STOP trading · simpan kas · tunggu kondisi pulih",
    }[lampu]

    teks = (
        f"{emoji} *Kondisi Pasar: {lampu}*\n\n"
        f"📊 Akurasi model (14h): {akurasi:.1%}\n\n"
        f"💡 *Aksi:* {aksi}\n\n"
        f"🕐 Update: {datetime.now().strftime('%H:%M WIB')}"
    )
    await update.message.reply_text(teks, parse_mode=ParseMode.MARKDOWN)


async def cmd_cek(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/cek ADRO — cek skor saham tertentu."""
    if not ctx.args:
        await update.message.reply_text(
            "❓ Contoh penggunaan: `/cek ADRO` atau `/cek BBRI`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    ticker = ctx.args[0].upper()
    await update.message.reply_text(f"🔍 Mengecek {ticker}...")
    teks = format_cek_saham(ticker)
    await update.message.reply_text(teks, parse_mode=ParseMode.MARKDOWN)


async def cmd_jurnal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/jurnal — tampilkan statistik trading."""
    df = baca_jurnal()
    if df.empty:
        await update.message.reply_text("📭 Belum ada data jurnal trading.")
        return

    stats = hitung_statistik_jurnal(df)
    # 5 trade terakhir
    terakhir = df.tail(5)
    teks = (
        f"📓 *Jurnal Trading*\n"
        f"{'─' * 28}\n\n"
        f"*Statistik keseluruhan:*\n"
        f"• Total trade   : {stats['total_trade']}\n"
        f"• Win rate      : {stats['win_rate']:.1%}\n"
        f"• Avg profit    : {stats['avg_profit']:+.2%}\n"
        f"• Profit factor : {stats['profit_factor']:.2f}\n"
        f"• Total profit  : Rp {stats['total_profit_rp']/1e6:.2f} jt\n\n"
        f"*5 Trade terakhir:*\n"
    )
    for _, r in terakhir.iterrows():
        icon = "✅" if r["hasil_pct"] > 0 else "❌"
        teks += (
            f"{icon} {r['ticker'].replace('.JK','')} "
            f"{r['hasil_pct']:+.2%} "
            f"({r.get('tanggal','')[:10]})\n"
        )
    await update.message.reply_text(teks, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/status — status model dan sistem."""
    akurasi = hitung_akurasi_rolling()
    retrain = perlu_retrain(date.today())
    kondisi_model = (
        "✅ Sehat"    if akurasi >= 0.60 else
        "⚠️ Waspada"  if akurasi >= 0.50 else
        "🚨 Drift!"
    )
    teks = (
        f"🤖 *Status Sistem IHSG Predictor*\n"
        f"{'─' * 28}\n\n"
        f"Model     : {kondisi_model}\n"
        f"Akurasi   : {akurasi:.1%} (rolling 14h)\n"
        f"Retrain   : {'⚠️ PERLU' if retrain['perlu'] else '✅ Tidak perlu'}\n"
        f"Alasan    : {retrain['alasan']}\n\n"
        f"🕐 Cek: {datetime.now().strftime('%d %b %Y %H:%M WIB')}"
    )
    await update.message.reply_text(teks, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/help — daftar semua perintah."""
    teks = (
        "📋 *Daftar Perintah Bot*\n\n"
        "/start    — Menu utama\n"
        "/ranking  — Top 10 saham hari ini\n"
        "/lampu    — Status lampu hijau/kuning/merah\n"
        "/cek XXXX — Cek skor 1 saham (contoh: /cek ADRO)\n"
        "/jurnal   — Statistik & riwayat trading\n"
        "/status   — Status model & sistem\n"
        "/pagi     — Laporan pagi lengkap\n"
        "/sore     — Ringkasan hasil hari ini\n"
        "/help     — Tampilkan menu ini\n"
    )
    await update.message.reply_text(teks, parse_mode=ParseMode.MARKDOWN)


async def cmd_pagi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/pagi — laporan pagi lengkap."""
    await update.message.reply_text("⏳ Menyiapkan laporan pagi...")
    teks = format_laporan_pagi()
    await update.message.reply_text(teks, parse_mode=ParseMode.MARKDOWN)


async def cmd_sore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/sore — ringkasan hasil hari ini."""
    await update.message.reply_text("⏳ Menyiapkan ringkasan sore...")
    teks = format_laporan_sore()
    await update.message.reply_text(teks, parse_mode=ParseMode.MARKDOWN)


# ════════════════════════════════════════════════════════════
#  CALLBACK — TOMBOL INLINE
# ════════════════════════════════════════════════════════════

async def callback_tombol(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handler untuk tombol inline keyboard."""
    query = update.callback_query
    await query.answer()

    aksi = query.data
    if aksi == "ranking":
        teks = format_laporan_pagi()
    elif aksi == "lampu":
        akurasi = hitung_akurasi_rolling()
        lampu   = "HIJAU" if akurasi >= 0.60 else "KUNING" if akurasi >= 0.50 else "MERAH"
        teks    = f"{EMOJI_LAMPU[lampu]} *Lampu: {lampu}* · Akurasi: {akurasi:.1%}"
    elif aksi == "laporan_pagi":
        teks = format_laporan_pagi()
    elif aksi == "laporan_sore":
        teks = format_laporan_sore()
    elif aksi == "jurnal":
        df    = baca_jurnal()
        stats = hitung_statistik_jurnal(df) if not df.empty else {}
        teks  = (
            f"📓 Win rate: {stats.get('win_rate',0):.1%} · "
            f"Profit: Rp {stats.get('total_profit_rp',0)/1e6:.2f}jt"
            if stats else "📭 Belum ada jurnal"
        )
    elif aksi == "status":
        akurasi = hitung_akurasi_rolling()
        teks    = f"🤖 Akurasi model: {akurasi:.1%}"
    else:
        teks = "❓ Perintah tidak dikenal"

    await query.edit_message_text(teks, parse_mode=ParseMode.MARKDOWN)


# ════════════════════════════════════════════════════════════
#  NOTIFIKASI OTOMATIS — KIRIM KE HP TANPA DIMINTA
# ════════════════════════════════════════════════════════════

async def kirim_notifikasi(app: Application, pesan: str):
    """Kirim pesan ke CHAT_ID Anda."""
    try:
        await app.bot.send_message(
            chat_id    = CHAT_ID,
            text       = pesan,
            parse_mode = ParseMode.MARKDOWN,
        )
    except Exception as e:
        print(f"[Telegram] Gagal kirim: {e}")


def jadwalkan_notifikasi(app: Application):
    """
    Jadwalkan notifikasi otomatis setiap hari.
    Berjalan di thread terpisah.
    """
    loop = asyncio.new_event_loop()

    def jalankan_async(coro):
        loop.run_until_complete(coro)

    # ── 08:30 — Laporan pagi ─────────────────────────────
    def notif_pagi():
        print("[Bot] Kirim laporan pagi...")
        teks = format_laporan_pagi()
        jalankan_async(kirim_notifikasi(app, teks))

    # ── 15:30 — Ringkasan sore ───────────────────────────
    def notif_sore():
        print("[Bot] Kirim ringkasan sore...")
        teks = format_laporan_sore()
        jalankan_async(kirim_notifikasi(app, teks))

    # ── Alert lampu merah ─────────────────────────────────
    def cek_alert_merah():
        akurasi = hitung_akurasi_rolling()
        if akurasi < 0.50:
            teks = (
                "🔴 *ALERT: LAMPU MERAH*\n\n"
                f"Akurasi model turun ke {akurasi:.1%}\n"
                "Sistem menyarankan STOP trading.\n"
                "Pertimbangkan untuk retrain model."
            )
            jalankan_async(kirim_notifikasi(app, teks))

    # ── Daftar jadwal ─────────────────────────────────────
    schedule.every().day.at("08:30").do(notif_pagi)
    schedule.every().day.at("15:30").do(notif_sore)
    schedule.every().day.at("09:00").do(cek_alert_merah)
    schedule.every().day.at("12:00").do(cek_alert_merah)

    print("[Bot] Jadwal notifikasi aktif:")
    print("      08:30 → Laporan pagi")
    print("      15:30 → Ringkasan sore")
    print("      09:00 & 12:00 → Cek alert lampu merah")

    # Loop jadwal di thread ini
    while True:
        schedule.run_pending()
        time.sleep(30)


# ════════════════════════════════════════════════════════════
#  JALANKAN BOT
# ════════════════════════════════════════════════════════════

def main():
    if TELEGRAM_TOKEN == "ISI_TOKEN_ANDA_DI_SINI":
        print("=" * 50)
        print("⚠️  TOKEN BELUM DIISI!")
        print()
        print("Langkah setup:")
        print("1. Buka Telegram → cari @BotFather")
        print("2. Ketik /newbot → ikuti instruksi")
        print("3. Copy TOKEN yang diberikan")
        print("4. Set environment variable:")
        print("   export TELEGRAM_TOKEN='token_anda'")
        print("   export TELEGRAM_CHAT_ID='chat_id_anda'")
        print()
        print("Cara dapat CHAT_ID:")
        print("   Cari @userinfobot di Telegram → /start")
        print("=" * 50)
        return

    print("=" * 50)
    print("🤖 IHSG Predictor Bot — Starting...")
    print(f"   Token  : {TELEGRAM_TOKEN[:10]}...")
    print(f"   Chat ID: {CHAT_ID}")
    print("=" * 50)

    # Buat aplikasi bot
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Daftarkan semua command handler
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("ranking", cmd_ranking))
    app.add_handler(CommandHandler("lampu",   cmd_lampu))
    app.add_handler(CommandHandler("cek",     cmd_cek))
    app.add_handler(CommandHandler("jurnal",  cmd_jurnal))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("pagi",    cmd_pagi))
    app.add_handler(CommandHandler("sore",    cmd_sore))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CallbackQueryHandler(callback_tombol))

    # Jalankan scheduler notifikasi di thread terpisah
    thread_scheduler = threading.Thread(
        target=jadwalkan_notifikasi,
        args=(app,),
        daemon=True,
    )
    thread_scheduler.start()

    print("\n✅ Bot siap! Buka Telegram dan cari bot Anda.")
    print("   Tekan Ctrl+C untuk berhenti.\n")

    # Mulai polling (terima pesan dari HP)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
