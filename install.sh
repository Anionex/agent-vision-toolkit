#!/usr/bin/env bash
# Install the Codex DeepSeek vision proxy on macOS.
set -euo pipefail

WITH_GLANCE=0
NO_START=0
HEADER_COMPAT=0
REASONING_SUMMARY=0
usage() {
  cat <<'EOF'
Usage: ./install.sh [options]
  --with-glance               install the standalone glance CLI
  --codex-header-compat       strip Codex identity headers upstream
  --inject-reasoning-summary  synthesize reasoning summaries (buffers SSE)
  --no-start                  write files without starting launchd (tests)
EOF
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-glance) WITH_GLANCE=1 ;;
    --codex-header-compat) HEADER_COMPAT=1 ;;
    --inject-reasoning-summary) REASONING_SUMMARY=1 ;;
    --no-start) NO_START=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/codex-deepseek-vision}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/codex-deepseek-vision}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
ENV_SOURCE="${ENV_SOURCE:-$REPO_DIR/.env}"
ENV_INSTALLED="$CONFIG_DIR/env"
PLIST="${PLIST:-$HOME/Library/LaunchAgents/com.codex.deepseek-vision-proxy.plist}"
LABEL="com.codex.deepseek-vision-proxy"
LOG="$CODEX_HOME/log/deepseek-vision-proxy.log"
PYTHON="${PYTHON:-$(command -v python3)}"

[[ -f "$ENV_SOURCE" ]] || { echo "missing .env; run: cp .env.example .env" >&2; exit 1; }
chmod 600 "$ENV_SOURCE"
env_value() {
  awk -F= -v key="$1" '$1 == key {value=substr($0, index($0, "=")+1); gsub(/^[[:space:]"]+|[[:space:]"]+$/, "", value); print value; exit}' "$ENV_SOURCE"
}
PORT="$(env_value PORT)"; PORT="${PORT:-19100}"
SLUG="$(env_value MODEL_SLUG)"; SLUG="${SLUG:-deepseek-v4-flash-vision}"
UPSTREAM="$(env_value DEEPSEEK_BASE_URL)"; UPSTREAM="${UPSTREAM:-https://api.deepseek.com}"
UPSTREAM_MODEL="$(env_value UPSTREAM_MODEL)"; UPSTREAM_MODEL="${UPSTREAM_MODEL:-deepseek-v4-flash}"
for key in DEEPSEEK_API_KEY VISION_API_KEY VISION_BASE_URL VISION_MODEL; do
  [[ -n "$(env_value "$key")" ]] || { echo "missing $key in .env" >&2; exit 1; }
done
if [[ $WITH_GLANCE -eq 1 && -e "$BIN_DIR/glance" ]] && ! grep -q 'codex-deepseek-vision/bin/glance' "$BIN_DIR/glance"; then
  echo "glance already exists: $BIN_DIR/glance" >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR/bin" "$CONFIG_DIR" "$CODEX_HOME/log" "$(dirname "$PLIST")"
install -m 755 "$REPO_DIR/deepseek-vision-proxy.py" "$INSTALL_DIR/deepseek-vision-proxy.py"
install -m 644 "$REPO_DIR/vision_client.py" "$INSTALL_DIR/vision_client.py"
install -m 755 "$REPO_DIR/bin/glance" "$INSTALL_DIR/bin/glance"
install -m 600 "$ENV_SOURCE" "$ENV_INSTALLED"

STAMP="$(date +%Y%m%d-%H%M%S)-$$"
for file in "$CODEX_HOME/config.toml" "$CODEX_HOME/cc-switch-model-catalog.json" "$PLIST"; do
  [[ -f "$file" ]] && cp -p "$file" "$file.bak-$STAMP"
done

EXTRA_ARGS=()
[[ $HEADER_COMPAT -eq 1 ]] && EXTRA_ARGS+=("--codex-header-compat")
[[ $REASONING_SUMMARY -eq 1 ]] && EXTRA_ARGS+=("--inject-reasoning-summary")
CONFIG="$CODEX_HOME/config.toml" CATALOG="$CODEX_HOME/cc-switch-model-catalog.json" \
TEMPLATE="$REPO_DIR/catalog-model.template.json" SLUG="$SLUG" PORT="$PORT" \
UPSTREAM_MODEL="$UPSTREAM_MODEL" PYTHON="$PYTHON" SCRIPT="$INSTALL_DIR/deepseek-vision-proxy.py" \
UPSTREAM="$UPSTREAM" ENV_INSTALLED="$ENV_INSTALLED" LOG="$LOG" PLIST="$PLIST" \
EXTRA_ARGS="${EXTRA_ARGS[*]:-}" REASONING_SUMMARY="$REASONING_SUMMARY" "$PYTHON" - <<'PY'
import json, os, plistlib, shlex
from pathlib import Path

