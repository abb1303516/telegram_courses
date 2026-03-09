#!/bin/bash
set -e

APP_DIR="/opt/telegram-courses"
SERVICE="telegram-courses"

echo "=== Deploying Telegram Courses ==="

cd "$APP_DIR"

echo "1. Pulling latest code..."
git pull origin main

echo "2. Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt --quiet

echo "3. Restarting service..."
sudo systemctl restart "$SERVICE"

echo "4. Status:"
sudo systemctl status "$SERVICE" --no-pager -l

echo ""
echo "=== Deployment complete ==="
