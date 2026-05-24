#!/usr/bin/env bash
set -e

echo "=== Zak Setup ==="

# Create venv if not present
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Created .venv"
fi

# Activate
source .venv/bin/activate

# Install deps
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "Dependencies installed"

# Scaffold .env if not present
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env — fill in your API keys"
fi

# Create data dirs
mkdir -p data/audit data/credentials

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env — add OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
echo "  2. Edit soul.md — name your agent and define its personality"
echo "  3. Edit config.yaml — set timezone, enable integrations"
echo "  4. Run: source .venv/bin/activate && python zak.py start"
echo ""
echo "For Google OAuth (Gmail/Calendar):"
echo "  - Enable Gmail API and Calendar API in Google Cloud Console"
echo "  - Download client_secret.json → data/credentials/client_secret.json"
echo "  - Set integrations.gmail.enabled: true in config.yaml"
echo "  - First run will open a browser for OAuth"
echo ""
echo "To import Alfred data: python zak.py migrate --alfred-dir /path/to/alfred/memory"
