"""The three services working together, and what happens when one is down.

The real web, links and stats apps are wired to each other in memory, so
these tests exercise the same code paths as the deployed system without
needing a network. Passing None for a service simulates it being down
(the connection is refused).
"""
import asyncio

import httpx

from conftest import load_service


class Wiring(httpx.AsyncBaseTransport):
    """Sends requests for http://links and http://stats to the right app."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.request_ids = []

    async def handle_async_request(self, request):
        self.calls.append((request.method, request.url.host, request.url.path))
        self.request_ids.append(request.headers.get("x-request-id"))
        target = self.routes.get(request.url.host)
        if target is None:
            raise httpx.ConnectError("connection refused", request=request)
        if target == "slow":
            raise httpx.ReadTimeout("timed out", request=request)
        return await target.handle_async_request(request)


class System:
    def __init__(self, links_up=True, stats_up=True):
        self.web = load_service("web")
        self.links = load_service("links")
        self.stats = load_service("stats")
        self.wiring = Wiring({})
        self.set_up("links", links_up)
        self.set_up("stats", stats_up)
        self.web.http = httpx.AsyncClient(transport=self.wiring)
        self.browser = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.web.app), base_url="http://snip.test"
        )

    def set_up(self, name, up):
        """up=True: working. up=False: connection refused. up="slow": times out."""
        app = getattr(self, name).app
        if up == "slow":
            self.wiring.routes[name] = "slow"
        else:
            self.wiring.routes[name] = httpx.ASGITransport(app=app) if up else None

    def get(self, path):
        return asyncio.run(self.browser.get(path))

    def post(self, path, **kwargs):
        return asyncio.run(self.browser.post(path, **kwargs))


def test_full_flow_create_click_count():
    system = System()
    created = system.post("/api/links", json={"url": "https://example.com/hello"})
    assert created.status_code == 201
    code = created.json()["code"]
    assert created.json()["short_url"] == f"http://snip.test/r/{code}"

    for _ in range(2):
        redirect = system.get(f"/r/{code}")
        assert redirect.status_code == 307
        assert redirect.headers["location"] == "https://example.com/hello"

    listing = system.get("/api/links").json()
    assert listing["stats_available"] is True
    assert listing["links"][0]["code"] == code
    assert listing["links"][0]["clicks"] == 2


def test_every_response_names_the_pod():
    system = System()
    assert system.get("/api/whoami").headers["x-served-by"]
    assert system.get("/").headers["x-served-by"]


def test_page_is_served():
    page = System().get("/")
    assert page.status_code == 200
    assert "Snip" in page.text


def test_unknown_link_is_404():
    system = System()
    assert system.get("/r/nothere").status_code == 404
    assert system.get("/r/BAD$CODE").status_code == 404


def test_invalid_address_is_explained():
    response = System().post("/api/links", json={"url": "javascript:alert(1)"})
    assert response.status_code == 422
    assert "valid" in response.json()["detail"]


def test_stats_down_redirects_still_work():
    system = System()
    code = system.post("/api/links", json={"url": "https://example.com/a"}).json()["code"]
    system.set_up("stats", False)

    redirect = system.get(f"/r/{code}")
    assert redirect.status_code == 307

    listing = system.get("/api/links")
    assert listing.status_code == 200
    assert listing.json()["stats_available"] is False
    assert listing.json()["links"][0]["clicks"] is None

    # When stats comes back the earlier click is gone (it was never stored).
    system.set_up("stats", True)
    assert system.get("/api/links").json()["links"][0]["clicks"] == 0


def test_links_down_gives_clear_503():
    system = System()
    code = system.post("/api/links", json={"url": "https://example.com/a"}).json()["code"]
    system.set_up("links", False)

    for response in [
        system.get("/api/links"),
        system.get(f"/r/{code}"),
        system.post("/api/links", json={"url": "https://example.com/b"}),
    ]:
        assert response.status_code == 503
        assert response.json()["detail"] == "links service unavailable"
        assert response.headers["retry-after"] == "5"

    # The page itself and the health checks do not depend on links.
    assert system.get("/").status_code == 200
    assert system.get("/healthz").status_code == 200
    assert system.get("/readyz").status_code == 200


def test_links_recovers_without_restarting_web():
    system = System(links_up=False)
    assert system.get("/api/links").status_code == 503
    system.set_up("links", True)
    assert system.get("/api/links").status_code == 200


def test_reads_are_retried_once_but_creates_are_not():
    system = System(links_up=False)
    system.get("/api/links")
    assert system.wiring.calls.count(("GET", "links", "/links")) == 2

    system.wiring.calls.clear()
    system.post("/api/links", json={"url": "https://example.com/a"})
    assert system.wiring.calls.count(("POST", "links", "/links")) == 1


def test_links_datastore_down_reaches_browser_as_503():
    system = System()

    class BrokenStore:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise RuntimeError("datastore is down")
            return fail

    system.links.store = BrokenStore()
    assert system.get("/api/links").status_code == 503
    assert system.post("/api/links", json={"url": "https://example.com"}).status_code == 503


def test_slow_links_is_not_retried():
    # A timeout means links is overloaded or stuck. Asking again would only
    # add load, so web gives up after one try.
    system = System(links_up="slow")
    assert system.get("/api/links").status_code == 503
    assert system.wiring.calls.count(("GET", "links", "/links")) == 1


def test_status_endpoint_reports_each_backend():
    system = System()
    assert system.get("/api/status").json()["links"] == "ok"
    assert system.get("/api/status").json()["stats"] == "ok"

    system.set_up("stats", False)
    status = system.get("/api/status").json()
    assert (status["web"], status["links"], status["stats"]) == ("ok", "ok", "down")

    system.set_up("links", False)
    status = system.get("/api/status").json()
    assert (status["links"], status["stats"]) == ("down", "down")


def test_one_request_id_is_passed_to_both_backends():
    system = System()
    code = system.post("/api/links", json={"url": "https://example.com/a"}).json()["code"]
    system.wiring.request_ids.clear()

    response = system.get(f"/r/{code}")
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 12
    # One call to links (look up) and one to stats (count), same ID on both.
    assert system.wiring.request_ids == [request_id, request_id]


def test_only_listed_codes_are_asked_from_stats():
    system = System()
    code = system.post("/api/links", json={"url": "https://example.com/a"}).json()["code"]
    system.wiring.calls.clear()
    system.get("/api/links")
    assert ("GET", "stats", "/clicks") in system.wiring.calls

    # With no links there is nothing to count, so stats is not called at all.
    empty = System()
    empty.get("/api/links")
    assert not [call for call in empty.wiring.calls if call[1] == "stats"]


def test_security_headers_on_every_response():
    system = System()
    for path in ["/", "/api/links", "/static/app.js", "/r/nothere"]:
        headers = system.get(path).headers
        assert "default-src 'self'" in headers["content-security-policy"]
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert "strict-transport-security" not in headers  # plain HTTP here


def test_https_requests_get_hsts_and_https_short_links():
    system = System()
    https = {"X-Forwarded-Proto": "https", "Host": "snip.example.test"}
    created = asyncio.run(system.browser.post(
        "/api/links", json={"url": "https://example.com/a"}, headers=https))
    assert created.headers["strict-transport-security"] == "max-age=86400"
    assert created.json()["short_url"].startswith("https://snip.example.test/r/")


def test_page_script_and_styles_are_served():
    system = System()
    assert "text/css" in system.get("/static/style.css").headers["content-type"]
    assert "javascript" in system.get("/static/app.js").headers["content-type"]
    # No inline script or style in the page: the security policy forbids it.
    page = system.get("/").text
    assert "<style" not in page and "<script>" not in page


def test_creating_links_is_rate_limited_per_visitor():
    system = System()
    def create(visitor):
        headers = {"X-Forwarded-For": f"{visitor}, 203.0.113.1"}
        return asyncio.run(system.browser.post(
            "/api/links", json={"url": "https://example.com/a"}, headers=headers))

    for _ in range(system.web.CREATE_LIMIT):
        assert create("198.51.100.7").status_code == 201
    blocked = create("198.51.100.7")
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"
    # A different visitor is not affected, and reading is never limited.
    assert create("198.51.100.8").status_code == 201
    assert system.get("/api/links").status_code == 200


def test_spoofed_forwarded_address_does_not_dodge_the_limit():
    system = System()
    def create(fake):
        # The visitor puts a made-up address first; the load balancer still
        # appends the real one.
        headers = {"X-Forwarded-For": f"{fake}, 198.51.100.7, 203.0.113.1"}
        return asyncio.run(system.browser.post(
            "/api/links", json={"url": "https://example.com/a"}, headers=headers))

    for i in range(system.web.CREATE_LIMIT):
        assert create(f"10.0.0.{i}").status_code == 201
    assert create("10.0.0.99").status_code == 429


def test_oversized_and_malformed_bodies_are_rejected():
    system = System()
    big = asyncio.run(system.browser.post("/api/links", content=b"x" * 5000))
    assert big.status_code == 413
    bad = asyncio.run(system.browser.post("/api/links", content=b"not json"))
    assert bad.status_code == 400


def test_whoami_reports_the_build_version():
    system = System()
    # The pipeline bakes the commit into the image as VERSION. Outside the
    # pipeline it is "dev".
    assert system.get("/api/whoami").json()["version"] == "dev"
