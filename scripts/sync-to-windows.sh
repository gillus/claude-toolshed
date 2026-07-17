#!/usr/bin/env bash
#
# Sync this WSL repo to the native-Windows copy that Claude Desktop runs.
# Modeled on trading_assistant/scripts/sync-to-windows.sh.
#
# WSL stays the source of truth / git repo. Per server:
#   - meal-planner: source is synced, then `uv sync` runs on Windows to refresh
#     the Windows-native venv (which is excluded from the sync).
#   - schoolwork-tracker: built in WSL (`npm run build`) before syncing; dist/
#     and node_modules/ are synced as-is. All runtime deps are pure JS, and the
#     setup scripts use unix-isms that don't run under cmd.exe, so no Windows
#     build step. Requires Node on Windows.
#
# .env files ARE synced (Windows needs the credentials). Per-machine state
# (.argo-data/ sessions, Windows .venv) is excluded and survives syncs.
#
# Usage:
#   scripts/sync-to-windows.sh            # build, sync, uv sync on Windows
#   scripts/sync-to-windows.sh --no-deps  # skip WSL build + Windows uv sync
#   scripts/sync-to-windows.sh --dry-run  # show what would change, do nothing
#
# Override paths via env: WIN_DST (WSL view of the Windows copy), WIN_UV (uv.exe).

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/"
WIN_DST="${WIN_DST:-/mnt/c/Users/gillu/claude-toolshed}"
WIN_UV="${WIN_UV:-C:\\Users\\gillu\\.local\\bin\\uv.exe}"
WIN_DST_DOS="${WIN_DST_DOS:-C:\\Users\\gillu\\claude-toolshed}"

run_deps=1
rsync_extra=()
for arg in "$@"; do
  case "$arg" in
    --no-deps) run_deps=0 ;;
    --dry-run) rsync_extra+=("--dry-run" "--verbose"); run_deps=0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if ! command -v rsync >/dev/null 2>&1; then
  echo "error: rsync not found in WSL" >&2; exit 1
fi

if [[ "$run_deps" -eq 1 ]]; then
  echo ">> building schoolwork-tracker (WSL)"
  (cd "$SRC/schoolwork-tracker" && npm run build)
fi

mkdir -p "$WIN_DST"

echo ">> syncing $SRC -> $WIN_DST"
# --delete keeps the copy clean. Excluded paths are per-machine state; rsync
# does not delete excluded paths on the receiver, so Windows keeps its own.
rsync -a --delete \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='.argo-data/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='.ruff_cache/' \
  "${rsync_extra[@]}" \
  "$SRC" "$WIN_DST/"

if [[ "$run_deps" -eq 1 ]]; then
  echo ">> refreshing Windows meal-planner venv (uv sync)"
  cmd.exe /c "cd /d $WIN_DST_DOS\\meal-planner && $WIN_UV sync" 2>&1 | tr -d '\r' \
    | grep -v -E 'wsl.localhost|UNC paths are not supported|CMD.EXE was started' || true
fi

echo ">> done. Restart Claude Desktop (quit from the tray) if the servers were running."
