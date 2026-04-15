#!/usr/bin/env python3
"""
jurnal_trading.py
=================
Modul jurnal trading untuk IHSG Predictor Bot.

Fitur:
- Catat transaksi BELI dan JUAL
- Hitung profit/loss otomatis
- Statistik win rate, avg return, profit factor
- Command /jurnal di Telegram
- Tombol BELI/JUAL/SKIP terintegrasi

Cara pakai di main.py:
    from jurnal_trading import (
        catat_beli, catat_jual, lihat_jurnal,
        cmd_jurnal, cmd_posisi_aktif,
        tombol_jurnal
    )
"""

import os, json
import pandas as pd
from datetime import datetime, date

JURNAL_FILE  = "logs/jurnal_trading.csv"
POSISI_FILE  = "logs/posisi_aktif.json"

os.makedirs("logs", exist_ok=True)

# ── POSISI AKTIF ──────────────────────────────────────────────
def load_posisi() -> dict:
    if os.path.exists(POSISI_FILE):
        try:
            return json.load(open(POSISI_FILE))
        except: pass
    return {}

def save_posisi(posisi: dict):
    with open(POSISI_FILE, "w") as f:
        json.dump(posisi, f, indent=2, ensure_ascii=False)

# ── JURNAL CSV ────────────────────────────────────────────────
def load_jurnal() -> pd.DataFrame:
    if os.path.exists(JURNAL_FILE):
        try:
            return pd.read_csv(JURNAL_FILE)
        except: pass
    return pd.DataFrame(columns=[
        "id","tanggal_beli","tanggal_jual","ticker",
        "harga_beli","harga_jual","lot","modal_rp",
        "hasil_rp","hasil_pct","status","catatan"
    ])

def save_jurnal(df: pd.DataFrame):
    df.to_csv(JURNAL_FILE, index=False)

# ── CATAT BELI ────────────────────────────────────────────────
def catat_beli(ticker: str, harga_beli: float, lot: int = 1,
               catatan: str = "") -> dict:
    """Catat transaksi beli ke posisi aktif."""
    posisi = load_posisi()
    modal  = harga_beli * lot * 100  # 1 lot = 100 lembar

    posisi[ticker] = {
        "tanggal_beli": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "harga_beli"  : harga_beli,
        "lot"         : lot,
        "modal_rp"    : modal,
        "catatan"     : catatan,
    }
    save_posisi(posisi)
    return posisi[ticker]

# ── CATAT JUAL ────────────────────────────────────────────────
def catat_jual(ticker: str, harga_jual: float,
               catatan: str = "") -> dict:
    """Catat transaksi jual, hitung P/L, pindah ke jurnal."""
    posisi = load_posisi()

    if ticker not in posisi:
        return {"error": f"{ticker} tidak ada di posisi aktif"}

    pos = posisi[ticker]
    harga_beli = pos["harga_beli"]
    lot        = pos["lot"]
    modal      = pos["modal_rp"]

    # Hitung hasil (sudah potong biaya Mirae 0.15% beli + 0.35% jual)
    biaya_beli = modal * 0.0015
    hasil_kotor= harga_jual * lot * 100
    biaya_jual = hasil_kotor * 0.0035
    hasil_bersih = hasil_kotor - biaya_jual - (modal + biaya_beli)
    hasil_pct    = hasil_bersih / modal * 100

    # Simpan ke jurnal
    df = load_jurnal()
    id_baru = len(df) + 1
    baris = {
        "id"           : id_baru,
        "tanggal_beli" : pos["tanggal_beli"],
        "tanggal_jual" : datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ticker"       : ticker,
        "harga_beli"   : harga_beli,
        "harga_jual"   : harga_jual,
        "lot"          : lot,
        "modal_rp"     : round(modal, 0),
        "hasil_rp"     : round(hasil_bersih, 0),
        "hasil_pct"    : round(hasil_pct, 2),
        "status"       : "PROFIT" if hasil_bersih > 0 else "LOSS",
        "catatan"      : catatan,
    }
    df = pd.concat([df, pd.DataFrame([baris])], ignore_index=True)
    save_jurnal(df)

    # Hapus dari posisi aktif
    del posisi[ticker]
    save_posisi(posisi)

    return baris

