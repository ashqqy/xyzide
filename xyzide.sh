#!/usr/bin/env bash
#
# Launcher for running xyzide straight from a checkout: ./xyzide.sh
# It injects the same environment that the nix wrapper sets up in flake.nix,
# then hands over to the real script in scripts/.

XYZIDE_SHARE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export XYZIDE_SHARE
export YAZI_CONFIG_HOME="$XYZIDE_SHARE/configs/yazi"
export LAYOUT_PATH="$XYZIDE_SHARE/configs/layouts/default.kdl"
export XYZIDE_OPENER="$XYZIDE_SHARE/scripts/yazi-opener.sh"
export XYZIDE_ARENA="$XYZIDE_SHARE/scripts/arena.sh"

exec bash "$XYZIDE_SHARE/scripts/xyzide.sh" "$@"
