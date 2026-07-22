"""Usage counting: what the server records, and what survives a redeploy.

Two halves, because the number has to be right across two failure modes that
actually happen: the server restarts (in-memory counters drop to zero) and the
stats endpoint is briefly unreachable (a poll returns nothing). Either one, done
naively, silently inflates the count — so both are pinned here.

Run: python3 test_stats.py
"""
import sys

sys.path.insert(0, ".github/scripts")

import log_usage                                    # noqa: E402
from notam import stats                             # noqa: E402


def check(label, got, exp):
    assert got == exp, f"{label}: got {got!r}, expected {exp!r}"
    print(f"[ok] {label:44} {got}")


# ---- what the server accepts as a device id --------------------------------
stats.reset()
for did in ("a1b2c3d4e5f60718",      # a real one
            "a1b2c3d4e5f60718",      # same pilot again -> still one device
            "FFFF0000FFFF0000",      # case is normalised
            "<script>alert(1)</script>", "", "   ", "short", None):
    stats.record(did)
snap = stats.snapshot(with_devices=True)
check("every briefing counted, junk ids included", snap["briefings"], 8)
check("only well-formed ids kept", snap["devices"], 2)
check("ids normalised to lowercase",
      snap["device_ids"], ["a1b2c3d4e5f60718", "ffff0000ffff0000"])
check("roster hidden unless asked for", "device_ids" in stats.snapshot(), False)


# ---- what survives across polls --------------------------------------------
def poll(state, ids, briefings, reachable=True):
    """One keep-alive poll, mirroring log_usage.main()."""
    cur = {"device_ids": ids, "briefings": briefings} if reachable else {}
    now = briefings if reachable else int(
        (state.get("last_snapshot") or {}).get("briefings", 0))
    users, total, new_users, delta = log_usage.accumulate_stats(state, cur, now)
    return {"users": users, "lifetime": {"briefings": total},
            "last_snapshot": {"briefings": now}}

s = poll({}, ["aaa1"], 3)
check("first poll", s["lifetime"]["briefings"], 3)

s = poll(s, ["aaa1", "bbb2"], 5)
check("second poll adds only the delta", s["lifetime"]["briefings"], 5)

s = poll(s, None, 0, reachable=False)
check("endpoint down: count frozen, not zeroed", s["lifetime"]["briefings"], 5)

s = poll(s, ["aaa1", "bbb2", "ccc3"], 8)
check("after the outage: no double count", s["lifetime"]["briefings"], 8)

s = poll(s, ["bbb2"], 2)                      # counter dropped -> redeploy
check("redeploy: whole snapshot is new", s["lifetime"]["briefings"], 10)
check("returning pilot counted once, not twice",
      s["users"], ["aaa1", "bbb2", "ccc3"])

print("\nALL PASSED")
