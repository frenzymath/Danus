"""consult CLI — the stateless strategic-consult gateway.

Reads an elaboration (``--file`` / ``--stdin``), sends it to a strong model via
the chosen transport, and prints the pinned JSON envelope on stdout. The caller
records ``reply`` verbatim as ``master_guidance`` and dispatches workers from it.

Entry point: ``python -m danus.strategy`` (bin/consult wraps this). Exit 0 on
success; non-zero on empty prompt / missing key / ``off``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

from .config import (
    load_claude_api_config, load_claude_code_config, load_config, resolve_transport,
)
from .ledger import log_spend
from .transport import (
    ClaudeApiTransport, ClaudeCodeTransport, GptProTransport, OffTransport,
)


def _claude_available(binary: str) -> bool:
    """True if the ``claude`` CLI is invokable (on PATH, or an executable path)."""
    if shutil.which(binary):
        return True
    return os.path.isfile(binary) and os.access(binary, os.X_OK)


def _write_out(path: str, res: Dict[str, Any]) -> None:
    """Human-readable markdown dump (reasoning summary + reply)."""
    usage = res.get("usage") or {}
    md = (
        f"# consult ({res.get('model')}, effort={res.get('effort')}, "
        f"transport={res.get('transport')}, {res.get('status')})\n\n"
        f"- time: {res.get('seconds')}s · tools: {res.get('tool_calls') or 'none'}\n"
        f"- tokens: in {usage.get('input')} / out {usage.get('output')} "
        f"(reasoning {usage.get('reasoning')}) · **cost ${res.get('cost_usd')}**\n\n"
        f"## reasoning summary\n\n{res.get('reasoning_summary') or '_(none)_'}\n\n"
        f"## reply (record this as master_guidance)\n\n{res.get('reply', '')}\n"
    )
    Path(path).write_text(md, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="consult",
        description="Consult a strong model (default gpt-5.5-pro) via an "
        "OpenAI-compatible Responses API; emit reply+cost as one JSON line.",
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="read the elaboration / prompt from this file")
    src.add_argument("--stdin", action="store_true", help="read the prompt from stdin")
    ap.add_argument("--effort", choices=["minimal", "low", "medium", "high", "xhigh"],
                    default="high", help="reasoning effort (default high; xhigh = strongest)")
    ap.add_argument("--tools", choices=["auto", "web", "none"], default="auto",
                    help="tool set for the richest attempts (auto = web_search + code_interpreter)")
    ap.add_argument("--project", help="project dir — append a spend record to "
                    "<project>/spend/consult.jsonl and report project_total_usd")
    ap.add_argument("--out", help="also write the full reply+summary as markdown here")
    ap.add_argument("--max-output-tokens", type=int, default=100000)
    ap.add_argument("--model", default=None,
                    help="override the consult model (api: any OpenAI-compatible id; "
                    "claude_api/claude_code: any Claude model, e.g. claude-fable-5 / claude-opus-4-8)")
    ap.add_argument("--transport", choices=["gpt_pro", "claude_api", "claude_code", "off"], default=None,
                    help="gpt_pro (the default, paid OpenAI-compatible), claude_api "
                    "(paid Anthropic API, BYO key), claude_code (your Claude "
                    "subscription via the Claude Code CLI), or off (no-op short-circuit); "
                    "falls back to $DANUS_CONSULT_TRANSPORT then gpt_pro")
    ap.add_argument("--quiet", action="store_true", help="suppress the stderr heartbeat")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)

    prompt = sys.stdin.read() if args.stdin else Path(args.file).read_text(encoding="utf-8")
    if not prompt.strip():
        print("refusing to consult on an empty prompt", file=sys.stderr, flush=True)
        return 2

    transport_name = resolve_transport(args.transport)

    if transport_name == "off":
        res = OffTransport().consult(
            prompt, effort=args.effort, tools=args.tools,
            max_output_tokens=args.max_output_tokens,
        )
        if args.project:
            res["project_total_usd"] = log_spend(args.project, res)  # records the $0 event
        if args.out:
            _write_out(args.out, res)
        print(json.dumps(res, ensure_ascii=False))
        print("[consult] transport=off (disabled); returning empty reply", file=sys.stderr, flush=True)
        return 1

    if transport_name == "claude_code":
        # Claude Code CLI via `claude -p` (subscription auth). On failure we do NOT fall
        # back to the paid gpt_pro — the caller (main agent) reasons on its own.
        cfg = load_claude_code_config()
        model = args.model or cfg.model
        if not _claude_available(cfg.claude_bin):
            print(f"claude CLI not found at '{cfg.claude_bin}' (set DANUS_CONSULT_CLAUDE_CODE_BIN, "
                  "or use --transport off)", file=sys.stderr, flush=True)
            return 3
        res = ClaudeCodeTransport(model, claude_bin=cfg.claude_bin, max_wall=cfg.max_wall,
                              price_in=cfg.price_in, price_out=cfg.price_out).consult(
            prompt, effort=args.effort, tools=args.tools,
            max_output_tokens=args.max_output_tokens,
        )
        if res.get("status") != "completed":
            print(f"[consult] WARNING status={res.get('status')} (claude_code transport did not "
                  "complete; main agent should reason on its own)", file=sys.stderr, flush=True)
        if args.project:
            res["project_total_usd"] = log_spend(args.project, res)  # records the consult event with its metered cost_usd
        if args.out:
            _write_out(args.out, res)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("status") == "completed" else 1

    if transport_name == "claude_api":
        # Native Anthropic API (per-token, BYO key). On failure we do NOT fall
        # back to gpt_pro — the caller (main agent) reasons on its own.
        acfg = load_claude_api_config()
        if args.model:
            acfg = replace(acfg, model=args.model)
        if not acfg.has_key:
            print("Anthropic consult key not set (set DANUS_CONSULT_CLAUDE_API_KEY "
                  "or ANTHROPIC_API_KEY, or use --transport off)",
                  file=sys.stderr, flush=True)
            return 3

        def _ahb(elapsed: float, status: Optional[str], n: int) -> None:
            print(f"[consult {elapsed:.0f}s status={status} events={n}]",
                  file=sys.stderr, flush=True)

        res = ClaudeApiTransport(acfg).consult(
            prompt, effort=args.effort, tools=args.tools,
            max_output_tokens=args.max_output_tokens,
            on_progress=None if args.quiet else _ahb,
        )
        if res.get("status") != "completed":
            print(f"[consult] WARNING status={res.get('status')} (claude_api transport "
                  "did not complete; main agent should reason on its own)",
                  file=sys.stderr, flush=True)
        if args.project:
            res["project_total_usd"] = log_spend(args.project, res)  # real usage × per-1M rate
        if args.out:
            _write_out(args.out, res)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("status") == "completed" else 1

    config = load_config()
    if args.model:
        config = replace(config, model=args.model)
    if not config.has_key:
        print("consult API key not set (set DANUS_CONSULT_API_KEY, "
              "or use --transport off)", file=sys.stderr, flush=True)
        return 3

    def _hb(elapsed: float, status: Optional[str], n: int) -> None:
        print(f"[consult {elapsed:.0f}s status={status} events={n}]", file=sys.stderr, flush=True)

    res = GptProTransport(config).consult(
        prompt, effort=args.effort, tools=args.tools,
        max_output_tokens=args.max_output_tokens,
        on_progress=None if args.quiet else _hb,
    )
    if res.get("status") and res["status"] != "completed":
        print(f"[consult] WARNING status={res['status']} (not completed)", file=sys.stderr, flush=True)
    if args.project:
        res["project_total_usd"] = log_spend(args.project, res)
    if args.out:
        _write_out(args.out, res)
    print(json.dumps(res, ensure_ascii=False))
    return 0
