#!/usr/bin/env bash
#
# Convenience launcher for running straight from a checkout: ./xyzide.sh
# Packaged installs go through the nix wrapper, which sets XYZ_SHARE itself.

XYZ_SHARE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export XYZ_SHARE

# $EDITOR is often unset, so fall back to whichever editor is actually present.
# scripts/editors/ has a profile for each of these names; note that helix is
# `hx` upstream and in nixpkgs but `helix` on Arch.
if [ -z "${XYZ_EDITOR:-}" ] && [ -z "${EDITOR:-}" ]; then
  for candidate in hx helix nvim vim; do
    if command -v "$candidate" >/dev/null 2>&1; then
      XYZ_EDITOR="$candidate"
      break
    fi
  done
  export XYZ_EDITOR
fi

exec bash "$XYZ_SHARE/scripts/xyzide.sh" "$@"
