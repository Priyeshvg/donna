#!/bin/bash
# Deploy Donna AI to EC2
# Usage: ./deploy/deploy-ec2.sh <EC2-IP-OR-HOSTNAME>

set -e

if [ -z "$1" ]; then
    echo "Usage: ./deploy/deploy-ec2.sh <EC2-IP-OR-HOSTNAME>"
    echo "Example: ./deploy/deploy-ec2.sh 54.123.45.67"
    echo "Example: ./deploy/deploy-ec2.sh donna.yourdomain.com"
    exit 1
fi

EC2_HOST="$1"
EC2_USER="ubuntu"
REMOTE_PATH="/opt/donna-ai"

echo "=== Deploying Donna AI to $EC2_HOST ==="

# Step 1: Rsync code to EC2
echo ""
echo "[1/3] Syncing code to EC2..."
rsync -avz --delete \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '.git' \
    --exclude '.env' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude 'tests/' \
    "$(dirname "$0")/../" \
    "${EC2_USER}@${EC2_HOST}:${REMOTE_PATH}/"

# Step 2: Install any new dependencies
echo ""
echo "[2/3] Installing dependencies..."
ssh "${EC2_USER}@${EC2_HOST}" "cd ${REMOTE_PATH} && source venv/bin/activate && pip install -q -r server/requirements.txt"

# Step 3: Restart the service
echo ""
echo "[3/3] Restarting donna-ai service..."
ssh "${EC2_USER}@${EC2_HOST}" "sudo systemctl restart donna-ai"

# Show status
echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Checking service status..."
ssh "${EC2_USER}@${EC2_HOST}" "sudo systemctl status donna-ai --no-pager -l | head -20"

echo ""
echo "To view logs: ssh ${EC2_USER}@${EC2_HOST} 'sudo journalctl -u donna-ai -f'"
