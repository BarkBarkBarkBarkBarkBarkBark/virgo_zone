#!/usr/bin/env bash
# Portable installer for VirgoZone (extension, local web app, and virgozone-start CLI).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="${HOSAKA_REPO:-$(cd "$ROOT/../Hosaka" && pwd)}"
GATEWAY="${HOSAKA_GATEWAY_REPO:-$(cd "$ROOT/../hosaka-gateway" && pwd)}"
PREFIX="${HOSAKA_PREFIX:-$HOME/.local}"
DEV=0
LINK=1

while (( $# )); do
  case "$1" in
    --dev) DEV=1 ;;
    --no-link) LINK=0 ;;
    --prefix) PREFIX="$2"; shift ;;
    --core) CORE="$(cd "$2" && pwd)"; shift ;;
    --gateway) GATEWAY="$(cd "$2" && pwd)"; shift ;;
    --help|-h)
      echo "Usage: bash install.sh [--dev] [--no-link] [--prefix PATH] [--core PATH] [--gateway PATH]"
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

PYTHON="${PYTHON:-$CORE/.hosakavenv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$CORE/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

INSTALL_ARGS=(--core "$CORE" --prefix "$PREFIX" --virgozone "$ROOT")
[[ ! -d "$ROOT/../hosaka_citations" ]] || INSTALL_ARGS+=(--citations "$(cd "$ROOT/../hosaka_citations" && pwd)")
(( ! LINK )) || INSTALL_ARGS+=(--link)
(( ! DEV )) || INSTALL_ARGS+=(--dev)
exec "$PYTHON" "$GATEWAY/install.py" "${INSTALL_ARGS[@]}"
