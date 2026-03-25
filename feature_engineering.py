# ============================================================
#  feature_engineering.py — Hitung Indikator Teknikal & Fitur
# ============================================================

import pandas as pd
import numpy as np
from config import SECTORS, FILTER_CONFIG


# ════════════════════════════════════════════════════════════
#  INDIKATOR TEKNIKAL
# ════════════════════════════════════════════════════════════

def hitung_indikator_teknikal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hitung semua indikator teknikal dari DataFrame OHLCV.
    Kolom input : open, high, low, close, volume
    Kolom output: tambahan ~20 fitur teknikal
    """
    df = df.copy()
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # ── Moving Average ────────────────────────────────────
    df["ma5"]   = close.rolling(5).mean()
    df["ma20"]  = close.rolling(20).mean()
    df["ma50"]  = close.rolling(50).mean()
    df["ma200"] = close.rolling(200).mean()

    # Posisi harga vs MA (1 = di atas, 0 = di bawah)
    df["above_ma20"]  = (close > df["ma20"]).astype(int)
    df["above_ma50"]  = (close > df["ma50"]).astype(int)
    df["above_ma200"] = (close > df["ma200"]).astype(int)

    # ── RSI (Relative Strength Index) ────────────────────
    delta  = close.diff()
    gain   = delta.clip(lower=0)
    loss   = (-delta).clip(lower=0)
    avg_g  = gain.rolling(14).mean()
    avg_l  = loss.rolling(14).mean()
    rs     = avg_g / avg_l.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # RSI zone: oversold (<30), normal (30-70), overbought (>70)
    df["rsi_oversold"]   = (df["rsi"] < 30).astype(int)
    df["rsi_overbought"] = (df["rsi"] > 70).astype(int)
    df["rsi_reversal"]   = (
        (df["rsi"].shift(1) < 30) & (df["rsi"] >= 30)
    ).astype(int)

    # ── MACD ─────────────────────────────────────────────
    ema12        = close.ewm(span=12, adjust=False).mean()
    ema26        = close.ewm(span=26, adjust=False).mean()
    df["macd"]   = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]    = df["macd"] - df["signal"]
    df["macd_bullish"] = (
        (df["macd"] > df["signal"]) &
        (df["macd"].shift(1) <= df["signal"].shift(1))
    ).astype(int)

    # ── Bollinger Bands ───────────────────────────────────
    sma20       = close.rolling(20).mean()
    std20       = close.rolling(20).std()
    df["bb_upper"] = sma20 + (2 * std20)
    df["bb_lower"] = sma20 - (2 * std20)
    df["bb_pct"]   = (close - df["bb_lower"]) / (
        df["bb_upper"] - df["bb_lower"]
    ).replace(0, np.nan)
    df["bb_squeeze"] = (
        (df["bb_upper"] - df["bb_lower"]) < (sma20 * 0.05)
    ).astype(int)

    # ── Volume ────────────────────────────────────────────
    df["vol_ma20"]   = volume.rolling(20).mean()
    df["vol_ratio"]  = volume / df["vol_ma20"].replace(0, np.nan)

    # ── Lag features (harga N hari lalu) ─────────────────
    for lag in [1, 3, 5]:
        df[f"return_lag{lag}"] = close.pct_change(lag)

    # ── Volatilitas ───────────────────────────────────────
    df["volatility_5d"]  = close.pct_change().rolling(5).std()
    df["volatility_20d"] = close.pct_change().rolling(20).std()

    # ── Candlestick sederhana ─────────────────────────────
    df["body_size"]   = abs(close - df["open"]) / df["open"]
    df["upper_wick"]  = (high - close.clip(lower=df["open"])) / df["open"]
    df["lower_wick"]  = (close.clip(upper=df["open"]) - low) / df["open"]

    return df


# ════════════════════════════════════════════════════════════
#  FILTER AWAL — 800+ SAHAM → ~150 KANDIDAT
# ════════════════════════════════════════════════════════════

def filter_saham_layak(dict_ohlcv: dict) -> dict:
    """
    Filter saham yang tidak layak sebelum scoring.
    dict_ohlcv : { ticker: DataFrame OHLCV }
    return     : { ticker: DataFrame } — hanya yang lolos filter
    """
    lolos = {}
    alasan_buang = {}

    for ticker, df in dict_ohlcv.items():
        if df.empty or len(df) < 60:
            alasan_buang[ticker] = "data kurang dari 60 hari"
            continue

        close  = df["close"].iloc[-1]
        volume = df["volume"].iloc[-1]

        # ── Filter 1: Buang gocap (harga < Rp 100) ──────
        if close < FILTER_CONFIG["min_harga"]:
            alasan_buang[ticker] = f"gocap: Rp {close:.0f}"
            continue

        # ── Filter 2: Buang volume tipis ─────────────────
        nilai_transaksi = close * volume
        if nilai_transaksi < FILTER_CONFIG["min_volume_harian"]:
            alasan_buang[ticker] = f"volume tipis: Rp {nilai_transaksi/1e6:.1f}jt"
            continue

        # ── Filter 3: Buang tren turun kuat ──────────────
        close_series = df["close"]
        high_30d     = close_series.iloc[-31:-1].max()
        drawdown     = (close / high_30d) - 1
        if drawdown < FILTER_CONFIG["max_drawdown_30d"]:
            alasan_buang[ticker] = f"drawdown 30d: {drawdown:.1%}"
            continue

        # ── Filter 4: Harga di bawah MA50 DAN MA200 ──────
        if len(df) >= 200:
            ma50  = close_series.rolling(50).mean().iloc[-1]
            ma200 = close_series.rolling(200).mean().iloc[-1]
            if close < ma50 and close < ma200:
                alasan_buang[ticker] = "di bawah MA50 dan MA200"
                continue

        lolos[ticker] = df

    print(f"[Filter] {len(dict_ohlcv)} saham → {len(lolos)} lolos "
          f"({len(alasan_buang)} dibuang)")
    return lolos


# ════════════════════════════════════════════════════════════
#  BUAT DATASET LATIH — LABEL Y (HIJAU/MERAH)
# ════════════════════════════════════════════════════════════

def buat_label(df: pd.DataFrame, target_pct: float = 0.0) -> pd.Series:
    """
    Buat label Y: 1 jika harga besok naik, 0 jika turun.
    df         : DataFrame OHLCV
    target_pct : threshold return (default 0% = naik saja)
    """
    return (df["close"].pct_change().shift(-1) > target_pct).astype(int)


def buat_dataset_latih(dict_ohlcv: dict) -> pd.DataFrame:
    """
    Gabungkan semua saham menjadi 1 dataset latih besar.
    Setiap baris = 1 saham × 1 hari.
    """
    semua_df = []

    for ticker, df_raw in dict_ohlcv.items():
        df = hitung_indikator_teknikal(df_raw.copy())

        # Tentukan sektor
        sektor = "lainnya"
        for nama_sektor, info in SECTORS.items():
            kode = ticker.replace(".JK", "")
            if kode in info["emiten"]:
                sektor = nama_sektor
                break

        df["ticker"] = ticker
        df["sektor"] = sektor
        df["label"]  = buat_label(df)

        semua_df.append(df)

    if not semua_df:
        return pd.DataFrame()

    gabungan = pd.concat(semua_df, ignore_index=False)
    gabungan = gabungan.dropna(subset=["label", "rsi", "macd"])
    gabungan = gabungan.replace([np.inf, -np.inf], np.nan).dropna()

    print(f"[Dataset] Total baris: {len(gabungan):,} "
          f"| Saham unik: {gabungan['ticker'].nunique()} "
          f"| Positif: {gabungan['label'].mean():.1%}")
    return gabungan


# ════════════════════════════════════════════════════════════
#  DAFTAR FITUR YANG DIPAKAI MODEL
# ════════════════════════════════════════════════════════════

FITUR_TEKNIKAL = [
    "above_ma20", "above_ma50", "above_ma200",
    "rsi", "rsi_oversold", "rsi_overbought", "rsi_reversal",
    "macd", "macd_hist", "macd_bullish",
    "bb_pct", "bb_squeeze",
    "vol_ratio",
    "return_lag1", "return_lag3", "return_lag5",
    "volatility_5d", "volatility_20d",
    "body_size", "upper_wick", "lower_wick",
]

FITUR_SUPPLY_DEMAND = [
    "volume_ratio", "volume_spike",
    "akumulasi", "distribusi",
    "momentum_5d", "is_breakout",
]

FITUR_KALENDER = [
    "bulan_hijri", "is_ramadan", "is_syawal",
    "days_to_lebaran", "days_after_lebaran",
    "is_libur_lebaran", "is_idul_adha_week",
    "bulan", "is_januari", "is_desember",
    "days_to_year_end", "is_quarter_end",
    "is_window_dressing", "is_christmas",
    "is_new_year_period", "is_jumat", "is_senin", "is_eve_libur",
]

FITUR_SENTIMEN = [
    "skor_sentimen", "jumlah_positif",
    "jumlah_negatif", "buzz_score",
]

FITUR_KOMODITAS = [
    "coal_pct", "cpo_pct", "nickel_pct", "oil_pct", "gold_pct",
    "coal_lag1", "cpo_lag1", "nickel_lag1", "oil_lag1", "gold_lag1",
]

FITUR_CUACA = [
    "suhu_max", "suhu_min", "hujan_mm", "angin_max", "is_banjir",
]

SEMUA_FITUR = (
    FITUR_SUPPLY_DEMAND +
    FITUR_TEKNIKAL +
    FITUR_KOMODITAS +
    FITUR_SENTIMEN +
    FITUR_KALENDER +
    FITUR_CUACA
)
