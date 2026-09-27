#!/usr/bin/env bash

# usage: opener.sh [--stay] FILE [LINE]

STAY=false
if [ "$1" = "--stay" ]; then
  STAY=true
  shift
fi

FILE="$1"
LINE="$2"
ENTER_KEY=13

COMMAND="${XYZ_EDIT_CMD//%s/$FILE}"

pane_id() {
  zellij action list-panes --json |
    jq -r --arg title "$1" '.[] | select(.is_plugin == false and .is_floating == false and .title == $title) | .id' |
    head -n1
}

EDITOR_PANE="$(pane_id Editor)"
EXPLORER_PANE="$(pane_id Explorer)"

zellij action focus-pane-id "terminal_$EDITOR_PANE"
if [ -n "$XYZ_EDIT_PRE" ]; then
  zellij action write "$XYZ_EDIT_PRE"
fi
zellij action write-chars "$COMMAND"
zellij action write "$ENTER_KEY"
if [ -n "$LINE" ] && [ -n "$XYZ_EDIT_GOTO" ]; then
  zellij action write-chars "${XYZ_EDIT_GOTO//%l/$LINE}"
  zellij action write "$ENTER_KEY"
fi
if [ "$STAY" = false ]; then
  zellij action focus-pane-id "terminal_$EXPLORER_PANE"
fi
