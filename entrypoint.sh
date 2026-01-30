#!/bin/bash
set -e

cd /app

REPO_URL="https://github.com/platinboi/runpod-gpu-suite.git"

# Always fresh clone - reliable, fast with --depth 1
echo "Fetching latest code from GitHub..."
rm -rf /app/src_repo
git clone --depth 1 "$REPO_URL" /app/src_repo

# Copy src to expected location
rm -rf /app/src
cp -r /app/src_repo/src /app/src

echo "Code version: $(cd /app/src_repo && git rev-parse --short HEAD)"
echo "Starting handler..."
exec python -u /app/src/handler.py
