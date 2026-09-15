#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/options.sh"
source "$SCRIPT_DIR/env.sh"

for program in "$XYZ_EDITOR" yazi zellij jq; do
  if ! command -v "$program" &>/dev/null; then
    echo "Error: $program is not found in system PATH. Please install it." >&2
    exit 1
  fi
done

if [ ! -f "$XYZ_LAYOUT_PATH" ]; then
  echo "Error: layout file not found: $XYZ_LAYOUT_PATH" >&2
  exit 1
fi

if ! zellij --config "$XYZ_SHARE/configs/zellij/config.kdl" attach --force-run-commands "$XYZ_SESSION_NAME" 2>/dev/null; then
  zellij --config "$XYZ_SHARE/configs/zellij/config.kdl" --session "$XYZ_SESSION_NAME" --new-session-with-layout "$XYZ_LAYOUT_PATH"
fi
