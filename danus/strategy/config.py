"""Strategy-layer config — read from the environment at CALL time (never import
time) so the gateway is testable and reconfigurable, mirroring danus.core /
danus.gateway.

The consult gateway talks to any OpenAI-compatible Responses endpoint. The
endpoint/model/pricing are all env driven via the ``DANUS_CONSULT_*`` names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Default OpenAI-compatible model id (large-reasoning "pro" tier).
DEFAULT_MODEL = "gpt-5.5-pro"
# Default model for the claude_code (subscription) transport. Kept
# separate from DEFAULT_MODEL so opting into claude never picks up the gpt default.
DEFAULT_CLAUDE_CODE_MODEL = "claude-fable-5"
# Default per-1M-token USD pricing. Override via env to match your own contract —
# no magic constants baked into the transport.
DEFAULT_PRICE_IN = 31.5
DEFAULT_PRICE_OUT = 189.0
# Default per-1M-token USD pricing for the default claude model (claude-fable-5):
# Anthropic list price is $10 input / $50 output (2026-06). Override via
# DANUS_CONSULT_CLAUDE_CODE_PRICE_IN / _OUT if you run a different claude model or plan.
DEFAULT_CLAUDE_CODE_PRICE_IN = 10.0
DEFAULT_CLAUDE_CODE_PRICE_OUT = 50.0
# Native Anthropic-API transport (`--transport claude_api`): same default model and
# list price as the claude transport (both consult Claude; this one bills per-token
# to YOUR Anthropic API key instead of drawing on a subscription login).
DEFAULT_CLAUDE_API_MODEL = DEFAULT_CLAUDE_CODE_MODEL
DEFAULT_CLAUDE_API_PRICE_IN = DEFAULT_CLAUDE_CODE_PRICE_IN
DEFAULT_CLAUDE_API_PRICE_OUT = DEFAULT_CLAUDE_CODE_PRICE_OUT
# Default refusal-fallback model (claude-fable-5's safety classifiers can decline a
# request; the API then re-serves it on this model in the same call). "off"/"none"
# disables the fallback parameter entirely.
DEFAULT_CLAUDE_API_FALLBACK = "claude-opus-4-8"


def _first(*names: str, default: str | None = None) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


@dataclass(frozen=True)
class ConsultConfig:
    """A snapshot of the consult endpoint config, resolved from the env."""

    api_key: str | None
    base_url: str | None
    model: str
    price_in: float
    price_out: float
    timeout: float

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


def load_config() -> ConsultConfig:
    """Resolve the consult config from the environment (call time), reading the
    ``DANUS_CONSULT_*`` names.
    """

    def _float(*names: str, default: float) -> float:
        raw = _first(*names)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    return ConsultConfig(
        api_key=_first("DANUS_CONSULT_API_KEY"),
        base_url=_first("DANUS_CONSULT_BASE_URL"),
        model=_first("DANUS_CONSULT_MODEL", default=DEFAULT_MODEL),
        price_in=_float("DANUS_CONSULT_PRICE_IN", default=DEFAULT_PRICE_IN),
        price_out=_float("DANUS_CONSULT_PRICE_OUT", default=DEFAULT_PRICE_OUT),
        timeout=_float("DANUS_CONSULT_TIMEOUT", default=7200.0),
    )


def resolve_transport(cli_value: str | None) -> str:
    """Pick the transport: explicit CLI flag > ``DANUS_CONSULT_TRANSPORT`` env
    > ``gpt_pro`` (the OSS default / core direction-guidance path).

    Recognized transports: ``gpt_pro`` (paid OpenAI-compatible), ``claude_api``
    (paid Anthropic API, native SDK), ``claude_code`` (the Claude Code CLI via
    ``claude -p``, subscription auth), and ``off``. Any other value resolves to
    the ``gpt_pro`` default.
    """
    val = (cli_value or os.environ.get("DANUS_CONSULT_TRANSPORT") or "gpt_pro").strip().lower()
    return val if val in ("off", "gpt_pro", "claude_api", "claude_code") else "gpt_pro"


@dataclass(frozen=True)
class ClaudeCodeConfig:
    """A snapshot of the claude_code (subscription) consult knobs, resolved from the env."""

    model: str
    claude_bin: str
    max_wall: float
    price_in: float
    price_out: float


def load_claude_code_config() -> ClaudeCodeConfig:
    """Resolve the ``--transport claude_code`` knobs from the environment (call time).

    Independent of the gpt_pro-path ``DANUS_CONSULT_MODEL`` (which defaults to the gpt
    tier), so opting into claude does not require touching the gpt_pro config. The
    model can still be overridden per-call by the ``--model`` CLI flag.
    """

    def _float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    return ClaudeCodeConfig(
        model=_first("DANUS_CONSULT_CLAUDE_CODE_MODEL", default=DEFAULT_CLAUDE_CODE_MODEL),
        claude_bin=_first("DANUS_CONSULT_CLAUDE_CODE_BIN", default="claude"),
        max_wall=_float("DANUS_CONSULT_CLAUDE_CODE_MAX_WALL", 1800.0),
        price_in=_float("DANUS_CONSULT_CLAUDE_CODE_PRICE_IN", DEFAULT_CLAUDE_CODE_PRICE_IN),
        price_out=_float("DANUS_CONSULT_CLAUDE_CODE_PRICE_OUT", DEFAULT_CLAUDE_CODE_PRICE_OUT),
    )


@dataclass(frozen=True)
class ClaudeApiConfig:
    """A snapshot of the native Anthropic-API consult knobs, resolved from the env."""

    api_key: str | None
    base_url: str | None
    model: str
    fallback_model: str | None
    price_in: float
    price_out: float
    timeout: float

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


def load_claude_api_config() -> ClaudeApiConfig:
    """Resolve the ``--transport claude_api`` knobs from the environment (call time).

    Independent of the gpt_pro-path ``DANUS_CONSULT_*`` credentials and of the
    claude_code knobs, so opting into the Anthropic API touches neither.
    The key falls back to a plain ``ANTHROPIC_API_KEY`` for convenience — but note
    the ``claude_code`` transport deliberately scrubs that variable from ITS child env
    (a subscription consult must never silently turn into per-token billing);
    here per-token billing is exactly what was asked for.
    """

    def _float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    fallback = _first("DANUS_CONSULT_CLAUDE_API_FALLBACK",
                      default=DEFAULT_CLAUDE_API_FALLBACK)
    if fallback and fallback.strip().lower() in ("off", "none", "disabled"):
        fallback = None
    return ClaudeApiConfig(
        api_key=_first("DANUS_CONSULT_CLAUDE_API_KEY", "ANTHROPIC_API_KEY"),
        base_url=_first("DANUS_CONSULT_CLAUDE_API_BASE_URL"),
        model=_first("DANUS_CONSULT_CLAUDE_API_MODEL", default=DEFAULT_CLAUDE_API_MODEL),
        fallback_model=fallback,
        price_in=_float("DANUS_CONSULT_CLAUDE_API_PRICE_IN", DEFAULT_CLAUDE_API_PRICE_IN),
        price_out=_float("DANUS_CONSULT_CLAUDE_API_PRICE_OUT", DEFAULT_CLAUDE_API_PRICE_OUT),
        timeout=_float("DANUS_CONSULT_TIMEOUT", 7200.0),
    )
