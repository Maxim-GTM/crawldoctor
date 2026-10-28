"""Tracking ingestion: allowed domains, CORS, attribution and event names. No server or Postgres."""
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.api import tracking as tracking_api
from app.database import get_async_db
from app.models.visit import Visit, VisitEvent, VisitSession
from app.services import tracking as tracking_mod
from app.services.tracking import TrackingService
from app.utils.domains import is_allowed_tracking_url, referrer_attribution

ALLOWED = ["getmaxim.ai", "getbifrost.ai", "maxim-articles.ghost.io"]


@pytest.mark.parametrize("url", [
    "https://www.getmaxim.ai/pricing",
    "https://getmaxim.ai/",
    "https://webflow.getmaxim.ai/x",
    "https://docs.getbifrost.ai/overview",
    "https://maxim-articles.ghost.io/some-post/",
    "https://www.getmaxim.ai:443/enterprise",
    "http://www.getmaxim.ai/",
])
def test_allowed_pages(url):
    assert is_allowed_tracking_url(url, ALLOWED)


@pytest.mark.parametrize("url", [
    "http://localhost:3002/",
    "https://gtm-msr.appspot.com/render?id=GTM-PZVSZ6P5",
    "https://docs.modrouter.online/guide",
    "https://www.getmaxim.ai:8443/",
    "https://bifrost-website-preview.getmaxim.workers.dev/",
    "https://www-getmaxim-ai.translate.goog/pricing",
    "https://getmaxim.ai.evil.example/",
    "https://notgetmaxim.ai/",
    "about:blank",
    "",
    None,
])
def test_rejected_pages(url):
    assert not is_allowed_tracking_url(url, ALLOWED)


def test_empty_allow_list_accepts_everything():
    assert is_allowed_tracking_url("http://localhost:3002/", [])


@pytest.mark.parametrize("referrer, page_host, expected", [
    ("https://www.getmaxim.ai/", "www.getmaxim.ai", (None, None, True)),
    ("https://docs.getbifrost.ai/overview", "www.getmaxim.ai", (None, None, True)),
    ("https://maxim-articles.ghost.io/a/", "maxim-articles.ghost.io", (None, None, True)),
    ("https://www.google.com/", "www.getmaxim.ai", ("google", "organic", False)),
    ("https://www.google.com.hk/", "www.getmaxim.ai", ("google", "organic", False)),
    ("https://cn.bing.com/search?q=x", "www.getmaxim.ai", ("bing", "organic", False)),
    ("https://duckduckgo.com/", "www.getmaxim.ai", ("duckduckgo", "organic", False)),
    ("https://gemini.google.com/app", "www.getmaxim.ai", ("gemini.google.com", "referral", False)),
    ("https://github.com/maximhq/bifrost", "www.getmaxim.ai", ("github.com", "referral", False)),
    (None, "www.getmaxim.ai", (None, None, False)),
])
def test_referrer_attribution(referrer, page_host, expected):
    assert referrer_attribution(referrer, page_host) == expected


def test_utm_parameters_win_over_referrer():
    svc = TrackingService()
    page = svc._extract_page_info("https://www.getmaxim.ai/?utm_source=google&utm_medium=cpc&utm_campaign=x")
    utm = svc._extract_utm(page, "https://www.google.com/")
    assert (utm["source"], utm["medium"], utm["campaign"], utm["internal_referral"]) == ("google", "cpc", "x", False)


def test_internal_referrer_is_not_a_source():
    svc = TrackingService()
    utm = svc._extract_utm(svc._extract_page_info("https://www.getmaxim.ai/pricing"), "https://www.getmaxim.ai/")
    assert utm["source"] is None
    assert utm["internal_referral"] is True


def test_same_host_referrer_continues_session():
    assert TrackingService()._is_external_entry(
        referrer="https://maxim-articles.ghost.io/a/",
        referrer_domain="maxim-articles.ghost.io",
        page_domain="maxim-articles.ghost.io",
    ) is False


@pytest.mark.parametrize("event_type, data, expected", [
    ("navigate", {"type": "navigate", "time_on_page_ms": 5}, ("navigation", {"type": "navigate", "time_on_page_ms": 5, "kind": "unload"})),
    ("navigation", {"type": "pushState", "from": "a", "to": "b"}, ("navigation", {"type": "pushState", "from": "a", "to": "b", "kind": "spa"})),
    ("navigation", {"kind": "unload"}, ("navigation", {"kind": "unload"})),
    ("navigate", None, ("navigation", {"kind": "unload"})),
    ("click", {"href": "x"}, ("click", {"href": "x"})),
])
def test_navigation_event_names_are_unified(event_type, data, expected):
    assert TrackingService._normalize_event(event_type, data) == expected


