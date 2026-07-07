#!/usr/bin/env python3
"""Accumulate lifetime AI-token usage into a secret GitHub Gist.

Run by .github/workflows/keepalive.yml every ~10 min. The app's /usage counter
is in-memory and resets on every redeploy; this job polls it and adds the delta
to a running lifetime total stored in a Gist — which survives redeploys, unlike
Render's ephemeral disk (see notam/usage.py and notam/cache.py).

Reset detection: keep-alive stops the service from sleeping, so /usage grows
monotonically EXCEPT it drops to a low value after a redeploy. If the current
snapshot's call count is lower than the last one we saw, a redeploy happened, so
the whole current snapshot counts as new usage (the <10 min tail before the
redeploy is lost — an acceptable approximation for a lifetime figure).

Config via env (set as GitHub repo secrets):
  APP_URL     base URL of the app (e.g. https://notam-ai.onrender.com)
  GIST_ID     id of a secret Gist holding notam-ai-usage.json
  GIST_TOKEN  a Personal Access Token with the 'gist' scope
Missing config or transient errors are non-fatal — the run is skipped, never
failed, so the keep-alive ping is never affected.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

APP_URL = os.environ.get("APP_URL", "").rstrip("/")
GIST_ID = os.environ.get("GIST_ID", "")
GIST_TOKEN = os.environ.get("GIST_TOKEN", "")
FILENAME = "notam-ai-usage.json"
_FIELDS = ("calls", "input", "output")


def accumulate(life: dict, last: dict, cur: dict):
    """Pure core: fold the current snapshot into the lifetime total.

    Returns (new_lifetime, delta, reset). `reset` is True when the counter
    dropped since last poll (a redeploy), in which case the whole snapshot is
    the delta; otherwise the delta is the per-field growth.
    """
    reset = cur["calls"] < last.get("calls", 0)
    delta = {k: cur[k] if reset else max(0, cur[k] - last.get(k, 0)) for k in _FIELDS}
    new = {k: life.get(k, 0) + delta[k] for k in _FIELDS}
    new["total"] = new["input"] + new["output"]
    return new, delta, reset


def _get_json(url, headers, timeout=30):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _skip(msg):
    print(f"[usage-log] skip: {msg}")
    sys.exit(0)


def main():
    if not (APP_URL and GIST_ID and GIST_TOKEN):
        _skip("GIST_ID / GIST_TOKEN / APP_URL not configured yet")

    # 1. current in-memory snapshot from the app
    try:
        snap = _get_json(f"{APP_URL}/usage", {"User-Agent": "notam-ai-usage-log"})
    except Exception as e:                        # asleep / redeploying / down
        _skip(f"could not read {APP_URL}/usage ({e})")

    cur = {"calls": int(snap.get("calls", 0)),
           "input": int(snap.get("input_tokens", 0)),
           "output": int(snap.get("output_tokens", 0))}

    gh = {"Authorization": f"Bearer {GIST_TOKEN}",
          "Accept": "application/vnd.github+json",
          "User-Agent": "notam-ai-usage-log"}

    # 2. read stored state from the Gist
    try:
        gist = _get_json(f"https://api.github.com/gists/{GIST_ID}", gh)
    except Exception as e:
        _skip(f"could not read Gist {GIST_ID} ({e}) — check GIST_ID and token scope")

    files = gist.get("files", {}) or {}
    state = {}
    if FILENAME in files and files[FILENAME].get("content"):
        try:
            state = json.loads(files[FILENAME]["content"])
        except Exception:
            state = {}
    life = state.get("lifetime", {})
    last = state.get("last_snapshot", {})

    # 3. fold in the new snapshot
    new_life, delta, reset = accumulate(life, last, cur)
    if sum(delta.values()) == 0 and last == cur:
        print("[usage-log] no change since last poll — nothing to write")
        return

    new_state = {
        "lifetime": new_life,
        "last_snapshot": cur,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Lifetime AI-token usage across all redeploys. Written by keepalive.yml.",
    }
    body = json.dumps(
        {"files": {FILENAME: {"content": json.dumps(new_state, indent=2)}}}).encode()

    # 4. write back to the Gist
    req = urllib.request.Request(f"https://api.github.com/gists/{GIST_ID}",
                                 data=body, headers=gh, method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except Exception as e:
        _skip(f"could not update Gist ({e})")

    tag = "reset detected, added full snapshot" if reset else "added delta"
    print(f"[usage-log] {tag}: +{delta} -> lifetime {new_life}")


if __name__ == "__main__":
    main()
