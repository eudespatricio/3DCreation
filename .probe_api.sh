#!/usr/bin/env bash
set -u
PATH="$HOME/.local/bin:/home/eudespatricio/.gemini/antigravity/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH

echo "=== agentapi --help ==="
timeout 40 agentapi --help 2>&1 | head -30
echo "rc=$?"

echo
echo "=== processos antigravity / language_server ==="
ps aux 2>/dev/null | grep -iE 'antigravity|language_server' | grep -v grep | head -5

echo
echo "=== portas em LISTEN ==="
ss -lntp 2>/dev/null | head -15

echo
echo "=== token jetski (apenas metadados) ==="
ls -la "$HOME/.gemini/jetski-standalone-oauth-token" 2>/dev/null
python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / ".gemini" / "jetski-standalone-oauth-token"
try:
    d = json.loads(p.read_text())
    print("chaves do token:", sorted(d.keys()))
except Exception as e:
    print("nao e json:", type(e).__name__)
PY
