# xyzide

A terminal IDE built from three tools glued together with `zellij`:

- **zellij** — the multiplexer; owns the session and the pane layout.
- **yazi** in the left pane.
- your **editor** (`$EDITOR`) in the right pane.

Selecting a file in the file manager makes it open in the editor pane — not
via any editor plugin, but by having zellij literally type an open-file
command into that pane on your behalf. See "How file-opening works" below.
**Helix and vim/nvim work out of the box**; other editors need `XYZ_EDIT_CMD`
set manually (see below).

## Usage

xyzide is a nix package — it isn't meant to be run outside of it (see
[Nix](#nix)):

```sh
nix run .
# or, once installed:
xyzide
```

`$EDITOR` must be set — xyzide has no built-in fallback list of editors to
try.

```sh
export EDITOR=hx     # or nvim, vim, ...
xyzide
```

`-e`/`--editor`, `-l`/`--layout` and `-s`/`--session` override the editor,
the zellij layout file, and the session name for a single run, without
exporting anything:

```sh
xyzide --editor nvim --layout ~/my-layout.kdl --session my-project
```

Running xyzide again from the same project directory reattaches to the same
session; running it from a different directory starts an independent
session, so several projects can each have their own xyzide running at once.

## Architecture

```
scripts/
  options.sh                 parses -e/-l flags into XYZ_EDITOR/XYZ_LAYOUT_PATH
  env.sh                     single source of truth for all XYZ_* env vars
  xyzide.sh                  sources options.sh then env.sh, checks dependencies, starts zellij
  opener.sh                  types an "open file" command into the editor pane
  editors/*.sh               per-editor XYZ_EDIT_CMD, picked by env.sh from $XYZ_EDITOR's binary name
configs/
  layouts/default.kdl        the two-pane zellij layout (Explorer | Editor)
  yazi/yazi.toml             yazi config: wires its opener to opener.sh
  yazi/keymap.toml           yazi keybindings: adds a preview-pane toggle
  yazi/plugins/toggle-pane.yazi  vendored yazi-rs/plugins toggle-pane plugin
flake.nix                    nix package (wraps the checkout + bundles zellij/yazi)
```

`scripts/options.sh` and `scripts/env.sh` are sourced (not executed) by
`scripts/xyzide.sh`, in that order, so a CLI flag lands in the same variable
`env.sh` would otherwise default from an environment variable — one place
that computes every default.

## Environment variables

Everything xyzide itself defines is prefixed `XYZ_`. Variables without that
prefix (`EDITOR`, `YAZI_CONFIG_HOME`) belong to a tool being integrated with,
not to xyzide.

| Variable | Default | Meaning |
|---|---|---|
| `XYZ_SHARE` | *(none — set by the nix package)* | where `configs/` and `scripts/` live; xyzide refuses to start if this isn't set |
| `XYZ_EDITOR` | `$EDITOR` (or `-e`/`--editor`) | the editor binary to launch; **required**, no fallback |
| `XYZ_EDIT_CMD` | picked from `scripts/editors/<binary>.sh`; **required** if there's no profile for your editor | command typed into the editor to open a file; `%s` is replaced with the path |
| `XYZ_LAYOUT_PATH` | `$XYZ_SHARE/configs/layouts/default.kdl` (or `-l`/`--layout`) | zellij layout file |
| `XYZ_OPENER` | `$XYZ_SHARE/scripts/opener.sh` | script yazi calls to open a file in the editor; fixed, not user-overridable |
| `XYZ_SESSION_NAME` | `xyzide-<hash-of-the-directory>` (or `-s`/`--session`) | zellij session name; each directory gets its own by default, so several projects can run at once |

`YAZI_CONFIG_HOME` is also set (to `$XYZ_SHARE/configs/yazi`) but isn't a
xyzide variable — it's yazi's own config-directory variable.

## Keybindings

`configs/yazi/keymap.toml` adds one binding on top of yazi's defaults:
`T` toggles the preview pane (`[mgr] ratio`'s third slot) on and off, via the
vendored `configs/yazi/plugins/toggle-pane.yazi` plugin (from
[yazi-rs/plugins](https://github.com/yazi-rs/plugins), pinned to match the
bundled yazi version rather than fetched at runtime).

## How file-opening works

`configs/yazi/yazi.toml` registers `scripts/opener.sh` as yazi's
opener for every file. That script:

1. focuses the editor pane (to its right, per `configs/layouts/default.kdl`),
2. sends Escape (to leave whatever mode the editor is in),
3. types `XYZ_EDIT_CMD` with the file path substituted for `%s`,
4. presses Enter,
5. focuses back to the yazi pane.

This is why `XYZ_EDIT_CMD` has to match your editor's own command syntax.
The `move-focus right`/`left` pair is hardcoded to match the default
layout's pane order — if you change `configs/layouts/default.kdl` to put the
editor pane somewhere else, update `scripts/opener.sh` to match.

### Editor profiles

`XYZ_EDIT_CMD` isn't set directly — `env.sh` takes the basename of
`$XYZ_EDITOR` and looks for `scripts/editors/<that-name>.sh`. If found, it's
sourced to set `XYZ_EDIT_CMD`. If you've already set `XYZ_EDIT_CMD` yourself,
that wins and no profile is loaded. If neither applies, xyzide refuses to
start — there's no guessed default, so an editor without a profile needs
`XYZ_EDIT_CMD` set by hand.

Shipped profiles: `helix.sh` and `hx.sh` use `:open "%s"`; `vim.sh` and
`nvim.sh` use `:e %s` (one file per binary name, so the lookup stays a plain
filename match). To add another editor, drop a
`scripts/editors/<binary-name>.sh` that exports `XYZ_EDIT_CMD`.

## Nix

`flake.nix` builds a package that bundles `zellij` and `yazi` so the
installed `xyzide` binary works without either already being on `$PATH`. The
editor is deliberately **not** bundled — xyzide always launches whatever
`$EDITOR` points at in your own environment.

Supports `x86_64-linux`, `aarch64-linux`, `x86_64-darwin`, `aarch64-darwin`.
