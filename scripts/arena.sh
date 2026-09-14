#!/usr/bin/env bash
#
# Launcher for the 3D arena game. Kept separate from brawl3d.py so a missing
# dependency is reported inside the pane instead of flashing it closed.

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GAME="${XYZ_ARENA_PY:-$HERE/brawl3d.py}"
PY="${XYZ_PYTHON:-python3}"

fail() {
  printf '\n  %s\n\n  Press ENTER to close this pane.\n' "$1" >&2
  read -r _
  exit 1
}

command -v "$PY" >/dev/null 2>&1 || fail "python3 is not in PATH."
"$PY" -c 'import numpy' 2>/dev/null \
  || fail "The arena needs numpy: sudo pacman -S python-numpy (or pip install numpy)."
[ -f "$GAME" ] || fail "Game not found: $GAME"

exec "$PY" "$GAME" "$@"
