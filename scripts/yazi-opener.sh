#!/usr/bin/env bash

FILE="$1"
ENTER_KEY=13

zellij action move-focus right
zellij action write-chars ":open \"$FILE\""
zellij action write "$ENTER_KEY"
zellij action move-focus left
