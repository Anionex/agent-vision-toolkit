#!/usr/bin/env bash
# One-click installer for codex-vision-proxy (macOS / Linux)
#
# Automates the steps in AGENT_INSTALL.md:
#   1. locate & back up Codex config     2. prepare install dir + vision env
#   3. start the proxy                    4. repoint Codex base_url
#   5. add "image" to the model catalog   6. background service
#   7. verify
#
# Usage:
#   ./install.sh [--port 19100] [--non-interactive] [--no-start] [--no-verify]
#                [--codex-header-compat] [--inject-reasoning-summary]
#
# Env overrides (also used by --non-interactive):
#   VISION_API_KEY VISION_BASE_URL VISION_MODEL LANG CODEX_HOME INSTALL_DIR ENV_FILE
set -euo pipefail

PORT=19100
NON_INTERACTIVE=0
START=1
VERIFY=1
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    --no-start) START=0; shift ;;
    --no-verify) VERIFY=0; shift ;;
    --codex-header-compat) EXTRA_ARGS+=(--codex-header-compat); shift ;;
    --inject-reasoning-summary) EXTRA_ARGS+=(--inject-reasoning-summary); shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

log()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- 0. prerequisites ----------
command -v python3 >/dev/null 2>&1 || die "python3 not found (Python 3.11+ required)"
PY=$(command -v python3)
python3 -c 'import sys, tomllib; assert sys.version_info >= (3, 11)' 2>/dev/null \
  || die "Python 3.11+ required (tomllib); found: $(python3 --version 2>&1)"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
test -f "$REPO_DIR/codex-vision-proxy.py" || die "codex-vision-proxy.py not found next to install.sh"

# ---------- 1. locate Codex config ----------
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CONFIG="$CODEX_HOME/config.toml"
test -f "$CONFIG" || die "Codex config not found at $CONFIG (set CODEX_HOME if custom)"

# ---------- parse config via python (tomllib) ----------
{
  read -r PROVIDER
  read -r MODEL
  read -r UPSTREAM
  read -r CATALOG
} < <(
  python3 - "$CONFIG" "$CODEX_HOME" <<'PYEOF'
import sys, tomllib, pathlib
config_path, codex_home = sys.argv[1], sys.argv[2]
with open(config_path, "rb") as f:
    cfg = tomllib.load(f)
provider = cfg.get("model_provider") or ""
model = cfg.get("model") or ""
upstream = ""
if provider:
    p = (cfg.get("model_providers") or {}).get(provider, {})
    upstream = p.get("base_url") or ""
catalog = cfg.get("model_catalog_json") or ""
if catalog and not pathlib.Path(catalog).is_absolute():
    catalog = str(pathlib.Path(codex_home) / catalog)
print(provider)
print(model)
print(upstream)
print(catalog)
PYEOF
)

[[ -n "$PROVIDER" && -n "$MODEL" ]] || die "Could not read model_provider/model from $CONFIG"
[[ -n "$UPSTREAM" ]] || die "Could not read base_url for provider '$PROVIDER'"
if [[ "$UPSTREAM" == *"127.0.0.1:$PORT"* || "$UPSTREAM" == *"localhost:$PORT"* ]]; then
  die "Codex already points at $UPSTREAM — cannot discover the real upstream. Restore from a backup first."
fi

log "Provider: $PROVIDER | model: $MODEL | upstream: $UPSTREAM"

# ---------- backups ----------
TS=$(date +%Y%m%d-%H%M%S)
cp "$CONFIG" "$CONFIG.vision-proxy.bak.$TS"
log "Backed up $CONFIG -> $CONFIG.vision-proxy.bak.$TS"
if [[ -n "$CATALOG" && -f "$CATALOG" ]]; then
  cp "$CATALOG" "$CATALOG.vision-proxy.bak.$TS"
  log "Backed up catalog -> $CATALOG.vision-proxy.bak.$TS"
fi

# ---------- 2. install dir + vision env ----------
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/codex-vision-proxy}"
ENV_FILE="${ENV_FILE:-$HOME/.config/codex-vision-proxy/env}"
mkdir -p "$INSTALL_DIR" "$(dirname "$ENV_FILE")"
cp -f "$REPO_DIR/codex-vision-proxy.py" "$INSTALL_DIR/"
cp -f "$REPO_DIR/vision_client.py" "$INSTALL_DIR/"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$REPO_DIR/.env.example" "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

# read existing values (defaults from .env.example)
env_get() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true; }
VISION_API_KEY="${VISION_API_KEY:-$(env_get VISION_API_KEY)}"
VISION_BASE_URL="${VISION_BASE_URL:-$(env_get VISION_BASE_URL)}"
VISION_BASE_URL="${VISION_BASE_URL:-https://api.inferera.com/v1}"
VISION_MODEL="${VISION_MODEL:-$(env_get VISION_MODEL)}"
VISION_MODEL="${VISION_MODEL:-gemini-3.6-flash}"
LANG_OUT="${LANG:-$(env_get LANG)}"
LANG_OUT="${LANG_OUT:-zh}"

if [[ -z "$VISION_API_KEY" ]]; then
  if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    die "VISION_API_KEY is not set (use --non-interactive with VISION_API_KEY env)"
  fi
  read -r -p "Vision API key (for $VISION_BASE_URL): " VISION_API_KEY
  [[ -n "$VISION_API_KEY" ]] || die "API key required"
fi

cat > "$ENV_FILE" <<EOF
VISION_API_KEY=$VISION_API_KEY
VISION_BASE_URL=$VISION_BASE_URL
VISION_MODEL=$VISION_MODEL
LANG=$LANG_OUT
EOF
chmod 600 "$ENV_FILE"
log "Vision config written to $ENV_FILE"

