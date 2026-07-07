"""danus.authoring — shared primitives for the artifact renderers.

Both ``danus.write_paper`` (the publication LaTeX paper) and
``danus.human_summary`` (the reader-facing progress report) are peer renderers:
each drives a **one-shot isolated codex** over a fully-embedded, scrubbed prompt
and returns small, honest results (paths + status + flags, never the artifact
body). This module owns the machinery they share:

- ``driver`` — the one-shot isolated codex driver (empty cwd + read-only sandbox +
  prompt on stdin; codex stdout is the artifact). Reads neutral ``DANUS_CODEX_*``
  env for its defaults; each renderer's server layers its own per-service override
  on top.
- ``common`` — the shared pure primitives: project resolution + path-escape
  validation, prompt section wrapping, verbatim fixed/project file reads, the
  frontmatter-stripping body scrub, the honesty outcome classifier, and a generic
  leak scanner (patterns supplied by the caller).

Neither module touches the network or writes files; everything here is testable
in isolation.
"""

from __future__ import annotations
