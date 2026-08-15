#!/usr/bin/env bash
#
# Deploy the ICA custom integration to a Home Assistant OS device over SSH,
# then restart HA Core so the new Python code is picked up.
#
# Prerequisites
#   - An SSH host alias that reaches your HA device. Defaults to "ha", i.e. you
#     can already run `ssh ha`. Override with the HA_SSH env var if different.
#   - An SSH-capable HA add-on ("Terminal & SSH" or "Advanced SSH & Web
#     Terminal") whose session can write to /config and run the `ha` CLI.
#
# Usage
#   scripts/deploy.sh                 # sync the integration + restart HA Core
#   scripts/deploy.sh --no-restart    # sync only (restart HA yourself)
#   HA_SSH=myhost scripts/deploy.sh   # use a different SSH alias/host
#   HA_CONFIG_DIR=/homeassistant scripts/deploy.sh   # non-default config path
#
# Only custom_components/ica/ is deployed — nothing else in the repo.

set -euo pipefail

HA_SSH="${HA_SSH:-ha}"
HA_CONFIG_DIR="${HA_CONFIG_DIR:-/config}"
RESTART=1
[ "${1:-}" = "--no-restart" ] && RESTART=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/../custom_components/ica"
PARENT="$HA_CONFIG_DIR/custom_components"
DEST="$PARENT/ica"

if [ ! -f "$SRC/manifest.json" ]; then
  echo "error: $SRC/manifest.json not found — is this the repo checkout?" >&2
  exit 1
fi

echo "→ Target: $HA_SSH:$DEST"

if ssh "$HA_SSH" 'command -v rsync >/dev/null 2>&1'; then
  echo "→ Syncing with rsync (incremental, prunes removed files)…"
  ssh "$HA_SSH" "mkdir -p '$PARENT'"
  rsync -a --delete --rsync-path="sudo rsync" \
    --exclude '__pycache__/' --exclude '*.pyc' \
    "$SRC/" "$HA_SSH:$DEST/"
else
  echo "→ rsync not on device; using a tar pipe (full replace)…"
  ssh "$HA_SSH" "rm -rf '$DEST' && mkdir -p '$PARENT'"
  tar -C "$SCRIPT_DIR/../custom_components" \
    --exclude '__pycache__' --exclude '*.pyc' \
    -cf - ica \
    | ssh "$HA_SSH" "tar -C '$PARENT' -xf -"
fi
echo "✓ Integration synced."

if [ "$RESTART" -eq 1 ]; then
  echo "→ Restarting Home Assistant Core…"
  if ssh "$HA_SSH" 'ha core restart'; then
    echo "✓ Restart requested — HA should be back in ~30–60s."
  else
    echo "⚠ Could not run 'ha core restart' over SSH." >&2
    echo "  Restart manually: Settings → System → Restart." >&2
  fi
else
  echo "ℹ No restart (--no-restart). Restart HA to load the new code."
fi
