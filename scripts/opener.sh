#!/usr/bin/env bash

FILE="$1"
ESC_KEY=27
ENTER_KEY=13

COMMAND="${XYZ_EDIT_CMD//%s/$FILE}"

zellij action move-focus right
zellij action write "$ESC_KEY"
zellij action write-chars "$COMMAND"
zellij action write "$ENTER_KEY"
zellij action move-focus left