# ---------- 3. start proxy ----------
PIDFILE="$INSTALL_DIR/proxy.pid"
start_proxy() {
  nohup "$PY" "$INSTALL_DIR/codex-vision-proxy.py" \
    --port "$PORT" --upstream "$UPSTREAM" --env-file "$ENV_FILE" \
    --log "$INSTALL_DIR/proxy.log" "${EXTRA_ARGS[@]}" >/dev/null 2>&1 &
  echo $! > "$PIDFILE"
}
if [[ "$START" -eq 1 ]]; then
  start_proxy
  sleep 1
  if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    warn "Proxy exited immediately — see $INSTALL_DIR/proxy.log (continuing with config changes anyway)"
  else
    log "Proxy started (pid $(cat "$PIDFILE"), port $PORT)"
  fi
else
  log "Skipping proxy start (--no-start)"
fi

# ---------- 4. repoint Codex base_url ----------
python3 - "$CONFIG" "$PROVIDER" "$PORT" <<'PYEOF'
import re, sys
path, provider, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
text = open(path, encoding="utf-8").read()
pat = re.compile(r"(\[model_providers\." + re.escape(provider) + r"\][^\[]*?base_url\s*=\s*\")[^\"]*(\")", re.S)
new, n = pat.subn(r"\1http://127.0.0.1:%d\2" % port, text, count=1)
if n != 1:
    sys.exit("Could not locate base_url inside [model_providers.%s]" % provider)
open(path, "w", encoding="utf-8").write(new)
print("base_url -> http://127.0.0.1:%d for provider '%s'" % (port, provider))
PYEOF

# ---------- 5. catalog: add "image" modality ----------
if [[ -n "$CATALOG" && -f "$CATALOG" ]]; then
  python3 - "$CATALOG" "$MODEL" <<'PYEOF'
import json, sys
path, model = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
models = data.get("models", data) if isinstance(data, dict) else data
entries = models if isinstance(models, list) else models.get("models", [])
target = None
for e in entries:
    if isinstance(e, dict) and (e.get("slug") == model or e.get("name") == model or e.get("id") == model):
        target = e
        break
if target is None:
    sys.exit("catalog entry for model '%s' not found (skipped)" % model)
mods = target.get("input_modalities")
if mods == ["text"]:
    target["input_modalities"] = ["text", "image"]
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("catalog: input_modalities -> [text, image] for '%s'" % model)
elif isinstance(mods, list) and "image" in mods:
    print("catalog: already supports image (no change)")
else:
    print("catalog: input_modalities = %s (left untouched)" % (mods or "unset"))
PYEOF
else
  warn "No model catalog file found — skipping modality edit. If Codex rejects view_image, see AGENT_INSTALL.md troubleshooting."
fi

# ---------- 6. background service ----------
if [[ "$START" -eq 1 ]]; then
  if [[ "$(uname)" == "Darwin" ]]; then
    PLIST="$HOME/Library/LaunchAgents/com.codex.vision-proxy.plist"
    mkdir -p "$(dirname "$PLIST")"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.codex.vision-proxy</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>$INSTALL_DIR/codex-vision-proxy.py</string>
    <string>--port</string><string>$PORT</string>
    <string>--upstream</string><string>$UPSTREAM</string>
    <string>--env-file</string><string>$ENV_FILE</string>
    <string>--log</string><string>$INSTALL_DIR/proxy.log</string>
    $(for a in "${EXTRA_ARGS[@]}"; do echo "<string>$a</string>"; done)
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$INSTALL_DIR/proxy.log</string>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/proxy.log</string>
</dict></plist>
EOF
    launchctl bootout "gui/$(id -u)/com.codex.vision-proxy" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    launchctl kickstart -k "gui/$(id -u)/com.codex.vision-proxy" 2>/dev/null || true
    log "LaunchAgent installed: $PLIST"
  elif [[ -d /run/systemd/system || -d /etc/systemd/system ]]; then
    UNIT="$HOME/.config/systemd/user/codex-vision-proxy.service"
    mkdir -p "$(dirname "$UNIT")"
    cat > "$UNIT" <<EOF
[Unit]
Description=codex-vision-proxy
After=network.target

[Service]
ExecStart=$PY $INSTALL_DIR/codex-vision-proxy.py --port $PORT --upstream $UPSTREAM --env-file $ENV_FILE --log $INSTALL_DIR/proxy.log ${EXTRA_ARGS[*]}
Restart=on-failure

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now codex-vision-proxy.service
    log "systemd user service installed: $UNIT"
  else
    warn "Unknown init system — proxy runs in background via nohup (pid file $PIDFILE)"
  fi
fi

# ---------- 7. verify ----------
if [[ "$VERIFY" -eq 1 ]]; then
  "$PY" -m py_compile "$INSTALL_DIR/codex-vision-proxy.py" "$INSTALL_DIR/vision_client.py" \
    && log "py_compile OK"
  if command -v nc >/dev/null 2>&1; then
    if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
      log "Port $PORT is listening"
    else
      warn "Port $PORT not listening yet — check $INSTALL_DIR/proxy.log"
    fi
  fi
fi

log "Done. Fully restart Codex, then ask your DeepSeek model to view_image a local image."
log "Backups: $CONFIG.vision-proxy.bak.$TS"
[[ -n "$CATALOG" && -f "$CATALOG" ]] && log "Catalog backup: $CATALOG.vision-proxy.bak.$TS"
