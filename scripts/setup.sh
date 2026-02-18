#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Claude MCP Bridge Setup ==="

# 1. Generate Bearer token if .env doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    TOKEN=$(openssl rand -base64 32)
    sed -i "s/BEARER_TOKEN=changeme/BEARER_TOKEN=$TOKEN/" .env
    echo "Generated Bearer token in .env"
else
    echo ".env already exists, skipping token generation"
    TOKEN=$(grep BEARER_TOKEN .env | cut -d= -f2-)
fi

# 2. Install dependencies
echo "Installing dependencies with uv..."
uv sync

# 3. Verify claude CLI
if command -v claude &>/dev/null; then
    echo "Claude CLI: $(claude --version 2>/dev/null || echo 'available')"
else
    echo "WARNING: claude CLI not found in PATH"
fi

# 4. Create log directory
mkdir -p ~/.local/share/mcp-bridge
echo "Log directory: ~/.local/share/mcp-bridge"

# 5. Setup Tailscale Funnel
echo ""
echo "Configuring Tailscale Funnel on port 10000..."
if tailscale funnel --https=10000 --bg http://localhost:8787 2>/dev/null; then
    PUBLIC_URL="https://$(tailscale status --json | python3 -c 'import sys,json; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
    echo "Public URL: ${PUBLIC_URL}:10000"
else
    echo "WARNING: Tailscale Funnel setup failed. Configure manually."
    PUBLIC_URL="https://<your-hostname>.ts.net"
fi

# 6. Optionally install systemd service
echo ""
read -p "Install systemd service? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo cp systemd/mcp-bridge.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable mcp-bridge
    sudo systemctl start mcp-bridge
    echo "Service installed and started"
fi

# 7. Print instructions
echo ""
echo "=== SETUP COMPLETE ==="
echo ""
echo "To connect from claude.ai:"
echo "  1. Go to claude.ai -> Settings -> Integrations"
echo "  2. Add custom connector"
echo "  3. URL: ${PUBLIC_URL}:10000/mcp"
echo "  4. Authorization header: Bearer $TOKEN"
echo ""
echo "Test locally:"
echo "  curl http://127.0.0.1:8787/health"
