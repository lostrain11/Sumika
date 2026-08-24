#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
args=()
for arg in "$@"; do
  case "$arg" in
    --no-build) args+=('-NoBuild') ;;
    --skip-model) args+=('-SkipModel') ;;
    --model=*) args+=('-Model' "${arg#--model=}") ;;
    --ollama-models-dir=*) args+=('-OllamaModelsDir' "${arg#--ollama-models-dir=}") ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$repo_root/tools/run-desktop.ps1" "${args[@]}"
