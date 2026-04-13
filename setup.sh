#!/bin/bash
# ============================================================
# IHSG Predictor — Auto Setup Script
# Jalankan: bash setup.sh
# ============================================================

echo "============================================================"
echo "IHSG Predictor — Auto Setup"
echo "============================================================"

# 1. Clone repo
echo ""
echo "[1/5] Clone repo dari GitHub..."
if [ -d "ihsg-predictor" ]; then
    echo "  Folder sudah ada, pull update..."
    cd ihsg-predictor
    git pull
else
    git clone https://github.com/samudra-azygo/ihsg-predictor.git
    cd ihsg-predictor
fi

# 2. Install dependencies
echo ""
echo "[2/5] Install dependencies..."
pip3 install -r requirements.txt --quiet

# 3. Set environment variables
echo ""
echo "[3/5] Set environment variables..."
export TELEGRAM_TOKEN="8744135725:AAEv4foDXkJVogWJqr4d_xeICJ0dL64en-8"
export TELEGRAM_CHAT_ID="828736755"

# Simpan ke .env supaya tidak hilang
cat > .env << EOF
TELEGRAM_TOKEN=8744135725:AAEv4foDXkJVogWJqr4d_xeICJ0dL64en-8
TELEGRAM_CHAT_ID=828736755
EOF

echo "  .env tersimpan!"

# 4. Train model swing
echo ""
echo "[4/5] Training model swing (5-10 menit)..."
python3 train_swing.py

# 5. Test scoring
echo ""
echo "[5/5] Test scoring swing..."
python3 scoring_swing.py 2>&1

echo ""
echo "============================================================"
echo "SETUP SELESAI!"
echo "Langkah berikutnya:"
echo "  - Set jadwal di Tasks (PythonAnywhere)"
echo "  - Atau jalankan: python3 main.py"
echo "============================================================"
