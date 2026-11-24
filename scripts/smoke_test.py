"""End-to-end check of a running Snip deployment.

Usage:  python scripts/smoke_test.py http://ADDRESS [EXPECTED_VERSION]

With EXPECTED_VERSION (a Git commit), it also checks that every web pod
that answers is running the image built from that commit.

Works against the local docker compose stack (http://localhost:8080) and
against the live load balancer address. Uses only the standard library.
Exit code 0 means every check passed.
"""
import json
import sys
import time
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop urllib from following redirects so we can inspect them."""

    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)


def request(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def main():
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    expected_version = sys.argv[2] if len(sys.argv) == 3 else None
    results = []

    def check(name, passed, detail=""):
        results.append(passed)
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

    status, headers, body = request(base, "GET", "/healthz")
    check("web liveness /healthz returns 200", status == 200, f"status {status}")

    status, headers, body = request(base, "GET", "/readyz")
    check("web readiness /readyz returns 200", status == 200, f"status {status}")

    status, headers, body = request(base, "GET", "/")
    check("page is served", status == 200 and b"Snip" in body, f"status {status}")

    target = f"https://example.com/smoke-{int(time.time())}"
    status, headers, body = request(base, "POST", "/api/links", {"url": target})
    check("create a short link (web -> links -> datastore)", status == 201, f"status {status}")
    if status != 201:
        return 1
    code = json.loads(body)["code"]

    status, headers, body = request(base, "POST", "/api/links", {"url": "javascript:alert(1)"})
    check("invalid address is rejected with 422", status == 422, f"status {status}")

    clicks = 3
    ok = True
    for _ in range(clicks):
        status, headers, body = request(base, "GET", f"/r/{code}")
        ok = ok and status == 307 and headers.get("location", headers.get("Location")) == target
    check(f"short link redirects to the original address ({clicks} clicks)", ok, f"status {status}")

    status, headers, body = request(base, "GET", "/r/nothere")
    check("unknown link returns 404", status == 404, f"status {status}")

    # Clicks are recorded just after the redirect is sent, so allow a moment.
    counted = None
    stats_available = None
    for _ in range(10):
        status, headers, body = request(base, "GET", "/api/links")
        if status == 200:
            data = json.loads(body)
            stats_available = data["stats_available"]
            for link in data["links"]:
                if link["code"] == code:
                    counted = link["clicks"]
            if counted == clicks:
                break
        time.sleep(0.5)
    check("list shows the new link", counted is not None or stats_available is False, f"status {status}")
    check("stats service is answering", stats_available is True)
    check(f"clicks were counted (web -> stats -> datastore)", counted == clicks, f"counted {counted}")

    status, headers, body = request(base, "GET", "/api/status")
    state = json.loads(body) if status == 200 else {}
    check("status endpoint reports links and stats ready",
          state.get("links") == "ok" and state.get("stats") == "ok", str(state))

    request_id = headers.get("X-Request-ID", headers.get("x-request-id", ""))
    check("responses carry a request ID for tracing", len(request_id) == 12, request_id)

    pods = set()
    versions = set()
    for _ in range(20):
        status, headers, body = request(base, "GET", "/api/whoami")
        if status == 200:
            answer = json.loads(body)
            pods.add(answer["pod"])
            versions.add(answer.get("version", "?"))
    check("web pods answering", len(pods) >= 1, ", ".join(sorted(pods)))
    if expected_version:
        check("every pod runs the expected commit", versions == {expected_version},
              ", ".join(sorted(versions)))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
