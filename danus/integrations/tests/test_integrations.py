"""Offline tests for danus.integrations.matlas — mocked HTTP, no network.

Covers the normalization contract and the never-raises / graceful-degradation
guarantee (a search outage must not crash a worker/verifier round).
"""

from __future__ import annotations

import io
import json
import urllib.error
from contextlib import contextmanager

from danus.integrations import matlas


@contextmanager
def _mock_urlopen(payload=None, raise_exc=None):
    orig = matlas.urllib.request.urlopen

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        if raise_exc is not None:
            raise raise_exc
        return _Resp(json.dumps(payload).encode("utf-8"))

    matlas.urllib.request.urlopen = fake
    try:
        yield
    finally:
        matlas.urllib.request.urlopen = orig


def test_empty_query_short_circuits():
    out = matlas.search("   ")
    assert out["count"] == 0 and out["results"] == [] and out["error"] == "empty query"


def test_normalization_of_results():
    payload = [
        {"title": "T1", "theorem": "for all n, ...", "arxiv_id": "2601.00001", "theorem_id": "thm1", "extra": "ignored"},
        {"title": "T2", "theorem": "there exists ...", "arxiv_id": "2601.00002", "theorem_id": "lem2"},
        "junk-not-a-dict",
    ]
    with _mock_urlopen(payload=payload):
        out = matlas.search("some statement", num_results=5)
    assert out["count"] == 2  # the non-dict item is dropped
    r = out["results"][0]
    assert set(r) == {"title", "theorem", "arxiv_id", "theorem_id"}  # exactly the 4 fields
    assert r["arxiv_id"] == "2601.00001" and "error" not in out


def test_network_error_never_raises():
    with _mock_urlopen(raise_exc=urllib.error.URLError("boom")):
        out = matlas.search("x")
    assert out["results"] == [] and out["count"] == 0 and out["error"].startswith("network:")


def test_non_list_body_is_error_not_crash():
    with _mock_urlopen(payload={"not": "a list"}):
        out = matlas.search("x")
    assert out["results"] == [] and "error" in out


def test_http_error_yields_error_envelope():
    # matlas.py:70 — an HTTPError (e.g. Cloudflare 403) -> 'http <code>' envelope
    exc = urllib.error.HTTPError(url=matlas._URL, code=403, msg="Forbidden", hdrs=None, fp=None)
    with _mock_urlopen(raise_exc=exc):
        out = matlas.search("x")
    assert out["results"] == [] and out["count"] == 0
    assert out["error"].startswith("http 403")


def test_timeout_yields_error_envelope():
    # matlas.py:73-74 — a socket TimeoutError -> error envelope, never raises
    with _mock_urlopen(raise_exc=TimeoutError("timed out")):
        out = matlas.search("x")
    assert out["results"] == [] and out["error"].startswith("TimeoutError")


def test_malformed_json_body_yields_error_envelope():
    # matlas.py:73-74 — a 200 with non-JSON body -> JSONDecodeError -> envelope.
    # Bypass json.dumps in the fake by returning raw bytes via a custom urlopen.
    orig = matlas.urllib.request.urlopen

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        return _Resp(b"this is not json {{{")

    matlas.urllib.request.urlopen = fake
    try:
        out = matlas.search("x")
    finally:
        matlas.urllib.request.urlopen = orig
    assert out["results"] == [] and out["error"].startswith("JSONDecodeError")


def test_num_results_non_positive_defaults_to_ten():
    # a non-positive num_results is clamped to the default 10 (matlas.py:54)
    captured = {}

    orig = matlas.urllib.request.urlopen

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        captured["body"] = req.data.decode("utf-8")
        return _Resp(json.dumps([]).encode("utf-8"))

    matlas.urllib.request.urlopen = fake
    try:
        matlas.search("q", num_results=0)
    finally:
        matlas.urllib.request.urlopen = orig
    assert '"num_results": 10' in captured["body"]


def test_main_smoke_runs_offline(capsys=None):
    # matlas.py:94-100 — the __main__ smoke block prints count/error + up to 3
    # results, using a mocked endpoint (no network). Run via runpy with argv set.
    import runpy
    import sys

    payload = [{"title": "T", "theorem": "thm body", "arxiv_id": "2601.1", "theorem_id": "t1"}]
    orig_argv = sys.argv
    with _mock_urlopen(payload=payload):
        sys.argv = ["matlas", "a math statement"]
        try:
            runpy.run_module("danus.integrations.matlas", run_name="__main__")
        finally:
            sys.argv = orig_argv


def main() -> None:
    test_empty_query_short_circuits()
    print("  [ok] empty query short-circuits")
    test_normalization_of_results()
    print("  [ok] normalization: 4 fields, non-dict dropped")
    test_network_error_never_raises()
    print("  [ok] network error -> error envelope, never raises")
    test_non_list_body_is_error_not_crash()
    print("  [ok] non-list body -> error envelope")
    test_http_error_yields_error_envelope()
    print("  [ok] HTTPError -> 'http <code>' envelope, never raises")
    test_timeout_yields_error_envelope()
    print("  [ok] TimeoutError -> error envelope")
    test_malformed_json_body_yields_error_envelope()
    print("  [ok] malformed JSON body -> JSONDecodeError envelope")
    test_num_results_non_positive_defaults_to_ten()
    print("  [ok] non-positive num_results clamped to 10")
    test_main_smoke_runs_offline()
    print("  [ok] __main__ smoke runs offline (mocked endpoint)")
    print("ALL INTEGRATIONS TESTS PASSED")


if __name__ == "__main__":
    main()
