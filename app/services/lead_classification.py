"""Classify form fills and leads: enterprise_license_request, demo_bifrost, demo_maxim or other.

The labels match the 50 leads classified once by hand on 2026-08-26, the only lead_type values
production had. The rules are written from those leads and from the forms on the live site:

- enterprise_license_request: the Bifrost enterprise / free-license form, recognised by its
  gateway questions ("Are you using an LLM Gateway today?", usingGateway, "Have you tried
  Bifrost OSS?") or by the page (/enterprise, #enterprise-trial, #free-license,
  #enterprise-support).
- demo_bifrost / demo_maxim: the book-a-demo form. On 2026-08-26 the Bifrost site moved to the
  site root and /bifrost/book-a-demo started redirecting to /book-a-demo, so /book-a-demo is a
  Bifrost demo from then on and a Maxim demo before.
- other: everything else: contact, partner applications, gated downloads, newsletter and the
  footer's bifrost-support-email box (even when it was filled in on a demo or enterprise page).
"""
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Tuple
from urllib.parse import urlparse

ENTERPRISE = "enterprise_license_request"
DEMO_BIFROST = "demo_bifrost"
DEMO_MAXIM = "demo_maxim"
OTHER = "other"

# A lead with several form fills takes the most valuable type.
LEAD_TYPE_PRIORITY = (ENTERPRISE, DEMO_BIFROST, DEMO_MAXIM, OTHER)

BIFROST_SITE_MERGE_AT = datetime(2026, 8, 26, tzinfo=timezone.utc)

_ENTERPRISE_FIELD_HINTS = ("gateway", "bifrostoss")
_ENTERPRISE_FRAGMENTS = ("enterprise-trial", "free-license", "enterprise-support")
_ENTERPRISE_ACTIONS = ("enterprise-trial", "enterprise-license")
_FOOTER_FIELD_HINTS = ("supportemail", "newsletter", "subscribe")
_DEMO_PATH = re.compile(r"(^|/)(book-a-demo|demo)/?$")


def _field_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _aware(ts: Optional[datetime]) -> Optional[datetime]:
    if ts is not None and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def classify_form_fill(
    page_url: Optional[str],
    path: Optional[str],
    form_values: Optional[dict],
    form_id: Optional[str] = None,
    form_action: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> str:
    """Return the form type of one form submission."""
    keys = [_field_key(k) for k in form_values] if isinstance(form_values, dict) else []
    parsed = urlparse(page_url or "")
    path = (path or parsed.path or "/").lower()
    fragment = (parsed.fragment or "").lower()
    action = (form_action or "").lower()

    # The footer's email box is the same form on every page: never a demo or license request.
    if keys and all(any(h in k for h in _FOOTER_FIELD_HINTS) for k in keys):
        return OTHER

    if any(h in k for k in keys for h in _ENTERPRISE_FIELD_HINTS):
        return ENTERPRISE
    if any(a in action for a in _ENTERPRISE_ACTIONS):
        return ENTERPRISE

    if _DEMO_PATH.search(path):
        if path.startswith("/bifrost/"):
            return DEMO_BIFROST
        ts = _aware(timestamp)
        return DEMO_BIFROST if ts is None or ts >= BIFROST_SITE_MERGE_AT else DEMO_MAXIM

    if any(f in fragment for f in _ENTERPRISE_FRAGMENTS):
        return ENTERPRISE
    if path.rstrip("/").endswith("/enterprise"):
        return ENTERPRISE
    return OTHER


def summarize_lead(form_types: Iterable[str]) -> Tuple[Optional[str], Optional[str]]:
    """(lead_type, form_types) for lead_summaries from the types of a client's form fills."""
    types = sorted({t for t in form_types if t})
    if not types:
        return None, None
    lead_type = next((t for t in LEAD_TYPE_PRIORITY if t in types), OTHER)
    return lead_type, ",".join(types)