# --- track_event end to end on SQLite ---------------------------------------------------------

@compiles(BigInteger, "sqlite")
def _bigint_primary_keys_autoincrement(type_, compiler, **kw):
    return "INTEGER"  # SQLite only autoincrements INTEGER PRIMARY KEY, not BIGINT


@pytest_asyncio.fixture
async def adb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        for model in (VisitSession, Visit, VisitEvent):
            await conn.run_sync(model.__table__.create)
    monkeypatch.setattr(tracking_mod.event_batcher, "enabled", False)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _page_view(svc, db, url, referrer, event_type="page_view"):
    # A private IP: the geo lookup answers locally instead of calling an API.
    return await svc.track_event(
        db, ip_address="10.0.0.5", user_agent="Mozilla/5.0 (Macintosh) Chrome/130.0",
        event_type=event_type, page_url=url, referrer=referrer, client_id="cid-1",
    )


@pytest.mark.asyncio
async def test_internal_navigation_keeps_the_entry_source(adb):
    svc = TrackingService()
    await _page_view(svc, adb, "https://www.getmaxim.ai/", "https://www.google.com/")
    await _page_view(svc, adb, "https://www.getmaxim.ai/pricing", "https://www.getmaxim.ai/")
    await _page_view(svc, adb, "https://www.getmaxim.ai/book-a-demo?utm_source=newsletter",
                     "https://www.getmaxim.ai/pricing")

    visits = (await adb.execute(select(Visit).order_by(Visit.id))).scalars().all()
    assert [(v.path, v.source, v.medium) for v in visits] == [
        ("/", "google", "organic"),
        ("/pricing", "google", "organic"),  # used to be source www.getmaxim.ai
        ("/book-a-demo", "newsletter", None),  # explicit UTM parameters still win
    ]
    assert len({v.session_id for v in visits}) == 1
    events = (await adb.execute(select(VisitEvent).order_by(VisitEvent.id))).scalars().all()
    assert [e.source for e in events] == ["google", "google", "newsletter"]


@pytest.mark.asyncio
async def test_old_navigate_events_are_stored_as_navigation(adb):
    svc = TrackingService()
    await _page_view(svc, adb, "https://www.getmaxim.ai/", None)
    await _page_view(svc, adb, "https://www.getmaxim.ai/", None, event_type="navigate")

    event = (await adb.execute(select(VisitEvent).order_by(VisitEvent.id.desc()))).scalars().first()
    assert event.event_type == "navigation"
    assert event.event_data["kind"] == "unload"


# --- /track/event endpoint ---------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    calls = []

    async def fake_track_event(**kwargs):
        calls.append(kwargs)
        return {"event_id": 1, "queued": False}

    async def no_db():
        yield None

    async def allow(*args, **kwargs):
        return True

    monkeypatch.setattr(tracking_api.settings, "rabbitmq_enabled", False)
    monkeypatch.setattr(tracking_api.settings, "tracking_allowed_domains", ALLOWED)
    monkeypatch.setattr(tracking_api.tracking_service, "track_event", fake_track_event)
    monkeypatch.setattr(tracking_api.rate_limiter, "is_allowed", allow)
    app = FastAPI()
    app.include_router(tracking_api.router)
    app.dependency_overrides[get_async_db] = no_db
    test_client = TestClient(app)
    test_client.calls = calls
    return test_client


def test_event_from_allowed_page_is_tracked_and_readable(client):
    resp = client.post("/track/event", json={"event_type": "form_submit", "page_url": "https://docs.getbifrost.ai/x"},
                       headers={"Origin": "https://docs.getbifrost.ai"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://docs.getbifrost.ai"
    assert len(client.calls) == 1


@pytest.mark.parametrize("page_url", ["http://localhost:3002/", "https://docs.modrouter.online/", None])
def test_event_from_other_page_is_dropped(client, page_url):
    resp = client.post("/track/event", json={"event_type": "page_view", "page_url": page_url},
                       headers={"Origin": "https://docs.modrouter.online"})
    assert resp.status_code == 204
    assert "access-control-allow-origin" not in resp.headers
    assert client.calls == []
