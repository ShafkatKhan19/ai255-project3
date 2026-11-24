"""web service: the only public service. Serves the page and is the gateway
to the two internal services.

  browser -> web -> links  (create and look up short links)
                 -> stats  (count clicks)

Endpoints
  GET  /              the page (its script and styles are under /static)
  GET  /api/links     list of links with click counts
  POST /api/links     create a short link
  GET  /r/{code}      redirect to the original address and count the click
  GET  /api/status    whether links and stats can do their job right now
  GET  /api/whoami    which pod answered (used to show load balancing)
  GET  /healthz       liveness
  GET  /readyz        readiness
"""
import asyncio
import collections
import json
import logging
import os
import re
import socket
import time
import uuid
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s web %(levelname)s %(message)s")
log = logging.getLogger("web")

# Inside the cluster these names are resolved by Kubernetes DNS to the
# Service in front of each set of pods.
LINKS_URL = os.environ.get("LINKS_URL", "http://links:8080")
STATS_URL = os.environ.get("STATS_URL", "http://stats:8080")

# The Git commit this image was built from. The pipeline sets it when it
# builds the image, so /api/whoami shows which commit is serving.
VERSION = os.environ.get("VERSION", "dev")

# links is needed to answer, so it gets a longer wait. stats is optional,
# so it gets a short one and the page never waits long for it.
LINKS_TIMEOUT = 4.0
STATS_TIMEOUT = 1.0

CODE_PATTERN = re.compile(r"^[a-z0-9]{1,32}$")
POD = socket.gethostname()
STATIC = Path(__file__).parent / "static"
INDEX = STATIC / "index.html"

# Sent with every response. The page loads its script and styles only from
# this site, so text injected into the page cannot run as code, and the
# page cannot be shown inside a frame on another site.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# Limits on creating links, per visitor and per web pod. Each pod counts
# on its own, so with several pods the real limit is a few times higher.
CREATE_LIMIT = 10        # new links ...
CREATE_WINDOW = 60.0     # ... per this many seconds
MAX_BODY_BYTES = 4096
recent_creates = {}      # visitor address -> times of their recent creates

app = FastAPI(title="web")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# One shared client, so connections to links and stats are reused. Idle
# connections are dropped after 5 seconds: a Kubernetes Service picks a pod
# when a connection is opened, so long-lived connections would keep sending
# everything to the same pods and ignore new ones added by the autoscaler.
http = httpx.AsyncClient(limits=httpx.Limits(keepalive_expiry=5.0))


@app.middleware("http")
async def tag_and_log(request: Request, call_next):
    """Give every request an ID, pass it to links and stats, and log it.

    Searching the three services' logs for one ID shows the whole path of
    one request.
    """
    request.state.request_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Served-By"] = POD
    response.headers["X-Request-ID"] = request.state.request_id
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    if scheme_of(request) == "https":
        # Tell the browser to use HTTPS for this host for the next day.
        response.headers["Strict-Transport-Security"] = "max-age=86400"
    if request.url.path not in ("/healthz", "/readyz", "/api/whoami"):
        log.info(
            "%s %s -> %s in %.0f ms request_id=%s",
            request.method, request.url.path, response.status_code,
            (time.perf_counter() - started) * 1000, request.state.request_id,
        )
    return response


def scheme_of(request):
    """'https' when the visitor reached the load balancer over HTTPS.

    The HTTPS load balancer decrypts the request and passes it on as plain
    HTTP, with the original scheme in the X-Forwarded-Proto header.
    """
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return forwarded if forwarded in ("http", "https") else request.url.scheme


def public_base(request):
    """The address the visitor used, for building short links."""
    return f"{scheme_of(request)}://{request.headers.get('host', request.url.netloc)}/"


def visitor_of(request):
    """The visitor's address, for rate limiting.

    Google's HTTPS load balancer adds "<visitor>, <load balancer>" to the
    end of X-Forwarded-For, so the visitor is second from the end. Anything
    before that was sent by the visitor and cannot be trusted.
    """
    parts = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    if len(parts) >= 2:
        return parts[-2]
    return request.client.host if request.client else "unknown"


def allow_create(visitor):
    """True if this visitor may create another link right now."""
    now = time.monotonic()
    if len(recent_creates) > 10000:
        recent_creates.clear()  # keep memory bounded
    times = recent_creates.setdefault(visitor, collections.deque())
    while times and now - times[0] > CREATE_WINDOW:
        times.popleft()
    if len(times) >= CREATE_LIMIT:
        return False
    times.append(now)
    return True


