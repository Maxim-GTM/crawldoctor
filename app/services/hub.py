"""GTM Hub single sign-on: ask the hub who the browser's session belongs to."""
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()

VERIFY_TIMEOUT_SECONDS = 5.0
CACHE_TTL_SECONDS = 60
CACHE_MAX_ENTRIES = 1000

# Identity used for every request when HUB_SSO_DISABLED=true (local development only).
DEV_USER = {"id": "dev", "email": "dev@localhost", "name": "Local dev", "image": None, "role": "admin"}


class HubUnavailable(Exception):
    """The hub gave no usable answer; callers must fail closed."""


@dataclass
class HubSession:
    """Hub verdict: 200 (allowed), 401 (not signed in) or 403 (signed in, no access to this app)."""
    status: int
    user: Optional[Dict[str, Any]] = None


# SHA-256 of the forwarded cookies -> (expires_at, session). Positive answers only.
_cache: Dict[str, Tuple[float, HubSession]] = {}


def hub_url() -> str:
    return settings.hub_url.rstrip("/")


def login_url(path: str = "/") -> str:
    """Hub login URL that sends the browser back to `path` on this app afterwards."""
    # Only same-app paths: "//host" or "/\host" would point browsers at another site.
    if not path.startswith("/") or path.startswith("//") or path.startswith("/\\"):
        path = "/"
    next_url = settings.app_public_url.rstrip("/") + path
    return f"{hub_url()}/login?next={quote(next_url, safe='')}"


def no_access_url() -> str:
    return f"{hub_url()}/no-access?app={quote(settings.hub_app_slug, safe='')}"


def signout_url() -> str:
    return f"{hub_url()}/signout"


def hub_cookies(raw_cookie_header: str) -> str:
    """Keep only the Better Auth cookies, byte-for-byte (the session token is signed)."""
    kept = []
    for part in (raw_cookie_header or "").split(";"):
        part = part.strip()
        if "better-auth." in part.split("=", 1)[0]:
            kept.append(part)
    return "; ".join(kept)


def _remember(key: str, session: HubSession) -> None:
    now = time.monotonic()
    for stale in [k for k, (expires_at, _) in _cache.items() if expires_at <= now]:
        del _cache[stale]
    while len(_cache) >= CACHE_MAX_ENTRIES:
        del _cache[next(iter(_cache))]
    _cache[key] = (now + CACHE_TTL_SECONDS, session)


async def verify(raw_cookie_header: str) -> HubSession:
    """Ask the hub whether this browser may use CrawlDoctor. Raises HubUnavailable on any failure."""
    if settings.hub_sso_disabled:
        return HubSession(status=200, user=dict(DEV_USER))

    cookies = hub_cookies(raw_cookie_header)
    if not cookies:
        return HubSession(status=401)

    key = hashlib.sha256(cookies.encode()).hexdigest()
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.get(
                f"{hub_url()}/api/sso/verify",
                params={"app": settings.hub_app_slug},
                headers={"Cookie": cookies, "Accept": "application/json"},
            )
    except httpx.HTTPError as e:
        logger.error("GTM Hub verify request failed", error=str(e) or type(e).__name__)
        raise HubUnavailable() from e

    if response.status_code == 404:
        logger.error(
            "GTM Hub does not know this app (unknown_app); check HUB_APP_SLUG",
            app=settings.hub_app_slug,
        )
        raise HubUnavailable()
    if response.status_code not in (200, 401, 403):
        logger.error("GTM Hub verify returned an unexpected status", status_code=response.status_code)
        raise HubUnavailable()

    try:
        body = response.json()
    except ValueError as e:
        logger.error("GTM Hub verify returned invalid JSON", status_code=response.status_code)
        raise HubUnavailable() from e

    if response.status_code == 401:
        return HubSession(status=401)
    if response.status_code == 403:
        user = body.get("user") if isinstance(body, dict) else None
        return HubSession(status=403, user=user if isinstance(user, dict) else None)

    user = body.get("user") if isinstance(body, dict) else None
    if not isinstance(user, dict) or not user.get("email"):
        logger.error("GTM Hub verify returned 200 without a user email")
        raise HubUnavailable()

    session = HubSession(status=200, user=user)
    _remember(key, session)
    return session
