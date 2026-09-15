#!/usr/bin/env bash

STATE_DIR="${XDG_RUNTIME_DIR:-/tmp}"

panes="$(zellij action list-panes --json)"
focused="$(jq -c '[.[] | select(.is_focused == true)][0]' <<<"$panes")"

focused_tab="$(jq -r '.tab_id' <<<"$focused")"
focused_title="$(jq -r '.title' <<<"$focused")"
focused_id="$(jq -r '.id' <<<"$focused")"
focused_is_plugin="$(jq -r '.is_plugin' <<<"$focused")"

state_file="$STATE_DIR/xyzide-yazi-toggle-${ZELLIJ_SESSION_NAME}-tab${focused_tab}"

pane_ref() {
  if [ "$1" = "true" ]; then echo "plugin_$2"; else echo "terminal_$2"; fi
}

if [ "$focused_title" = "Explorer" ]; then
  if [ -f "$state_file" ]; then
    zellij action focus-pane-id "$(cat "$state_file")"
    rm -f "$state_file"
  fi
else
  explorer_id="$(jq -r --argjson tab "$focused_tab" \
    '[.[] | select(.is_plugin == false and .title == "Explorer" and .tab_id == $tab)][0].id' <<<"$panes")"
  if [ -n "$explorer_id" ] && [ "$explorer_id" != "null" ]; then
    pane_ref "$focused_is_plugin" "$focused_id" >"$state_file"
    zellij action focus-pane-id "terminal_$explorer_id"
  fi
fi
