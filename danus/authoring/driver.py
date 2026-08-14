"""One-shot isolated codex driver for the main-only artifact renderers.

Both ``danus.write_paper`` and ``danus.human_summary`` delegate the heavy
generation (the full ``.tex`` / the report / the auditor report) to a local codex
at maximum (``max``) reasoning, via the same codex-exec machinery the proving
workers and the verify service use (all at the neutral ``max`` default). The prompt is large (it embeds the style guide / writer prompt plus
the fact-graph content), so it goes on **stdin**, not argv — argv can't reliably
hold it. codex's **stdout is the artifact**: the model emits the document, the
driver captures it.

Isolation by construction: codex runs with ``cwd`` = a fresh empty
``tempfile.TemporaryDirectory()`` so it has nothing local to read. The prompt
(assembled by each renderer's ``assemble.py``) already embeds everything the role
needs — including ``AGENTS.md`` — so codex relies only on the embedded prompt, not
on files it might discover on disk. The operator has explicitly selected Codex
full-permission mode for every workflow. Isolation therefore comes from the fresh
empty cwd and fully embedded prompt, not from a filesystem sandbox.

Two exec tails share this one driver (see ``run_codex``):

- the **offline default** (writer / auditor / reviser) — full-permission Codex,
  no MCP, no web; the empty cwd + embedded prompt are the whole world;
- the **networked variant** (the reference verifier) — mirrors
  ``danus.verify.launcher``: ``--dangerously-bypass-approvals-and-sandbox`` with
  the danus gateway injected via ``-c`` at ``DANUS_ROLE=verifier`` (the read-only
  ``search_arxiv_theorems`` role — no new gateway role) plus codex's built-in
  ``web_search``. The empty cwd is kept, so codex still cannot read/write the
  project tree; its only outward reach is the gateway's read-only tool + web.


Config (env, read at CALL time — never import time; resolved via the shared
``danus.codex`` launcher):
  DANUS_CODEX_BIN     codex binary (alias: CODEX_BIN; default: the deployment's
                      bin/codex wrapper, else "codex" on PATH)
  DANUS_CODEX_MODEL   neutral default model (default "gpt-5.6-sol"); each renderer's
                      server layers its own per-service override on top
  DANUS_CODEX_EFFORT  neutral default reasoning effort (default "max")
  timeout             default 7200s (0 = no timeout)
"""

from __future__ import annotations

import subprocess
import tempfile

from danus import codex

DEFAULT_MODEL = codex.DEFAULT_MODEL
DEFAULT_EFFORT = codex.DEFAULT_EFFORT
DEFAULT_TIMEOUT = 7200


def _gateway_config_arg(gateway_role: str) -> str:
    """The ``-c`` MCP-injection string that mounts the danus gateway into codex,
    mirroring ``danus.verify.launcher._mcp_config_arg`` exactly: it runs the
    installed package (``python3 -m danus.gateway``) with the given ``DANUS_ROLE``,
    independent of CODEX_HOME. Reuse ``DANUS_ROLE=verifier`` for minimum privilege —
    that gateway role exposes ONLY ``search_arxiv_theorems`` (read-only). We do NOT
    define a new gateway role for the paper verifier."""
    return (
        'mcp_servers.danus={command="python3",args=["-m","danus.gateway"],'
        f'env={{DANUS_ROLE="{gateway_role}"}}}}'
    )


def default_model() -> str:
    """The neutral default codex model (``DANUS_CODEX_MODEL``). Each renderer's
    server resolves its own per-service override first and falls back to this."""
    return codex.model()


def default_effort() -> str:
    """The neutral default reasoning effort (``DANUS_CODEX_EFFORT``). Each
    renderer's server layers its own per-service override on top."""
    return codex.effort()


def run_codex(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    timeout: int = DEFAULT_TIMEOUT,
    networked: bool = False,
    gateway_role: str = "verifier",
) -> subprocess.CompletedProcess:
    """Drive codex ``exec`` once: prompt on stdin, artifact on stdout.

    Runs with ``cwd`` = a fresh empty temp dir (isolation). Returns the
    ``CompletedProcess`` verbatim (stdout/stderr/returncode); the caller decides
    honesty (a nonzero returncode / empty stdout / timeout is NOT success). Raises
    ``subprocess.TimeoutExpired`` on timeout and ``FileNotFoundError`` if the codex
    binary is absent — the server translates both into an honest non-``ok`` status.

    Two mutually-exclusive tails, chosen by ``networked``:

    - **Offline (default, ``networked=False``)** — full-permission Codex with
      ``--skip-git-repo-check``, no MCP, and no web. Codex has an empty cwd and a
      fully embedded prompt, so it has no project files to discover. This is what
      the writer / auditor / reviser use.

    - **Networked (``networked=True``)** — the reference-verifier path, mirroring
      ``danus.verify.launcher.build_codex_command``: keep the same full-permission
      flag, inject the
      danus gateway via ``-c`` at ``DANUS_ROLE=<gateway_role>`` (default
      ``verifier`` — exposes ONLY ``search_arxiv_theorems``, minimum privilege; no
      new gateway role is created), and enable codex's built-in ``web_search``
      tool. The empty cwd is kept, so the only writes/reads are through the
      gateway's read-only tool + web search — codex still cannot touch the project
      tree; the caller (``server.reference_verify``) is the sole writer of the ledger.
    """
    codex_bin = codex.resolve_bin()
    if networked:
        tail = (
            "-c", _gateway_config_arg(gateway_role),
            "--config", "tools.web_search=true",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "-",  # read the prompt from stdin
        )
    else:
        tail = (
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "-",  # read the prompt from stdin
        )
    cmd = codex.exec_cmd(codex_bin, model, effort, *tail)
    with tempfile.TemporaryDirectory(prefix="danus-authoring-codex-") as empty_cwd:
        return subprocess.run(
            cmd,
            input=prompt,
            cwd=empty_cwd,
            env=codex.subprocess_env(codex_bin),
            capture_output=True,
            text=True,
            timeout=timeout if timeout and timeout > 0 else None,
        )
