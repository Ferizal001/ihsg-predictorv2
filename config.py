# ============================================================
#  config.py — Konfigurasi Utama Sistem Prediksi Saham IDX
# ============================================================

# ── Sumber data ──────────────────────────────────────────────
DATA_SOURCES = {
    "harga"     : "yfinance",           # Yahoo Finance (OHLCV)
    "komoditas" : "tradingeconomics",   # Trading Economics API
    "berita"    : ["bisnis.com", "kontan.co.id", "reuters.com/id"],
    "cuaca"     : "open-meteo.com",     # BMKG / Open-Meteo
}

# ── Komoditas yang dipantau ───────────────────────────────────
COMMODITIES = {
    "coal"  : "MTF=F",    # Batu bara
    "cpo"   : "FCPO.KL",  # CPO / Sawit
    "nickel": "NI=F",     # Nikel
    "oil"   : "BZ=F",     # Minyak Brent
    "gold"  : "GC=F",     # Emas
}

# ── Sektor saham IDX & relevansi komoditas ───────────────────
SECTORS = {
    "tambang"  : {"komoditas_bobot": 0.40, "emiten": ["ADRO","PTBA","ITMG","INCO","ANTM"]},
    "perbankan": {"komoditas_bobot": 0.05, "emiten": ["BBRI","BMRI","BBCA","BBNI","BRIS"]},
    "konsumer" : {"komoditas_bobot": 0.10, "emiten": ["UNVR","ICBP","MYOR","SIDO","KLBF"]},
    "agribisnis": {"komoditas_bobot": 0.35, "emiten": ["AALI","SIMP","LSIP","PALM","DSNG"]},
    "energi"   : {"komoditas_bobot": 0.30, "emiten": ["PGAS","AKRA","MEDC","ELSA","RUIS"]},
    "teknologi": {"komoditas_bobot": 0.05, "emiten": ["GOTO","BUKA","EMTK","DMMX","MTDL"]},
}

# ── Bobot scoring awal (akan di-override oleh model) ─────────
SCORING_WEIGHTS_DEFAULT = {
    "supply_demand": 0.35,
    "teknikal"     : 0.25,
    "komoditas"    : 0.20,
    "sentimen"     : 0.12,
    "kalender"     : 0.08,
}

# ── Parameter filter awal ────────────────────────────────────
FILTER_CONFIG = {
    "min_volume_harian"   : 500_000_000,   # Rp 500 juta/hari
    "min_harga"           : 100,           # Rp 100 (buang gocap)
    "max_drawdown_30d"    : -0.30,         # Turun >30% dalam 30 hari
    "min_market_cap"      : 100_000_000_000, # Rp 100 miliar
}

# ── Parameter small gains ────────────────────────────────────
TRADING_CONFIG = {
    "take_profit_pct"     : 0.020,   # Target profit +2%
    "stop_loss_pct"       : -0.010,  # Stop loss -1%
    "trailing_stop_pct"   : 0.010,   # Trailing stop 1%
    "max_posisi"          : 5,       # Maks 5 saham sekaligus
    "max_risiko_per_trade": 0.02,    # Maks 2% modal per trade
    "min_kas_pct"         : 0.20,    # Selalu sisakan 20% kas
    "min_biaya_worth_it"  : 0.015,   # Min profit 1.5% (tutup biaya)
    "biaya_transaksi"     : 0.004,   # 0.4% total beli+jual
}

# ── Parameter market regime ──────────────────────────────────
REGIME_CONFIG = {
    "vix_kuning"          : 20,      # VIX > 20 → kuning
    "vix_merah"           : 30,      # VIX > 30 → merah
    "ihsg_drop_merah"     : -0.03,   # IHSG turun >3% → merah
    "foreign_sell_hari"   : 3,       # Asing net sell >3 hari → kuning
    "akurasi_min_hijau"   : 0.60,    # Akurasi rolling > 60% → hijau
    "akurasi_min_kuning"  : 0.50,    # Akurasi rolling > 50% → kuning
    "portfolio_stop_loss" : -0.10,   # Portfolio turun 10% → merah
}

# ── Parameter retrain ────────────────────────────────────────
RETRAIN_CONFIG = {
    "jadwal_rutin_hari"   : 30,      # Retrain tiap 30 hari
    "drift_threshold"     : 0.50,    # Akurasi < 50% → retrain darurat
    "window_latih_tahun"  : 3,       # Pakai data 3 tahun terakhir
    "rolling_window_hari" : 14,      # Cek akurasi rolling 14 hari
}

# ── Lokasi file ──────────────────────────────────────────────
PATHS = {
    "data_dir"    : "data/",
    "model_dir"   : "models/",
    "log_dir"     : "logs/",
    "jurnal"      : "logs/jurnal_trading.csv",
    "akurasi_log" : "logs/akurasi_rolling.csv",
}
