"""Wait until Snip reports that links and stats are both ready.

Usage:  python scripts/wait_ready.py http://ADDRESS [SECONDS]

Used by the pipeline after `docker compose up`: the Firestore emulator
takes a while to start, and until it has, links and stats are not ready.
Exit code 0 as soon as /api/status says both are "ok", 1 on timeout.
"""
import json
import sys
import time
import urllib.request


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    limit = int(sys.argv[2]) if len(sys.argv) == 3 else 120
    started = time.time()
    last = "no answer yet"
    while time.time() - started < limit:
        try:
            with urllib.request.urlopen(base + "/api/status", timeout=5) as response:
                state = json.loads(response.read())
            last = str(state)
            if state.get("links") == "ok" and state.get("stats") == "ok":
                print(f"ready after {time.time() - started:.0f}s: {last}")
                return 0
        except Exception as error:  # not listening yet, connection reset, ...
            last = f"{type(error).__name__}: {error}"
        time.sleep(3)
    print(f"not ready after {limit}s; last answer: {last}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
