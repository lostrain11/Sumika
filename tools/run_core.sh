#!/usr/bin/env bash
set -euo pipefail

# Legacy Windows Git Bash compatibility wrapper. The native macOS/Linux
# launcher is reserved but not implemented yet; use the documented Python
# command on those platforms.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) ;;
  *) printf 'This compatibility wrapper only supports Windows Git Bash. Use the documented Python core command on macOS/Linux.\n' >&2; exit 2 ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
args=()
for arg in "$@"; do
  case "$arg" in
    --port=*) args+=('-Port' "${arg#--port=}") ;;
    --data-dir=*) args+=('-DataDir' "${arg#--data-dir=}") ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$repo_root/tools/run_core.ps1" "${args[@]}"
