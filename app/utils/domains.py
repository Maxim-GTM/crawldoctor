"""Internal domain classification for Maxim/Bifrost unified session tracking."""

import re
from urllib.parse import urlparse
from typing import Iterable, Optional, Tuple

# Internal domain families — matched by exact hostname or suffix
_INTERNAL_DOMAINS = {
    "maxim": {
        "exact": {"getmaxim.ai"},
        "suffix": ".getmaxim.ai",
    },
    "bifrost": {
        "exact": {"getbifrost.ai"},
        "suffix": ".getbifrost.ai",
    },
}


def _normalize_hostname(raw: str) -> str:
    """Lowercase and strip port from a hostname string."""
    h = raw.strip().lower()
    # Strip port if present (but not IPv6 brackets)
    if h and not h.startswith("[") and ":" in h:
        h = h.rsplit(":", 1)[0]
    return h


def classify_domain(hostname: Optional[str]) -> Optional[str]:
    """Return the internal family name ('maxim' | 'bifrost') or None if external.

    Uses normalized hostname matching — never substring contains.
    """
    if not hostname:
        return None

    h = _normalize_hostname(hostname)
    if not h:
        return None

    for family, rules in _INTERNAL_DOMAINS.items():
        if h in rules["exact"]:
            return family
        if h.endswith(rules["suffix"]):
            return family

    return None


def is_internal_domain(hostname: Optional[str]) -> bool:
    """Return True when *hostname* belongs to any internal domain family."""
    return classify_domain(hostname) is not None


def is_internal_url(url: Optional[str]) -> bool:
    """Return True when the host portion of *url* is an internal domain."""
    if not url:
        return False
    try:
        return is_internal_domain(urlparse(url).netloc)
    except Exception:
        return False


def is_allowed_tracking_url(url: Optional[str], allowed_domains: Iterable[str]) -> bool:
    """True when *url* is an http(s) page on an allowed host (or a subdomain of one), default port.

    An empty *allowed_domains* allows everything. Rejects pages with no host, localhost and
    preview hosts, third-party copies of the script, and non-default ports (www.getmaxim.ai:8443).
    """
    allowed = [d.strip().lower().lstrip(".") for d in allowed_domains if d and d.strip()]
    if not allowed:
        return True
    if not url:
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not host:
        return False
    if port is not None and port not in (80, 443):
        return False
    return any(host == d or host.endswith("." + d) for d in allowed)


# Search engines whose referrals count as organic, keyed by referrer host. Hosts of other
# Google/Bing products (gemini.google.com, mail.google.com) are referrals, not searches.
_SEARCH_ENGINES = (
    (re.compile(r"^(www\.)?google(\.[a-z]{2,3}){1,2}$"), "google"),
    (re.compile(r"^((www|cn)\.)?bing\.com$"), "bing"),
    (re.compile(r"^((html|lite)\.)?duckduckgo\.com$"), "duckduckgo"),
    (re.compile(r"^([a-z]+\.)?search\.yahoo\.com$"), "yahoo"),
    (re.compile(r"^(www\.)?baidu\.com$"), "baidu"),
    (re.compile(r"^(www\.)?yandex\.(ru|com)$"), "yandex"),
    (re.compile(r"^(www\.)?ecosia\.org$"), "ecosia"),
    (re.compile(r"^search\.brave\.com$"), "brave"),
)


def referrer_attribution(
    referrer: Optional[str], page_host: Optional[str]
) -> Tuple[Optional[str], Optional[str], bool]:
    """(source, medium, is_internal) for a page reached without UTM parameters.

    - Internal navigation (a Maxim/Bifrost host, or the page's own host): (None, None, True).
      The caller attributes the page to its session's entry instead.
    - A search engine: its name, the same value as utm_source (www.google.com -> google), "organic".
    - Any other site: its host, "referral".
    """
    if not referrer:
        return None, None, False
    try:
        netloc = urlparse(referrer).netloc.lower()
    except ValueError:
        return None, None, False
    if not netloc:
        return None, None, False
    host = _normalize_hostname(netloc)
    if is_internal_domain(host) or host == _normalize_hostname(page_host or ""):
        return None, None, True
    for pattern, name in _SEARCH_ENGINES:
        if pattern.match(host):
            return name, "organic", False
    return netloc, "referral", False
