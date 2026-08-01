#!/usr/bin/env bash
# End-to-end checks for the DeepSeek vision chain:
#   1. proxy is listening on the expected port
#   2. catalog model has image modality (view_image passes its check)
#   3. config points Codex at the proxy
#   4. optional: real image -> proxy -> glance -> DeepSeek round trip
#
# Usage: ./verify.sh [image-path]   (image-path triggers the live round trip)

set -uo pipefail

PORT="${PORT:-19100}"
SLUG="${SLUG:-gpt-5.2}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
IMG="${1:-}"
FAIL=0

echo "== 1. proxy liveness (port $PORT)"
if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "   OK: proxy listening on 127.0.0.1:$PORT"
else
  echo "   FAIL: nothing on 127.0.0.1:$PORT; run ./install.sh or launchctl kickstart"
  FAIL=1
fi

echo "== 2. catalog model '$SLUG' advertises image modality"
python3 - "$CODEX_HOME/cc-switch-model-catalog.json" "$SLUG" <<'EOF'
import json, sys
path, slug = sys.argv[1], sys.argv[2]
data = json.load(open(path))
models = data if isinstance(data, list) else data.get("models", data)
m = next((x for x in models if isinstance(x, dict) and x.get("slug") == slug), None)
if m is None:
    print("   FAIL: slug %r not found in catalog" % slug); sys.exit(1)
mods = m.get("input_modalities", [])
if "image" in mods:
    print("   OK: %s input_modalities=%s" % (slug, mods))
else:
    print("   FAIL: %s input_modalities=%s missing 'image'; view_image stays blocked" % (slug, mods))
    sys.exit(1)
EOF
[[ $? -ne 0 ]] && FAIL=1

echo "== 3. config base_url points at the proxy"
if rg -n 'base_url = "http://127\.0\.0\.1:'"$PORT"'"' "$CODEX_HOME/config.toml" >/dev/null 2>&1; then
  echo "   OK: base_url -> 127.0.0.1:$PORT"
else
  echo "   FAIL: config.toml base_url is not 127.0.0.1:$PORT"
  FAIL=1
fi

echo "== 4. live image round trip"
if [[ -n "$IMG" ]]; then
  python3 "$(dirname "$0")/test_view_image_chain.py" --proxy "http://127.0.0.1:$PORT/responses" "$IMG" || FAIL=1
else
  echo "   skip (pass an image path to run: ./verify.sh <image>)"
fi

echo
[[ $FAIL -eq 0 ]] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED (see above)"
exit $FAIL
