#!/usr/bin/env bash

FILE="$1"
ESC_KEY=27
ENTER_KEY=13

if [ -z "$FILE" ]; then
  echo "Usage: yazi-opener <file>" >&2
  exit 1
fi

zellij action move-focus right
# Leave whatever mode/prompt the editor is in before typing the command.
zellij action write "$ESC_KEY"
zellij action write-chars ":open \"$FILE\""
zellij action write "$ENTER_KEY"
zellij action move-focus left
