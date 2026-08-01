#!/usr/bin/env bash
# Verify the proxy, Codex configuration, and optional live image path.
set -uo pipefail

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
ENV_FILE="${CODEX_DEEPSEEK_VISION_ENV:-$HOME/.config/codex-deepseek-vision/env}"
IMG="${1:-}"
FAIL=0

read_env() {
  [[ -f "$ENV_FILE" ]] || return 0
  awk -F= -v key="$1" '$1 == key {value=substr($0, index($0, "=")+1); gsub(/^[[:space:]"]+|[[:space:]"]+$/, "", value); print value; exit}' "$ENV_FILE"
}
PORT="${PORT:-$(read_env PORT)}"; PORT="${PORT:-19100}"
SLUG="${SLUG:-$(read_env MODEL_SLUG)}"; SLUG="${SLUG:-deepseek-v4-flash-vision}"

echo "== 1. proxy liveness"
if python3 - "$PORT" <<'PY'
import socket, sys
with socket.socket() as s:
    s.settimeout(1)
    raise SystemExit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
then echo "   OK: 127.0.0.1:$PORT"; else echo "   FAIL: proxy is not listening"; FAIL=1; fi

echo "== 2. Codex config and catalog"
if python3 - "$CODEX_HOME" "$SLUG" "$PORT" <<'PY'
import json, pathlib, sys, tomllib
home, slug, port = pathlib.Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
config = tomllib.loads((home / "config.toml").read_text())
assert config.get("model") == slug, (config.get("model"), slug)
provider = config.get("model_providers", {}).get("deepseek_vision", {})
assert provider.get("base_url") == f"http://127.0.0.1:{port}", provider
data = json.loads((home / "cc-switch-model-catalog.json").read_text())
models = data if isinstance(data, list) else data["models"]
model = next(item for item in models if item.get("slug") == slug)
assert "image" in model.get("input_modalities", []), model
print(f"   OK: model={slug}, display_name={model.get('display_name')!r}")
PY
then :; else echo "   FAIL: invalid config or catalog"; FAIL=1; fi

echo "== 3. local env"
if [[ -f "$ENV_FILE" ]]; then
  MODE="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE" 2>/dev/null || true)"
  [[ "$MODE" == "600" ]] && echo "   OK: env permissions=600" || { echo "   FAIL: env permissions=$MODE"; FAIL=1; }
else
  echo "   FAIL: missing $ENV_FILE"; FAIL=1
fi

echo "== 4. optional live image round trip"
if [[ -n "$IMG" ]]; then
  python3 "$(dirname "$0")/test_view_image_chain.py" --proxy "http://127.0.0.1:$PORT/responses" --model "$SLUG" --env-file "$ENV_FILE" "$IMG" || FAIL=1
else
  echo "   skip (pass an image path to test the real APIs)"
fi

echo
[[ $FAIL -eq 0 ]] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit $FAIL
