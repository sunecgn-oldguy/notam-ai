"""Provider-agnostic token counter for the AI layer.

Both Claude and a local qwen report token counts, so we accumulate them in one
shape. With Claude, tokens ≈ money; with a local qwen they are just a load
measure — the counter carries over, only its meaning changes.

Counts real model calls only (cache hits, trigger NOTAMs and the 'none' provider
spend nothing and are not recorded). In-memory and per-process, so it resets when
the server restarts — i.e. "usage since the server last started".
Thread-safe: summaries run in parallel.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_totals = {"calls": 0, "input": 0, "output": 0, "by_provider": {}}


def record(provider: str, input_tokens: int, output_tokens: int) -> None:
    with _lock:
        _totals["calls"] += 1
        _totals["input"] += input_tokens
        _totals["output"] += output_tokens
        p = _totals["by_provider"].setdefault(
            provider, {"calls": 0, "input": 0, "output": 0})
        p["calls"] += 1
        p["input"] += input_tokens
        p["output"] += output_tokens


def snapshot() -> dict:
    with _lock:
        return {
            "calls": _totals["calls"],
            "input_tokens": _totals["input"],
            "output_tokens": _totals["output"],
            "total_tokens": _totals["input"] + _totals["output"],
            "by_provider": {k: dict(v) for k, v in _totals["by_provider"].items()},
        }


def reset() -> None:
    with _lock:
        _totals["calls"] = 0
        _totals["input"] = 0
        _totals["output"] = 0
        _totals["by_provider"] = {}
