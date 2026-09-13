#!/usr/bin/env bash

export XYZ_EDITOR="hx"
export XYZ_FILEMANAGER="yazi"

for program in "$XYZ_EDITOR" "$XYZ_FILEMANAGER" zellij; do
  if ! command -v "$program" &>/dev/null; then
    echo "Error: $program is not found in system PATH. Please install it."
    exit 1
  fi
done

SESSION_NAME="xyzide-session"

LAYOUT="${LAYOUT_PATH:-$XYZIDE_SHARE/configs/layouts/default.kdl}"

if ! zellij attach "$SESSION_NAME" 2>/dev/null; then
  zellij --session "$SESSION_NAME" --layout "$LAYOUT"
fi
