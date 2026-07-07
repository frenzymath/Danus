"""Offline edge-case tests for danus.write_paper.assemble — the headline-selection
error path and the style-anchor block branches. Zero network / codex.

Runs standalone (``python -m danus.write_paper.tests.test_assemble_edge``) and pytest.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from danus.core import FactGraph
from danus.write_paper import assemble

from ._fixtures import temp_project


@contextlib.contextmanager
def _env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_fact_graph_content_valid_headline_walks_predecessors():
    with temp_project() as pdir:
        ids = FactGraph(Path(pdir)).list()
        out = assemble.fact_graph_content(pdir, headline=[ids[0]])
        assert out and "## statement" in out and "## proof" in out


def test_fact_graph_content_unknown_headline_raises():
    with temp_project() as pdir:
        try:
            assemble.fact_graph_content(pdir, headline=["does-not-exist"])
            assert False, "an unknown headline fact id must raise ValueError"
        except ValueError:
            pass


def test_fact_graph_content_duplicate_headline_is_deduped():
    with temp_project() as pdir:
        ids = FactGraph(Path(pdir)).list()
        once = assemble.fact_graph_content(pdir, headline=[ids[0]])
        twice = assemble.fact_graph_content(pdir, headline=[ids[0], ids[0]])
        assert once == twice  # the second occurrence hits the already-seen dedup skip


def test_anchor_block_none_and_missing_dir_return_none():
    with tempfile.TemporaryDirectory() as d, _env(DANUS_WRITE_PAPER_SKILL_DIR=d):
        assert assemble._anchor_block(None) is None
        assert assemble._anchor_block("nonexistent") is None


def test_anchor_block_binary_file_named_not_embedded():
    with tempfile.TemporaryDirectory() as d, _env(DANUS_WRITE_PAPER_SKILL_DIR=d):
        adir = Path(d) / "style" / "anchors" / "paperX"
        adir.mkdir(parents=True)
        (adir / "sub").mkdir()  # a subdirectory: rglob yields it -> the non-file skip
        (adir / "fig.bin").write_bytes(b"\xff\xfe\x00\x01 not-utf-8")
        out = assemble._anchor_block("paperX")
        assert out is not None and "fig.bin (binary; not embedded)" in out


def test_anchor_block_text_file_is_embedded():
    with tempfile.TemporaryDirectory() as d, _env(DANUS_WRITE_PAPER_SKILL_DIR=d):
        adir = Path(d) / "style" / "anchors" / "paperY"
        adir.mkdir(parents=True)
        (adir / "main.tex").write_text("\\documentclass{amsart}\n", encoding="utf-8")
        out = assemble._anchor_block("paperY")
        assert out is not None and "\\documentclass{amsart}" in out


def main() -> None:
    test_fact_graph_content_valid_headline_walks_predecessors()
    print("  [ok] fact_graph_content walks predecessors for a valid headline id")
    test_fact_graph_content_unknown_headline_raises()
    print("  [ok] fact_graph_content raises on an unknown headline id")
    test_fact_graph_content_duplicate_headline_is_deduped()
    print("  [ok] fact_graph_content dedups a repeated headline id")
    test_anchor_block_none_and_missing_dir_return_none()
    print("  [ok] _anchor_block returns None for no-anchor / missing dir")
    test_anchor_block_binary_file_named_not_embedded()
    print("  [ok] _anchor_block names a binary exemplar without embedding it")
    test_anchor_block_text_file_is_embedded()
    print("  [ok] _anchor_block embeds a text exemplar verbatim")
    print("ALL ASSEMBLE-EDGE TESTS PASSED")


if __name__ == "__main__":
    main()
