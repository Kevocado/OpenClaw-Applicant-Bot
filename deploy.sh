#!/bin/bash
# ─── OpenClaw Applicant Bot — VPS Deployment Script ───
# Run this on your Contabo VPS (root@195.26.241.52)
# Prerequisite: Docker + Docker Compose already installed

set -e

echo "========================================="
echo "  OpenClaw Applicant Bot — VPS Setup"
echo "========================================="

# ─── Step 1: Clone the repo ───
echo ""
echo "[1/6] Cloning repository..."
cd /root
if [ -d "OpenClaw-Applicant-Bot" ]; then
    echo "  → Repo exists, pulling latest..."
    cd OpenClaw-Applicant-Bot
    git pull origin main
else
    git clone https://github.com/Kevocado/OpenClaw-Applicant-Bot.git
    cd OpenClaw-Applicant-Bot
fi

# ─── Step 2: Copy .env file ───
echo ""
echo "[2/6] Setting up environment..."
if [ ! -f ".env" ]; then
    echo "  ⚠️  No .env file found. Creating from template..."
    echo "  → IMPORTANT: Edit .env with your actual credentials after this script finishes!"
    cp .env.example .env 2>/dev/null || echo "  → No .env.example found, you'll need to create .env manually"
fi
echo "  → .env file ready"

# ─── Step 3: Install Python dependencies ───
echo ""
echo "[3/6] Installing Python dependencies..."
pip3 install --quiet -r requirements.txt
echo "  → Python deps installed"

# ─── Step 4: Create required directories ───
echo ""
echo "[4/6] Creating directories..."
mkdir -p screenshots user_data_dir logs
echo "  → screenshots/, user_data_dir/, logs/ created"

# ─── Step 5: Deploy OpenClaw config ───
echo ""
echo "[5/6] Deploying OpenClaw config..."
echo "  → openclaw.json is ready (127.0.0.1:8000, token auth, exec approval)"
cat openclaw.json

# ─── Step 6: Start Docker containers ───
echo ""
echo "[6/6] Starting n8n + PostgreSQL..."
docker compose up -d
echo ""
echo "  → Waiting 10s for containers to initialize..."
sleep 10
docker compose ps

echo ""
echo "========================================="
echo "  ✅ DEPLOYMENT COMPLETE!"
echo "========================================="
echo ""
echo "  n8n dashboard:  http://195.26.241.52:5678"
echo "  OpenClaw:       http://127.0.0.1:8000 (loopback only)"
echo ""
echo "  Next steps:"
echo "  1. Open http://195.26.241.52:5678 in your browser"
echo "  2. Log in with your N8N_BASIC_AUTH credentials"
echo "  3. Set up Gmail + Google Sheets credentials in n8n"
echo "  4. Import the n8n workflows"
echo "========================================="
