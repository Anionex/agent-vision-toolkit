#!/usr/bin/env bash
# Remove installed runtime files. User configuration backups are intentionally preserved.
set -euo pipefail

LABEL="com.codex.deepseek-vision-proxy"
PLIST="${PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/codex-deepseek-vision}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/codex-deepseek-vision}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

if [[ "${NO_LAUNCHCTL:-0}" != "1" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
fi
rm -f "$PLIST"
rm -rf "$INSTALL_DIR"
if [[ -f "$BIN_DIR/glance" ]] && grep -q 'codex-deepseek-vision/bin/glance' "$BIN_DIR/glance"; then
  rm -f "$BIN_DIR/glance"
fi
echo "runtime removed"
echo "kept secrets/config for recovery: $CONFIG_DIR"
echo "restore the desired ~/.codex/config.toml.bak-* and catalog backup before restarting Codex"
