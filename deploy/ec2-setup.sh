#!/bin/bash
# EC2 Setup Script for Donna AI
# Run this on a fresh Ubuntu 22.04 EC2 instance

set -e

echo "=== Donna AI EC2 Setup ==="

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Python 3.11
sudo apt-get install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip

# Install git and other tools
sudo apt-get install -y git curl nginx certbot python3-certbot-nginx

# Create app directory
sudo mkdir -p /opt/donna-ai
sudo chown ubuntu:ubuntu /opt/donna-ai

# Clone or copy the code (we'll rsync it)
cd /opt/donna-ai

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r server/requirements.txt

# Create systemd service
sudo tee /etc/systemd/system/donna-ai.service > /dev/null <<EOF
[Unit]
Description=Donna AI WhatsApp Assistant
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/donna-ai
Environment=PATH=/opt/donna-ai/venv/bin
EnvironmentFile=/opt/donna-ai/.env
ExecStart=/opt/donna-ai/venv/bin/python -m server.server --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable donna-ai
sudo systemctl start donna-ai

# Configure nginx as reverse proxy
sudo tee /etc/nginx/sites-available/donna-ai > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
        proxy_read_timeout 120s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/donna-ai /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "=== Setup Complete ==="
echo "Donna AI is running on port 8000"
echo "Nginx is proxying port 80 -> 8000"
echo ""
echo "Next steps:"
echo "1. Copy .env file to /opt/donna-ai/.env"
echo "2. sudo systemctl restart donna-ai"
echo "3. For HTTPS, run: sudo certbot --nginx -d yourdomain.com"