# ── STATISTIK ─────────────────────────────────────────────────
def hitung_statistik() -> dict:
    df = load_jurnal()
    if df.empty:
        return {}

    df["hasil_pct"] = pd.to_numeric(df["hasil_pct"], errors="coerce")
    df["hasil_rp"]  = pd.to_numeric(df["hasil_rp"],  errors="coerce")

    profit = df[df["hasil_pct"] > 0]
    loss   = df[df["hasil_pct"] <= 0]

    avg_win  = float(profit["hasil_pct"].mean()) if len(profit) > 0 else 0
    avg_loss = float(loss["hasil_pct"].mean())   if len(loss)   > 0 else 0
    pf = abs(profit["hasil_rp"].sum()) / abs(loss["hasil_rp"].sum() or 1)

    return {
        "total_trade"    : len(df),
        "win"            : len(profit),
        "loss"           : len(loss),
        "win_rate"       : round(len(profit)/len(df)*100, 1),
        "avg_return"     : round(float(df["hasil_pct"].mean()), 2),
        "avg_win"        : round(avg_win, 2),
        "avg_loss"       : round(avg_loss, 2),
        "profit_factor"  : round(pf, 2),
        "total_profit_rp": round(float(df["hasil_rp"].sum()), 0),
    }

# ── FORMAT PESAN TELEGRAM ─────────────────────────────────────
def format_jurnal_telegram(n_terakhir: int = 10) -> str:
    df  = load_jurnal()
    stat= hitung_statistik()

    if df.empty:
        return (
            "📓 JURNAL TRADING\n\n"
            "Belum ada transaksi tercatat.\n"
            "Tap tombol BELI saat dapat sinyal untuk mulai mencatat!"
        )

    baris = ["📓 JURNAL TRADING", ""]

    # Statistik
    if stat:
        icon = "🟢" if stat["total_profit_rp"] >= 0 else "🔴"
        baris += [
            f"📊 STATISTIK ({stat['total_trade']} trade):",
            f"  Win Rate    : {stat['win_rate']}% ({stat['win']}W/{stat['loss']}L)",
            f"  Avg Return  : {stat['avg_return']:+.2f}%",
            f"  Avg Win     : {stat['avg_win']:+.2f}%",
            f"  Avg Loss    : {stat['avg_loss']:+.2f}%",
            f"  Profit Factor: {stat['profit_factor']:.2f}x",
            f"  Total P/L   : {icon} Rp {stat['total_profit_rp']:,.0f}",
            "",
        ]

    # 10 trade terakhir
    baris.append(f"📋 {n_terakhir} TRADE TERAKHIR:")
    for _, r in df.tail(n_terakhir).iloc[::-1].iterrows():
        icon = "✅" if r["status"] == "PROFIT" else "❌"
        baris.append(
            f"{icon} {r['ticker']} | {r['hasil_pct']:+.2f}% | "
            f"Rp{float(r['hasil_rp']):+,.0f} | {str(r['tanggal_jual'])[:10]}"
        )

    return "\n".join(baris)

def format_posisi_aktif() -> str:
    posisi = load_posisi()
    if not posisi:
        return "📋 POSISI AKTIF\n\nTidak ada posisi aktif saat ini."

    baris = [f"📋 POSISI AKTIF ({len(posisi)} saham)", ""]
    for ticker, pos in posisi.items():
        modal = pos.get("modal_rp", 0)
        baris.append(
            f"• {ticker}\n"
            f"  Beli : Rp{pos['harga_beli']:,.0f} | {pos['lot']} lot\n"
            f"  Modal: Rp{modal:,.0f}\n"
            f"  Tgl  : {pos['tanggal_beli'][:10]}"
        )
    return "\n".join(baris)

