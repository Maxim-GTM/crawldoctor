"""Unit tests for where the GTM Hub sign-in check goes. No server or network needed.

HUB_INTERNAL_URL sends the server-side verify call to the hub's container on the shared
network; everything the browser follows (login, no-access, sign-out) stays on HUB_URL.
"""
import httpx
import pytest

from app.config import Settings
from app.services import hub

COOKIE = "better-auth.session_token=abc.def"


@pytest.fixture
def verify_calls(monkeypatch):
    """Every verify request goes to a mock hub that signs the user in; returns the URLs called."""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"user": {"email": "dev@getmaxim.ai", "role": "member"}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        hub.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(hub, "_cache", {})
    monkeypatch.setattr(hub.settings, "hub_sso_disabled", False)
    monkeypatch.setattr(hub.settings, "hub_url", "https://hub.example.com/")
    monkeypatch.setattr(hub.settings, "hub_app_slug", "crawldoctor")
    monkeypatch.setattr(hub.settings, "app_public_url", "https://crawldoctor.example.com")
    return calls


@pytest.mark.asyncio
async def test_verify_uses_hub_internal_url_and_browser_urls_stay_on_hub_url(verify_calls, monkeypatch):
    monkeypatch.setattr(hub.settings, "hub_internal_url", "http://hub:3000/")

    session = await hub.verify(COOKIE)

    assert session.status == 200
    assert verify_calls == ["http://hub:3000/api/sso/verify?app=crawldoctor"]
    assert hub.login_url("/dashboard") == (
        "https://hub.example.com/login?next=https%3A%2F%2Fcrawldoctor.example.com%2Fdashboard"
    )
    assert hub.no_access_url() == "https://hub.example.com/no-access?app=crawldoctor"
    assert hub.signout_url() == "https://hub.example.com/signout"


@pytest.mark.asyncio
@pytest.mark.parametrize("internal", ["", "  "])
async def test_verify_falls_back_to_hub_url(verify_calls, monkeypatch, internal):
    monkeypatch.setattr(hub.settings, "hub_internal_url", internal)

    await hub.verify(COOKIE)

    assert verify_calls == ["https://hub.example.com/api/sso/verify?app=crawldoctor"]


def test_hub_internal_url_is_read_without_prefix(monkeypatch):
    monkeypatch.setenv("HUB_INTERNAL_URL", "http://hub:3000")
    assert Settings(_env_file=None).hub_internal_url == "http://hub:3000"

    monkeypatch.delenv("HUB_INTERNAL_URL")
    assert Settings(_env_file=None).hub_internal_url == ""
