#!/usr/bin/env bash

FILE="$1"
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
zellij action focus-pane-id "terminal_$EXPLORER_PANE"
