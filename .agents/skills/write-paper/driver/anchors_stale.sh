#!/usr/bin/env bash
# anchors_stale.sh — is the style-anchor set stale (needs re-distilling)?
#
# The write-paper SKILL preflight (stage 1a) uses this to decide whether to run
# the STYLE_DISTILLER. The distiller ONLY proposes; the operator gates the accept.
#
#   bash anchors_stale.sh <skill_dir>
#
#   rc 0  -> STALE: style/anchors/ is non-empty AND its newest content is newer
#            than style/.distilled_at (or that marker is absent). Run the distiller.
#   rc 1  -> SKIP: anchors/ is empty/absent, or unchanged since the last distill.
#   rc 2  -> usage error.
#
# "Newest content" = the newest mtime among the FILES under anchors/ (dirs and the
# anchors README are ignored). The marker style/.distilled_at is touched by the
# SKILL step after the operator accepts a distill round.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: anchors_stale.sh <skill_dir>" >&2
  exit 2
fi

skill_dir="$1"
anchors_dir="$skill_dir/style/anchors"
marker="$skill_dir/style/.distilled_at"

if [[ ! -d "$anchors_dir" ]]; then
  exit 1  # no anchors dir at all -> nothing to distil
fi

# Newest content mtime among real anchor files (skip the top-level README.md that
# ships with the folder; it is documentation, not an operator anchor).
newest=0
while IFS= read -r -d '' f; do
  base="$(basename "$f")"
  # ignore the shipped anchors/README.md itself
  if [[ "$f" == "$anchors_dir/README.md" ]]; then
    continue
  fi
  m=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo 0)
  if [[ "$m" -gt "$newest" ]]; then
    newest="$m"
  fi
done < <(find "$anchors_dir" -type f -print0)

if [[ "$newest" -eq 0 ]]; then
  exit 1  # anchors/ empty (or only the README) -> skip
fi

if [[ ! -f "$marker" ]]; then
  exit 0  # anchors exist but never distilled -> stale
fi

marker_m=$(stat -c %Y "$marker" 2>/dev/null || stat -f %m "$marker" 2>/dev/null || echo 0)
if [[ "$newest" -gt "$marker_m" ]]; then
  exit 0  # an anchor is newer than the last distill -> stale
fi

exit 1  # unchanged since the last distill -> skip