async def call(method, url, timeout, request_id, retries=0, **kwargs):
    """Call another service.

    A retry happens only when the connection failed (for example the pod
    was just killed), not when the service was slow: retrying a slow
    service only adds load to it. Retries are only requested for GETs,
    because repeating a GET cannot create anything twice.
    """
    headers = {"X-Request-ID": request_id}
    attempt = 0
    while True:
        try:
            return await http.request(method, url, timeout=timeout, headers=headers, **kwargs)
        except httpx.TimeoutException:
            raise
        except httpx.TransportError as error:
            if attempt >= retries:
                raise
            attempt += 1
            log.warning("retrying %s %s after %s", method, url, type(error).__name__)


def links_down(error):
    log.error("links service unavailable: %s", error)
    return HTTPException(
        status_code=503,
        detail="links service unavailable",
        headers={"Retry-After": "5"},
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "web", "pod": POD}


@app.get("/readyz")
async def readyz():
    # web is ready as soon as it is running. It does not check links or
    # stats here on purpose: if it did, one broken backend would mark every
    # web pod unready and the whole site would vanish instead of showing a
    # clear error message.
    return {"status": "ready"}


@app.get("/api/whoami")
async def whoami():
    return {"pod": POD, "version": VERSION}


@app.get("/")
async def index():
    return FileResponse(INDEX)


async def backend_state(base_url, request_id):
    """'ok' if the service's readiness check passes, otherwise 'down'."""
    try:
        response = await call("GET", f"{base_url}/readyz", LINKS_TIMEOUT, request_id)
        return "ok" if response.status_code == 200 else "down"
    except httpx.HTTPError:
        return "down"


@app.get("/api/status")
async def status(request: Request):
    request_id = request.state.request_id
    links, stats = await asyncio.gather(
        backend_state(LINKS_URL, request_id), backend_state(STATS_URL, request_id)
    )
    return {"web": "ok", "links": links, "stats": stats, "pod": POD}


@app.get("/api/links")
async def list_links(request: Request):
    request_id = request.state.request_id
    try:
        response = await call("GET", f"{LINKS_URL}/links", LINKS_TIMEOUT, request_id, retries=1)
    except httpx.HTTPError as error:
        raise links_down(error)
    if response.status_code != 200:
        raise links_down(f"status {response.status_code}")
    links = response.json()["links"]

    # Click counts are a nice-to-have. If stats is down, still show the links.
    stats_available = True
    counts = {}
    if links:
        codes = ",".join(link["code"] for link in links)
        try:
            response = await call(
                "GET", f"{STATS_URL}/clicks", STATS_TIMEOUT, request_id, params={"codes": codes}
            )
            if response.status_code == 200:
                counts = response.json()["clicks"]
            else:
                stats_available = False
        except httpx.HTTPError as error:
            log.warning("stats unavailable: %s", type(error).__name__)
            stats_available = False

    base = public_base(request)
    for link in links:
        link["short_url"] = f"{base}r/{link['code']}"
        link["clicks"] = counts.get(link["code"], 0) if stats_available else None
    return {"links": links, "stats_available": stats_available, "pod": POD}


@app.post("/api/links", status_code=201)
async def create_link(request: Request):
    if not allow_create(visitor_of(request)):
        raise HTTPException(
            status_code=429,
            detail="too many new links, please wait a minute",
            headers={"Retry-After": str(int(CREATE_WINDOW))},
        )
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request too large")
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="body must be JSON")
    try:
        # No retry here: sending a create twice could make two links.
        response = await call(
            "POST", f"{LINKS_URL}/links", LINKS_TIMEOUT, request.state.request_id, json=body
        )
    except httpx.HTTPError as error:
        raise links_down(error)
    if response.status_code == 422:
        raise HTTPException(status_code=422, detail="please enter a valid http or https address")
    if response.status_code != 201:
        raise links_down(f"status {response.status_code}")
    link = response.json()
    link["short_url"] = f"{public_base(request)}r/{link['code']}"
    return link


async def record_click(code, request_id):
    """Tell stats about a click. Runs after the redirect has been sent."""
    try:
        response = await call("POST", f"{STATS_URL}/clicks/{code}", STATS_TIMEOUT, request_id)
        if response.status_code != 202:
            log.warning("click for %s not recorded: status %s", code, response.status_code)
    except httpx.HTTPError as error:
        # The click is lost, but the visitor already got their redirect.
        log.warning("click for %s not recorded: %s", code, type(error).__name__)


@app.get("/r/{code}")
async def follow(code: str, request: Request, background: BackgroundTasks):
    request_id = request.state.request_id
    if not CODE_PATTERN.match(code):
        raise HTTPException(status_code=404, detail="link not found")
    try:
        response = await call(
            "GET", f"{LINKS_URL}/links/{code}", LINKS_TIMEOUT, request_id, retries=1
        )
    except httpx.HTTPError as error:
        raise links_down(error)
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="link not found")
    if response.status_code != 200:
        raise links_down(f"status {response.status_code}")
    background.add_task(record_click, code, request_id)
    # 307 is a temporary redirect, so browsers ask again next time and
    # every click is counted.
    return RedirectResponse(response.json()["url"], status_code=307)