# ── TELEGRAM HANDLERS ─────────────────────────────────────────
# Import ini di main.py dan daftarkan handler-nya

async def cmd_jurnal(update, ctx):
    """Handler command /jurnal"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    pesan = format_jurnal_telegram()
    keyboard = [[
        InlineKeyboardButton("📋 Posisi Aktif", callback_data="posisi_aktif"),
        InlineKeyboardButton("🔄 Refresh",       callback_data="refresh_jurnal"),
    ]]
    await update.message.reply_text(
        pesan,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_posisi(update, ctx):
    """Handler command /posisi"""
    await update.message.reply_text(format_posisi_aktif())

async def tombol_beli(update, ctx):
    """Handler tombol BELI_TICKER_HARGA"""
    q    = update.callback_query
    await q.answer()
    data = q.data  # format: BELI_TICKER_HARGA

    parts  = data.split("_")
    ticker = parts[1]
    harga  = float(parts[2]) if len(parts) > 2 else 0

    # Default 1 lot
    pos = catat_beli(ticker, harga, lot=1)
    modal = pos["modal_rp"]

    await q.edit_message_text(
        f"✅ BELI {ticker} dicatat!\n\n"
        f"💰 Harga beli : Rp{harga:,.0f}\n"
        f"📦 Lot        : 1 lot (100 lembar)\n"
        f"💵 Modal      : Rp{modal:,.0f}\n"
        f"📅 Tanggal    : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"🎯 TP: +3% → Rp{harga*1.03:,.0f}\n"
        f"🛑 SL: -2% → Rp{harga*0.98:,.0f}\n\n"
        f"Gunakan /posisi untuk cek posisi aktif\n"
        f"Gunakan /jual {ticker} [harga] saat mau jual"
    )

async def tombol_skip(update, ctx):
    """Handler tombol SKIP_TICKER"""
    q    = update.callback_query
    await q.answer()
    ticker = q.data.split("_")[1]
    await q.edit_message_text(
        f"⏭️ {ticker} di-skip\n"
        f"Bot tetap monitor saham ini 👀"
    )

async def tombol_jual(update, ctx):
    """Handler tombol JUAL_TICKER_HARGA"""
    q    = update.callback_query
    await q.answer()
    parts  = q.data.split("_")
    ticker = parts[1]
    harga  = float(parts[2]) if len(parts) > 2 else 0

    hasil = catat_jual(ticker, harga)

    if "error" in hasil:
        await q.edit_message_text(f"❌ Error: {hasil['error']}")
        return

    icon = "🟢" if hasil["status"] == "PROFIT" else "🔴"
    await q.edit_message_text(
        f"{icon} JUAL {ticker} dicatat!\n\n"
        f"💰 Harga beli : Rp{hasil['harga_beli']:,.0f}\n"
        f"💰 Harga jual : Rp{hasil['harga_jual']:,.0f}\n"
        f"📊 Hasil      : {hasil['hasil_pct']:+.2f}%\n"
        f"💵 P/L        : Rp{hasil['hasil_rp']:+,.0f}\n"
        f"📅 Tanggal    : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"(Sudah dipotong biaya Mirae 0.15%+0.35%)\n"
        f"Ketik /jurnal untuk lihat semua trade"
    )

async def tombol_refresh_jurnal(update, ctx):
    """Handler tombol refresh jurnal"""
    q = update.callback_query
    await q.answer()
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    pesan = format_jurnal_telegram()
    keyboard = [[
        InlineKeyboardButton("📋 Posisi Aktif", callback_data="posisi_aktif"),
        InlineKeyboardButton("🔄 Refresh",       callback_data="refresh_jurnal"),
    ]]
    await q.edit_message_text(
        pesan, reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def tombol_posisi_aktif(update, ctx):
    """Handler tombol posisi aktif"""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(format_posisi_aktif())

async def cmd_jual(update, ctx):
    """
    Handler command /jual TICKER HARGA
    Contoh: /jual BBCA 9500
    """
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "Format: /jual TICKER HARGA\n"
            "Contoh: /jual BBCA 9500"
        )
        return

    ticker = args[0].upper()
    try:
        harga = float(args[1].replace(",", ""))
    except:
        await update.message.reply_text("Harga tidak valid!")
        return

    hasil = catat_jual(ticker, harga)

    if "error" in hasil:
        await update.message.reply_text(f"❌ {hasil['error']}")
        return

    icon = "🟢" if hasil["status"] == "PROFIT" else "🔴"
    await update.message.reply_text(
        f"{icon} JUAL {ticker} dicatat!\n\n"
        f"Harga beli : Rp{hasil['harga_beli']:,.0f}\n"
        f"Harga jual : Rp{hasil['harga_jual']:,.0f}\n"
        f"Hasil      : {hasil['hasil_pct']:+.2f}%\n"
        f"P/L        : Rp{hasil['hasil_rp']:+,.0f}\n\n"
        f"Ketik /jurnal untuk lihat semua trade"
    )

async def cmd_beli(update, ctx):
    """
    Handler command /beli TICKER HARGA [LOT]
    Contoh: /beli BBCA 9500 2
    """
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "Format: /beli TICKER HARGA [LOT]\n"
            "Contoh: /beli BBCA 9500\n"
            "Contoh: /beli BBCA 9500 2"
        )
        return

    ticker = args[0].upper()
    try:
        harga = float(args[1].replace(",", ""))
        lot   = int(args[2]) if len(args) > 2 else 1
    except:
        await update.message.reply_text("Format salah!")
        return

    pos   = catat_beli(ticker, harga, lot=lot)
    modal = pos["modal_rp"]

    await update.message.reply_text(
        f"✅ BELI {ticker} dicatat!\n\n"
        f"Harga beli : Rp{harga:,.0f}\n"
        f"Lot        : {lot} lot\n"
        f"Modal      : Rp{modal:,.0f}\n\n"
        f"TP +3% : Rp{harga*1.03:,.0f}\n"
        f"SL -2% : Rp{harga*0.98:,.0f}\n\n"
        f"Ketik /posisi untuk cek posisi aktif"
    )


# ── CARA INTEGRASI KE main.py ─────────────────────────────────
"""
Tambahkan ini di main.py:

