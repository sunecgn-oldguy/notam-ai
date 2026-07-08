"""Tests for notam.fetchcache — TTL, empty-list caching, and single-flight."""
import threading
import time

from notam import fetchcache

_fails = 0


def check(label, cond):
    global _fails
    print(f"[{'ok' if cond else 'FAIL'}] {label}")
    if not cond:
        _fails += 1


# --- TTL: miss -> fetch, hit within TTL, refetch after expiry ---
fetchcache.clear()
calls = {"n": 0}
def fetch():
    calls["n"] += 1
    return ["notam-" + str(calls["n"])]

v1 = fetchcache.get_or_fetch("EDDK", fetch, ttl=60, now=1000)
v2 = fetchcache.get_or_fetch("EDDK", fetch, ttl=60, now=1030)   # within TTL -> hit
check("hit within TTL reuses the value (no 2nd fetch)", v1 == v2 and calls["n"] == 1)
v3 = fetchcache.get_or_fetch("EDDK", fetch, ttl=60, now=1100)   # past TTL -> refetch
check("expiry triggers a fresh fetch", calls["n"] == 2 and v3 != v1)

# --- empty results are cached too (don't refetch airports with 0 NOTAMs) ---
fetchcache.clear()
ecalls = {"n": 0}
def fetch_empty():
    ecalls["n"] += 1
    return []
fetchcache.get_or_fetch("XXXX", fetch_empty, ttl=60, now=1000)
r = fetchcache.get_or_fetch("XXXX", fetch_empty, ttl=60, now=1005)
check("empty list is cached (fetcher called once)", r == [] and ecalls["n"] == 1)

# --- distinct keys don't collide ---
fetchcache.clear()
a = fetchcache.get_or_fetch("EDDK", lambda: ["a"], ttl=60, now=1000)
b = fetchcache.get_or_fetch("EKVG", lambda: ["b"], ttl=60, now=1000)
check("distinct keys are independent", a == ["a"] and b == ["b"])

# --- single-flight: 30 concurrent misses for one key => ONE upstream fetch ---
fetchcache.clear()
sf = {"n": 0}
lock = threading.Lock()
def slow_fetch():
    with lock:
        sf["n"] += 1
    time.sleep(0.15)                 # widen the race window
    return ["shared"]

results = []
rlock = threading.Lock()
def worker():
    v = fetchcache.get_or_fetch("EGLL", slow_fetch, ttl=60)   # real time.time()
    with rlock:
        results.append(v)

threads = [threading.Thread(target=worker) for _ in range(30)]
for t in threads: t.start()
for t in threads: t.join()
check("single-flight: 30 concurrent callers -> 1 fetch", sf["n"] == 1)
check("single-flight: all 30 got the shared value", len(results) == 30 and all(r == ["shared"] for r in results))

print("\n" + ("ALL PASSED" if _fails == 0 else f"{_fails} FAILED"))
