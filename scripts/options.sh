#!/usr/bin/env bash

usage() {
  echo "Usage: xyzide [-e|--editor <cmd>] [-l|--layout <path>] [-s|--session <name>]" >&2
}

while [ $# -gt 0 ]; do
  case "$1" in
    -e|--editor)
      [ $# -ge 2 ] || { echo "Error: $1 requires a value." >&2; usage; exit 1; }
      XYZ_EDITOR="$2"
      shift 2
      ;;
    -l|--layout)
      [ $# -ge 2 ] || { echo "Error: $1 requires a value." >&2; usage; exit 1; }
      XYZ_LAYOUT_PATH="$2"
      shift 2
      ;;
    -s|--session)
      [ $# -ge 2 ] || { echo "Error: $1 requires a value." >&2; usage; exit 1; }
      XYZ_SESSION_NAME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done
