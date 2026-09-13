#!/usr/bin/env bash

# Helix is called `hx` upstream and in nixpkgs, but Arch ships it as `helix`.
# Both are accepted; set XYZ_EDITOR yourself to use a different editor.
if [ -z "$XYZ_EDITOR" ]; then
  for candidate in hx helix; do
    if command -v "$candidate" &>/dev/null; then
      XYZ_EDITOR="$candidate"
      break
    fi
  done
fi
export XYZ_EDITOR="${XYZ_EDITOR:-hx}"
export XYZ_FILEMANAGER="${XYZ_FILEMANAGER:-yazi}"

for program in "$XYZ_EDITOR" "$XYZ_FILEMANAGER" zellij; do
  if ! command -v "$program" &>/dev/null; then
    echo "Error: $program is not found in system PATH. Please install it." >&2
    if [ "$program" = "hx" ]; then
      echo "Hint: on Arch the package is 'helix' (sudo pacman -S helix)." >&2
    fi
    exit 1
  fi
done

SESSION_NAME="xyzide-session"

# XYZIDE_SHARE is injected by the nix wrapper; fall back to the repo checkout
# so the script also works when run straight from ./scripts.
if [ -z "$XYZIDE_SHARE" ]; then
  XYZIDE_SHARE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
fi
LAYOUT="${LAYOUT_PATH:-$XYZIDE_SHARE/configs/layouts/default.kdl}"

# Referenced by configs/yazi/yazi.toml to open files in the editor pane.
if [ -z "$XYZIDE_OPENER" ] && [ -x "$XYZIDE_SHARE/scripts/yazi-opener.sh" ]; then
  export XYZIDE_OPENER="$XYZIDE_SHARE/scripts/yazi-opener.sh"
fi

# Referenced by the Alt+a binding in the layout.
if [ -z "$XYZIDE_ARENA" ] && [ -x "$XYZIDE_SHARE/scripts/arena.sh" ]; then
  export XYZIDE_ARENA="$XYZIDE_SHARE/scripts/arena.sh"
fi

if [ ! -f "$LAYOUT" ]; then
  echo "Error: layout file not found: $LAYOUT" >&2
  exit 1
fi

# `--layout` together with `--session` means "add this layout as a new tab to
# that session" and fails with "There is no active session!" when the session
# does not exist yet. `--new-session-with-layout` is the flag that actually
# creates a session from a layout.
if ! zellij attach --force-run-commands "$SESSION_NAME" 2>/dev/null; then
  zellij --session "$SESSION_NAME" --new-session-with-layout "$LAYOUT"
fi
