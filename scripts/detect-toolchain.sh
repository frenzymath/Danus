#!/usr/bin/env bash
# Sourced by bootstrap. Prefer working host tools over this deployment's tools.
# DANUS_ROOT and RT must already be set. Print absolute paths for runtime.env.
danus_find_host_tool() {
  local name="$1" dir candidate
  local -a dirs
  IFS=: read -r -a dirs <<< "$PATH"
  for dir in "${dirs[@]}"; do
    dir="$(cd "${dir:-.}" 2>/dev/null && pwd -P)" || continue
    case "$dir/" in "$RT/"*|"$DANUS_ROOT/bin/") continue ;; esac
    candidate="$dir/$name"
    [ -x "$candidate" ] && [ ! -d "$candidate" ] || continue
    # Also exclude aliases/symlinks to our wrapper, to avoid recursive launches.
    [ "$name" != codex ] || [ ! "$candidate" -ef "$DANUS_ROOT/bin/codex" ] || continue
    if [ "$name" = node ]; then
      "$candidate" -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 16 ? 0 : 1)' >/dev/null 2>&1 || continue
    else
      "$candidate" --version >/dev/null 2>&1 || continue
    fi
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}