1. Import di atas:
   from jurnal_trading import (
       cmd_jurnal, cmd_posisi, cmd_jual, cmd_beli,
       tombol_beli, tombol_skip, tombol_jual,
       tombol_refresh_jurnal, tombol_posisi_aktif,
   )

2. Daftarkan handler di fungsi main():
   app.add_handler(CommandHandler("jurnal",  cmd_jurnal))
   app.add_handler(CommandHandler("posisi",  cmd_posisi))
   app.add_handler(CommandHandler("beli",    cmd_beli))
   app.add_handler(CommandHandler("jual",    cmd_jual))

3. Di CallbackQueryHandler, tambahkan kondisi:
   elif data.startswith("BELI_"):    await tombol_beli(update, ctx)
   elif data.startswith("SKIP_"):    await tombol_skip(update, ctx)
   elif data.startswith("JUAL_"):    await tombol_jual(update, ctx)
   elif data == "refresh_jurnal":    await tombol_refresh_jurnal(update, ctx)
   elif data == "posisi_aktif":      await tombol_posisi_aktif(update, ctx)
"""

if __name__ == "__main__":
    # Test modul
    print("Test jurnal_trading.py")
    print()

    # Test catat beli
    print("1. Catat BELI BBCA 9500...")
    catat_beli("BBCA", 9500, lot=1)
    catat_beli("BBRI", 4800, lot=2)
    print(format_posisi_aktif())

    print()

    # Test catat jual
    print("2. Catat JUAL BBCA 9800...")
    hasil = catat_jual("BBCA", 9800)
    print(f"   Hasil: {hasil['hasil_pct']:+.2f}% | Rp{hasil['hasil_rp']:+,.0f}")

    print()

    # Test jurnal
    print("3. Jurnal trading:")
    print(format_jurnal_telegram())
