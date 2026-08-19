"""Offline tests for danus.dsh — settings rewrite, block-scoped reads, YAML quoting.

Runs standalone (``python -m danus.tests.test_dsh``) and under pytest.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from danus.dsh import (
    read_agent_default_model,
    rewrite_agent_default_model,
    write_headless_gateway_patch,
    yaml_single_quoted,
)

_BLOCK = (
    "theme: dark\n"
    "provider: decoy-provider\n"
    "model: decoy-model\n"
    "agent-default-model:\n"
    "  provider: deepseek-official\n"
    "  model: deepseek-v4-pro\n"
    "  reasoningEffort: max\n"
    "other:\n"
    "  model: another-decoy\n"
)


def test_read_agent_default_ignores_decoy_keys():
    provider, model = read_agent_default_model(_BLOCK)
    assert provider == "deepseek-official"
    assert model == "deepseek-v4-pro"


def test_read_agent_default_missing_block():
    assert read_agent_default_model("theme: dark\nmodel: decoy\n") == (None, None)


def test_rewrite_replaces_only_the_agent_default_block():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "settings.yaml"
        path.write_text(_BLOCK, encoding="utf-8")
        rewrite_agent_default_model(path, "deepseek-official", "deepseek-v4-flash", "high")
        text = path.read_text(encoding="utf-8")
        assert "model: deepseek-v4-flash" in text
        assert "reasoningEffort: high" in text
        assert "provider: decoy-provider" in text  # untouched decoy
        assert "model: decoy-model" in text
        assert "model: another-decoy" in text
        assert text.count("agent-default-model:") == 1


def test_rewrite_omits_effort_when_empty_and_creates_block_when_absent():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "settings.yaml"
        rewrite_agent_default_model(path, "p", "m", "")
        text = path.read_text(encoding="utf-8")
        assert "agent-default-model:" in text
        assert "provider: p" in text and "model: m" in text
        assert "reasoningEffort" not in text


def test_yaml_single_quoted_escapes_apostrophe():
    assert yaml_single_quoted("w1") == "'w1'"
    assert yaml_single_quoted("o'reilly") == "'o''reilly'"
    try:
        yaml_single_quoted("a\nb")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_write_headless_gateway_patch_quotes_author_with_apostrophe():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "cordis.patch.yml"
        write_headless_gateway_patch(
            path,
            role="worker",
            author="o'reilly",
            project_dir="/tmp/proj",
            fail_on_startup=True,
            danus_root="/tmp/Danus",
            verify_url="http://127.0.0.1:8091/verify",
        )
        text = path.read_text(encoding="utf-8")
        assert "DANUS_AUTHOR: 'o''reilly'" in text
        assert "DANUS_ROLE: 'worker'" in text
        assert "failOnStartupError: true" in text
        assert "command: '/tmp/Danus/bin/danus-mcp'" in text


def main() -> None:
    tests = [
        test_read_agent_default_ignores_decoy_keys,
        test_read_agent_default_missing_block,
        test_rewrite_replaces_only_the_agent_default_block,
        test_rewrite_omits_effort_when_empty_and_creates_block_when_absent,
        test_yaml_single_quoted_escapes_apostrophe,
        test_write_headless_gateway_patch_quotes_author_with_apostrophe,
    ]
    for t in tests:
        t()
        print(f"  [ok] {t.__name__}")
    print("ALL DSH HELPER TESTS PASSED")


if __name__ == "__main__":
    main()