config_path = Path(os.environ["CONFIG"])
lines = config_path.read_text().splitlines() if config_path.exists() else []
top = {
    "model_provider": 'model_provider = "deepseek_vision"',
    "model": f'model = "{os.environ["SLUG"]}"',
    "model_catalog_json": 'model_catalog_json = "cc-switch-model-catalog.json"',
}
first_section = next((i for i, line in enumerate(lines) if line.strip().startswith("[")), len(lines))
for key, value in top.items():
    found = next((i for i in range(first_section) if lines[i].strip().split("=", 1)[0].strip() == key), None)
    if found is None:
        lines.insert(first_section, value); first_section += 1
    else:
        lines[found] = value

header = "[model_providers.deepseek_vision]"
try:
    start = next(i for i, line in enumerate(lines) if line.strip() == header)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
except StopIteration:
    lines += ([""] if lines and lines[-1].strip() else []) + [header]
    start, end = len(lines) - 1, len(lines)
provider = {
    "name": 'name = "DeepSeek Vision Proxy"',
    "base_url": f'base_url = "http://127.0.0.1:{os.environ["PORT"]}"',
    "wire_api": 'wire_api = "responses"',
    "requires_openai_auth": "requires_openai_auth = false",
}
for key, value in provider.items():
    found = next((i for i in range(start + 1, end) if lines[i].strip().split("=", 1)[0].strip() == key), None)
    if found is None:
        lines.insert(end, value); end += 1
    else:
        lines[found] = value
config_path.write_text("\n".join(lines).rstrip() + "\n")

catalog_path = Path(os.environ["CATALOG"])
data = json.loads(catalog_path.read_text()) if catalog_path.exists() else {"models": []}
models = data if isinstance(data, list) else data.setdefault("models", [])
template = json.loads(Path(os.environ["TEMPLATE"]).read_text())
template["slug"] = os.environ["SLUG"]
template["supports_reasoning_summaries"] = os.environ["REASONING_SUMMARY"] == "1"
existing = next((item for item in models if item.get("slug") == template["slug"]), None)
if existing is None:
    models.append(template)
else:
    for key, value in template.items():
        existing.setdefault(key, value)
    modalities = existing.setdefault("input_modalities", [])
    for modality in ("text", "image"):
        if modality not in modalities:
            modalities.append(modality)
    existing["supports_reasoning_summaries"] = template["supports_reasoning_summaries"]
catalog_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

args = [os.environ["PYTHON"], os.environ["SCRIPT"], "--port", os.environ["PORT"],
        "--upstream", os.environ["UPSTREAM"], "--env-file", os.environ["ENV_INSTALLED"],
        "--model-map", os.environ["SLUG"] + "=" + os.environ["UPSTREAM_MODEL"],
        "--log", os.environ["LOG"]] + shlex.split(os.environ.get("EXTRA_ARGS", ""))
with open(os.environ["PLIST"], "wb") as handle:
    plistlib.dump({"Label": "com.codex.deepseek-vision-proxy", "ProgramArguments": args,
                   "RunAtLoad": True, "KeepAlive": True,
                   "StandardErrorPath": os.environ["LOG"]}, handle)
PY
chmod 600 "$PLIST"

if [[ $WITH_GLANCE -eq 1 ]]; then
  mkdir -p "$BIN_DIR"
  WRAPPER="$BIN_DIR/glance"
  printf '#!/bin/sh\nexec %q %q "$@"\n' "$PYTHON" "$INSTALL_DIR/bin/glance" > "$WRAPPER"
  chmod 755 "$WRAPPER"
  echo "glance installed: $WRAPPER"
  case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "add to PATH: export PATH=\"$BIN_DIR:\$PATH\"" ;; esac
fi

if [[ $NO_START -eq 0 ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
fi

echo "installed: model=$SLUG proxy=127.0.0.1:$PORT"
echo "restart Codex, then run: ./verify.sh"
