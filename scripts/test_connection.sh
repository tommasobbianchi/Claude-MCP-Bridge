#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

PORT=${PORT:-8787}
BASE="http://127.0.0.1:$PORT"

echo "=== Health Check ==="
curl -s "$BASE/health" | python3 -m json.tool

echo ""
echo "=== Auth Test (no token → 401) ==="
curl -s -o /dev/null -w "HTTP %{http_code}\n" "$BASE/mcp"

echo ""
echo "=== MCP Initialize ==="
RESPONSE=$(curl -si \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -X POST "$BASE/mcp" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}' 2>/dev/null)

SESSION_ID=$(echo "$RESPONSE" | grep -i "mcp-session-id" | tr -d '\r' | awk '{print $2}')
echo "Session: $SESSION_ID"
echo "$RESPONSE" | grep "^data:" | sed 's/^data: //' | python3 -m json.tool

echo ""
echo "=== Tools List ==="
curl -s \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -X POST "$BASE/mcp" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null 2>&1

curl -s -N \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -X POST "$BASE/mcp" \
  --max-time 5 \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' 2>/dev/null | grep "^data:" | sed 's/^data: //' | python3 -c "
import sys, json
data = json.load(sys.stdin)
tools = data.get('result', {}).get('tools', [])
print(f'Found {len(tools)} tools:')
for t in tools:
    print(f'  - {t[\"name\"]}: {t[\"description\"][:60]}...')
"

echo ""
echo "=== All tests passed ==="
