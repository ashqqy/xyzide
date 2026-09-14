#!/usr/bin/env bash

if [ -z "${XYZ_SHARE:-}" ]; then
  echo "Error: \$XYZ_SHARE is not set." >&2
  exit 1
fi

XYZ_EDITOR="${XYZ_EDITOR:-$EDITOR}"
if [ -z "$XYZ_EDITOR" ]; then
  echo "Error: \$EDITOR is not set." >&2
  exit 1
fi
export XYZ_EDITOR

editor_profile="$XYZ_SHARE/scripts/editors/$(basename -- "$XYZ_EDITOR").sh"
if [ -z "${XYZ_EDIT_CMD:-}" ]; then
  source "$editor_profile" 2>/dev/null
fi
if [ -z "${XYZ_EDIT_CMD:-}" ]; then
  echo "Error: no editor profile for '$XYZ_EDITOR'; set \$XYZ_EDIT_CMD manually." >&2
  exit 1
fi
export XYZ_EDIT_CMD

export YAZI_CONFIG_HOME="$XYZ_SHARE/configs/yazi"
export XYZ_OPENER="$XYZ_SHARE/scripts/opener.sh"

# Referenced by the arena keybinding in the layout.
export XYZ_ARENA="$XYZ_SHARE/scripts/arena.sh"

export XYZ_LAYOUT_PATH="${XYZ_LAYOUT_PATH:-$XYZ_SHARE/configs/layouts/default.kdl}"

export XYZ_SESSION_NAME="${XYZ_SESSION_NAME:-xyzide-$(pwd -P | cksum | cut -d' ' -f1)}"
