#!/bin/bash
set -e

cd /app

# GitHub repo URL (public repo, no auth needed)
REPO_URL="https://github.com/platinboi/runpod-gpu-suite.git"

# Clone or pull latest code
if [ -d "/app/src_repo/.git" ]; then
    echo "Pulling latest code..."
    cd /app/src_repo && git pull --ff-only && cd /app
else
    echo "Cloning repository..."
    rm -rf /app/src_repo
    git clone --depth 1 "$REPO_URL" /app/src_repo
fi

# Copy src to expected location
rm -rf /app/src
cp -r /app/src_repo/src /app/src

echo "Starting handler..."
exec python -u /app/src/handler.py
