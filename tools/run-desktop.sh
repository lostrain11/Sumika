#!/usr/bin/env bash
set -euo pipefail

# Legacy Windows Git Bash compatibility wrapper. A native macOS/Linux Tauri
# wrapper is reserved but not implemented yet.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) ;;
  *) printf 'This compatibility wrapper only supports Windows Git Bash. Native macOS/Linux desktop startup is not implemented yet.\n' >&2; exit 2 ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
args=()
for arg in "$@"; do
  case "$arg" in
    --no-build) args+=('-NoBuild') ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$repo_root/tools/run-desktop.ps1" "${args[@]}"
