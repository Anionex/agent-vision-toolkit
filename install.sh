#!/usr/bin/env bash
# Install the DeepSeek vision-capable local proxy for Codex.
#
# What it does:
#   1. backs up anything it touches (config.toml, model catalog, proxy, plist)
#   2. installs the proxy script + launchd agent (port 19100 by default)
#   3. merges the catalog model entry (gpt-5.2 -> DeepSeek V4 Flash, image modality)
#   4. points Codex config at the local proxy
#
# After install: restart the Codex desktop app, then run ./verify.sh.
#
# Usage: ./install.sh [--port 19100] [--model gpt-5.2]

set -euo pipefail

PORT=19100
SLUG="gpt-5.2"
ENV_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --model) SLUG="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
LAUNCHERS="$CODEX_HOME/launchers"
PLIST="$HOME/Library/LaunchAgents/com.codex.deepseek-ua-rewrite-proxy.plist"
LABEL="com.codex.deepseek-ua-rewrite-proxy"
LOG="$LAUNCHERS/deepseek-ua-rewrite-proxy.err.log"
STAMP="$(date +%Y%m%d-%H%M%S)"
PYTHON="${PYTHON:-$(command -v python3)}"

# ---- .env: vision API credentials (no local tools required) ----
[[ -z "$ENV_FILE" && -f "$REPO_DIR/.env" ]] && ENV_FILE="$REPO_DIR/.env"
VISION_API_KEY=""
VISION_BASE_URL="https://api.inferera.com/v1"
VISION_MODEL="gemini-3.5-flash"
if [[ -n "$ENV_FILE" ]]; then
  VISION_API_KEY="$(awk -F= '/^VISION_API_KEY=/{gsub(/["'"'"' ]/, "", $2); print $2; exit}' "$ENV_FILE")"
  VISION_BASE_URL="$(awk -F= '/^VISION_BASE_URL=/{gsub(/["'"'"' ]/, "", $2); print $2; exit}' "$ENV_FILE")"
  [[ -z "$VISION_BASE_URL" ]] && VISION_BASE_URL="https://api.inferera.com/v1"
  VISION_MODEL="$(awk -F= '/^VISION_MODEL=/{gsub(/["'"'"' ]/, "", $2); print $2; exit}' "$ENV_FILE")"
  [[ -z "$VISION_MODEL" ]] && VISION_MODEL="gemini-3.5-flash"
  echo "==> .env loaded from $ENV_FILE"
else
  echo "==> no .env found; vision API key left empty (fall back to --glance-cmd if installed)"
  echo "    hint: cp .env.example .env and fill VISION_API_KEY to avoid extra installs"
fi

mkdir -p "$LAUNCHERS"

echo "==> installing proxy (port $PORT, model slug '$SLUG')"

# ---- 1. backups ----
for f in "$CODEX_HOME/config.toml" "$CODEX_HOME/cc-switch-model-catalog.json" \
         "$LAUNCHERS/deepseek-ua-rewrite-proxy.py" "$PLIST"; do
  [[ -f "$f" ]] && cp "$f" "$f.bak-$STAMP" && echo "    backup: $f -> $f.bak-$STAMP"
done

# ---- 2. proxy script + launchd agent ----
cp "$REPO_DIR/deepseek-ua-rewrite-proxy.py" "$LAUNCHERS/deepseek-ua-rewrite-proxy.py"
sed -e "s|__PYTHON__|$PYTHON|" \
    -e "s|__SCRIPT__|$LAUNCHERS/deepseek-ua-rewrite-proxy.py|" \
    -e "s|__PORT__|$PORT|" \
    -e "s|__LOG__|$LOG|" \
    -e "s|__VISION_API_KEY__|$VISION_API_KEY|" \
    -e "s|__VISION_BASE_URL__|$VISION_BASE_URL|" \
    -e "s|__VISION_MODEL__|$VISION_MODEL|" \
    "$REPO_DIR/launchd.plist.template" > "$PLIST"

if launchctl list 2>/dev/null | grep -q "$LABEL"; then
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
  echo "    launchd: reloaded $LABEL"
else
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "    launchd: bootstrapped $LABEL"
fi
sleep 1

# ---- 3. catalog entry merge ----
CATALOG_PATH="$CODEX_HOME/cc-switch-model-catalog.json" \
TEMPLATE_PATH="$REPO_DIR/catalog-model.template.json" \
python3 - "$SLUG" <<'EOF'
import json, sys
import os
slug = sys.argv[1]
catalog_path = os.environ["CATALOG_PATH"]
template = json.load(open(os.environ["TEMPLATE_PATH"]))
if template["slug"] != slug:
    template["slug"] = slug
    template["display_name"] = "DeepSeek V4 Flash"

data = json.load(open(catalog_path))
models = data if isinstance(data, list) else data.get("models", data)
if not isinstance(models, list):
    raise SystemExit("unexpected catalog structure: %r" % type(models))

existing = next((m for m in models if isinstance(m, dict) and m.get("slug") == slug), None)
if existing is None:
    models.append(template)
    print("    catalog: added model slug %r" % slug)
else:
    for k, v in template.items():
        existing.setdefault(k, v)
    print("    catalog: merged template fields into existing slug %r" % slug)

json.dump(data, open(catalog_path, "w"), ensure_ascii=False, indent=1)
print("    catalog: wrote", catalog_path)
EOF

# ---- 4. config.toml: point Codex at the local proxy ----
CONFIG_PATH="$CODEX_HOME/config.toml" \
python3 - "$SLUG" "$PORT" <<'EOF'
import sys
import os
slug, port = sys.argv[1], sys.argv[2]
path = os.environ["CONFIG_PATH"]
lines = open(path).read().splitlines()

def set_line(pred, new):
    for i, ln in enumerate(lines):
        if pred(ln):
            lines[i] = new
            return True
    return False

ok = True
ok &= set_line(lambda l: l.startswith("model_provider"), 'model_provider = "custom"')
ok &= set_line(lambda l: l.startswith("model ="), 'model = "%s"' % slug)
ok &= set_line(lambda l: l.startswith("model_catalog_json"),
               'model_catalog_json = "cc-switch-model-catalog.json"')

# inside the [model_providers.custom] section
in_custom = False
for i, ln in enumerate(lines):
    if ln.startswith("[model_providers."):
        in_custom = ln == "[model_providers.custom]"
        continue
    if in_custom and ln.startswith("base_url"):
        lines[i] = 'base_url = "http://127.0.0.1:%s"' % port
        ok &= True

if "[model_providers.custom]" not in "\n".join(lines):
    lines += ["", "[model_providers.custom]", 'name = "deepseek"',
              'base_url = "http://127.0.0.1:%s"' % port, 'wire_api = "responses"',
              "requires_openai_auth = true"]

open(path, "w").write("\n".join(lines) + "\n")
print("    config: pointed model '%s' at 127.0.0.1:%s" % (slug, port))
EOF

echo
echo "==> done. Next steps:"
echo "    1. restart the Codex desktop app (it caches config at startup)"
echo "    2. run ./verify.sh  (checks proxy, catalog, config)"
echo "    3. in a chat, send an image or ask the model to view_image <path>"
