"""Dashboard filters and reports: the new optional params on the list endpoints, the
report endpoints, and the channel mapping.

No server or Postgres needed (in-memory SQLite):
    pytest tests/test_filters_and_reports.py
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.analytics import router
from app.database import Base, get_db
from app.models.enrichment import IpEnrichment
from app.models.summary import JourneySummary, LeadSummary
from app.models.visit import Visit, VisitEvent, VisitSession
from app.services.channels import ai_assistant, classify_channel
from app.services.reports import company_from_form, is_junk_domain, tracking_status
from app.utils.auth import get_current_user

NOW = datetime.now(timezone.utc).replace(microsecond=0)
TODAY = NOW.strftime("%Y-%m-%d")
WEEK_AGO = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")


# =====================================================================
# Pure helpers
# =====================================================================

@pytest.mark.parametrize("source,medium,channel", [
    (None, None, "Direct"),
    ("", "", "Direct"),
    ("direct", None, "Direct"),
    ("www.google.com", None, "Search"),
    ("www.google.com.hk", None, "Search"),
    ("google", "organic", "Search"),
    ("duckduckgo.com", None, "Search"),
    ("google", "cpc", "Paid"),
    ("linkedin", "paid_social", "Paid"),
    ("chatgpt.com", None, "AI assistants"),
    ("gemini.google.com", None, "AI assistants"),
    ("www.perplexity.ai", None, "AI assistants"),
    ("claude.ai", None, "AI assistants"),
    ("www.getmaxim.ai", None, "Internal"),
    ("app.getmaxim.ai", None, "Internal"),
    ("docs.getbifrost.ai", None, "Internal"),
    ("bifrost_docs", None, "Internal"),
    ("www.linkedin.com", None, "Social"),
    ("t.co", None, "Social"),
    ("reddit post", None, "Social"),
    ("github.com", None, "Referral"),
    ("newsletter", "email", "Referral"),
    # Tags our own CTAs use, as seen in production
    ("google", "aimax", "Paid"),
    ("chatgpt", "ads", "Paid"),
    ("", "bifrost_footer", "Internal"),
    ("www.google.com", "bifrost_footer", "Internal"),
    ("bifrost_docs", "bifrost_navbar", "Internal"),
    ("articles_failover-routing-strategies", "cta_modal", "Internal"),
    ("articles", "cta_banner_prompt_engineering", "Internal"),
    ("bifrost_model-library_compare_openai_gpt-5", "cta_modal", "Internal"),
    ("blog", "sidebar_widget", "Internal"),
    ("content", "social", "Social"),
    ("aiagenttools", "directory", "Referral"),
])
def test_classify_channel(source, medium, channel):
    assert classify_channel(source, medium) == channel


def test_ai_assistant_names():
    assert ai_assistant("ChatGPT.com") == "ChatGPT"
    assert ai_assistant("gemini") == "Gemini"
    assert ai_assistant("www.google.com") is None


@pytest.mark.parametrize("domain,junk", [
    ("localhost:3000", True), ("localhost", True), ("www.getmaxim.ai:8443", True), ("192.168.1.3:3000", True),
    ("10.0.0.1", True), ("gtm-msr.appspot.com", True), ("docs.modrouter.online", True), ("", True), (None, True),
    ("screenshot.framer.invalid", True), ("www.getmaxim.ai", False), ("docs.getbifrost.ai", False),
])
def test_is_junk_domain(domain, junk):
    assert is_junk_domain(domain) is junk


def test_tracking_status():
    assert tracking_status(NOW - timedelta(hours=2), NOW) == "live"
    assert tracking_status(NOW - timedelta(days=3), NOW) == "quiet"
    assert tracking_status(NOW - timedelta(days=40), NOW) == "stale"
    assert tracking_status(None, NOW) == "stale"
    assert tracking_status((NOW - timedelta(hours=1)).replace(tzinfo=None), NOW) == "live"


def test_company_from_form():
    assert company_from_form(json.dumps({"Email": "a@acme.dev", "Company": "Acme"})) == "Acme"
    assert company_from_form(json.dumps({"company_name": "Globex "})) == "Globex"
    # "Company size" is not a company
    assert company_from_form(json.dumps({"Company size": "1-10"})) is None
    assert company_from_form("not json") is None
    assert company_from_form(None) is None


# =====================================================================
# API against a seeded SQLite database
# =====================================================================

def _ts(**delta):
    return NOW - timedelta(**delta)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [VisitSession.__table__, Visit.__table__, VisitEvent.__table__, LeadSummary.__table__,
              JourneySummary.__table__, IpEnrichment.__table__]
    Base.metadata.create_all(engine, tables=tables)
    Session = sessionmaker(bind=engine, autoflush=False)
    db = Session()

    sessions = [
        # id, client, ip, country, entry referrer, last active
        ("s-human-us", "cid-alice", "1.1.1.1", "US", "www.google.com", _ts(hours=1)),
        ("s-bot", "cid-googlebot", "9.9.9.9", "US", None, _ts(hours=2)),
        ("s-human-in", "cid-bob", "2.2.2.2", "IN", "chatgpt.com", _ts(days=2)),
        ("s-old", "cid-carol", "3.3.3.3", "GB", None, _ts(days=20)),
        ("s-anon", None, "4.4.4.4", "DE", None, _ts(hours=3)),
    ]
    for sid, cid, ip, country, ref, last in sessions:
        db.add(VisitSession(id=sid, client_id=cid, ip_address=ip, country=country, entry_referrer_domain=ref,
                            first_visit=last - timedelta(minutes=10), last_visit=last))

    visits = [
        # id, session, client, crawler, is_bot, domain, path, source, medium, country, ip, when
        (1, "s-human-us", "cid-alice", None, False, "www.getmaxim.ai", "/pricing", "www.google.com", None, "US", "1.1.1.1", _ts(hours=1)),
        (2, "s-human-us", "cid-alice", None, False, "www.getmaxim.ai", "/book-a-demo", "www.getmaxim.ai", None, "US", "1.1.1.1", _ts(minutes=50)),
        (3, "s-bot", "cid-googlebot", "GoogleBot", True, "www.getmaxim.ai", "/pricing", None, None, "US", "9.9.9.9", _ts(hours=2)),
        (4, "s-human-in", "cid-bob", None, False, "www.getmaxim.ai", "/articles/gateways", "chatgpt.com", None, "IN", "2.2.2.2", _ts(days=2)),
        (5, "s-human-in", "cid-bob", None, False, "www.getmaxim.ai", "/pricing", "chatgpt.com", None, "IN", "2.2.2.2", _ts(days=2, minutes=-5)),
        (6, "s-old", "cid-carol", None, False, "docs.getbifrost.ai", "/quickstart", "google", "cpc", "GB", "3.3.3.3", _ts(days=20)),
        (7, "s-anon", None, None, False, "localhost:3000", "/", None, None, "DE", "4.4.4.4", _ts(hours=3)),
    ]
    for vid, sid, cid, crawler, bot, domain, path, source, medium, country, ip, when in visits:
        db.add(Visit(id=vid, session_id=sid, client_id=cid, crawler_type=crawler, is_bot=bot, page_domain=domain,
                     path=path, page_url=f"https://{domain}{path}", source=source, medium=medium, country=country,
                     ip_address=ip, user_agent="Mozilla/5.0", timestamp=when, tracking_id="maxim-site"))

    db.add(VisitEvent(id=100, session_id="s-bot", visit_id=3, client_id="cid-googlebot", event_type="page_view",
                      page_url="https://www.getmaxim.ai/pricing", timestamp=_ts(hours=2)))
    db.add(VisitEvent(id=101, session_id="s-human-us", visit_id=2, client_id="cid-alice", event_type="click",
                      page_url="https://www.getmaxim.ai/book-a-demo", timestamp=_ts(minutes=49)))

    db.add(LeadSummary(client_id="cid-alice", email="alice@acme.dev", name="Alice Example", captured_path="/book-a-demo",
                       captured_at=_ts(minutes=45), last_seen=_ts(minutes=45), source="www.google.com",
                       captured_data=json.dumps({"Email": "alice@acme.dev", "Company": "Acme Robotics"})))
    db.add(LeadSummary(client_id="cid-bob", email="bob@globex.io", name="Bob", captured_path="/enterprise",
                       captured_at=_ts(days=2), last_seen=_ts(days=2), source="chatgpt.com",
                       captured_data=json.dumps({"email": "bob@globex.io", "Are you using an LLM Gateway today?": "No"})))
    db.add(LeadSummary(client_id="cid-dan", email="dan@initech.com", name="Dan", captured_path="/book-a-demo",
                       captured_at=_ts(days=1), last_seen=_ts(days=1), source=None, captured_data="{}"))
    db.add(JourneySummary(client_id="cid-alice", email="alice@acme.dev", name="Alice Example", has_captured_data=1,
                          form_fill_count=2, visit_count=2, first_seen=_ts(hours=1), last_seen=_ts(minutes=45),
                          source="www.google.com", campaign=None))
    db.add(JourneySummary(client_id="cid-bob", email="bob@globex.io", name="Bob", has_captured_data=1,
                          form_fill_count=1, visit_count=9, first_seen=_ts(days=3), last_seen=_ts(days=2),
                          source="chatgpt.com", campaign="launch"))

    for ip, domain, ctype, flags in [
        ("1.1.1.1", "acme.dev", "business", {}),
        ("2.2.2.2", "jio.com", "isp", {}),
        ("3.3.3.3", "aws.amazon.com", "business", {"is_datacenter": True}),
    ]:
        db.add(IpEnrichment(ip=ip, company_domain=domain, company_name=domain.split(".")[0].title(), company_type=ctype,
                            status="success", **flags))
    # A lookup made without an API key: a name, and nothing to tell an ISP from a company
    db.add(IpEnrichment(ip="4.4.4.4", company_name="Deutsche Telekom", status="success"))
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as c:
        yield c
    db.close()


def get(client, endpoint, **params):
    r = client.get(f"/api/v1/analytics{endpoint}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def ids(rows, key="id"):
    return sorted(r[key] for r in rows)


def test_recent_filters(client):
    base = {"start_date": WEEK_AGO, "end_date": TODAY}
    assert ids(get(client, "/recent", **base)["visits"]) == [1, 2, 3, 4, 5, 7]
    assert ids(get(client, "/recent", visitor="human", **base)["visits"]) == [1, 2, 4, 5, 7]
    assert ids(get(client, "/recent", visitor="bot", **base)["visits"]) == [3]
    assert ids(get(client, "/recent", visitor="GoogleBot", **base)["visits"]) == [3]
    assert ids(get(client, "/recent", path="PRIC", **base)["visits"]) == [1, 3, 5]
    assert ids(get(client, "/recent", source="chatgpt", **base)["visits"]) == [4, 5]
    assert ids(get(client, "/recent", country="in", **base)["visits"]) == [4, 5]
    assert ids(get(client, "/recent", domain="localhost:3000", **base)["visits"]) == [7]
    data = get(client, "/recent", visitor="human", path="/pricing", **base)
    assert ids(data["visits"]) == [1, 5] and data["total_count"] == 2


def test_recent_path_wildcards_are_literal(client):
    # "_" and "%" in a typed path match themselves, not any character
    assert get(client, "/recent", path="pr_cing", start_date=WEEK_AGO, end_date=TODAY)["visits"] == []


def test_session_filters(client):
    rng = {"start_date": WEEK_AGO, "end_date": TODAY}
    all_ids = ids(get(client, "/sessions", **rng)["sessions"], "session_id")
    assert all_ids == ["s-anon", "s-bot", "s-human-in", "s-human-us"]  # s-old is outside the range
    assert ids(get(client, "/sessions", visitor="bot", **rng)["sessions"], "session_id") == ["s-bot"]
    assert ids(get(client, "/sessions", visitor="human", **rng)["sessions"], "session_id") == ["s-anon", "s-human-in", "s-human-us"]
    assert ids(get(client, "/sessions", country="us", **rng)["sessions"], "session_id") == ["s-bot", "s-human-us"]
    assert ids(get(client, "/sessions", referrer="google", **rng)["sessions"], "session_id") == ["s-human-us"]
    assert ids(get(client, "/sessions", referrer="direct", **rng)["sessions"], "session_id") == ["s-anon", "s-bot"]
    assert ids(get(client, "/sessions", has_client_id="false", **rng)["sessions"], "session_id") == ["s-anon"]
    data = get(client, "/sessions", has_client_id="true", visitor="human", **rng)
    assert ids(data["sessions"], "session_id") == ["s-human-in", "s-human-us"] and data["total_count"] == 2
    # Without filters the old behaviour stands: every session, newest first
    assert get(client, "/sessions")["total_count"] == 5


def test_session_rejects_unknown_visitor(client):
    assert client.get("/api/v1/analytics/sessions", params={"visitor": "robot"}).status_code == 422


def test_user_filters(client):
    rng = {"start_date": WEEK_AGO, "end_date": TODAY}
    assert ids(get(client, "/users", **rng)["users"], "client_id") == ["cid-alice", "cid-bob", "cid-googlebot"]
    assert ids(get(client, "/users", visitor="human", **rng)["users"], "client_id") == ["cid-alice", "cid-bob"]
    assert ids(get(client, "/users", visitor="bot", **rng)["users"], "client_id") == ["cid-googlebot"]
    assert ids(get(client, "/users", converted="true", **rng)["users"], "client_id") == ["cid-alice", "cid-bob"]
    assert ids(get(client, "/users", source="chatgpt", **rng)["users"], "client_id") == ["cid-bob"]
    by_email = get(client, "/users", q="ALICE@acme", **rng)["users"]
    assert [u["client_id"] for u in by_email] == ["cid-alice"]
    assert by_email[0]["email"] == "alice@acme.dev"
    # Stats cover all of a person's visits, not just those in the range
    assert by_email[0]["visit_count"] == 2 and by_email[0]["session_count"] == 1
    assert [u["client_id"] for u in get(client, "/users", q="cid-go", **rng)["users"]] == ["cid-googlebot"]
    # Carol was last active 20 days ago
    assert get(client, "/users", q="cid-carol", **rng)["users"] == []
    newest_first = get(client, "/users", visitor="human", **rng)["users"]
    assert [u["client_id"] for u in newest_first] == ["cid-alice", "cid-bob"]


def test_lead_search_and_company(client):
    rng = {"start_date": WEEK_AGO, "end_date": TODAY}
    assert ids(get(client, "/leads", q="robotics", **rng)["leads"], "client_id") == ["cid-alice"]
    assert ids(get(client, "/leads", q="globex", **rng)["leads"], "client_id") == ["cid-bob"]
    assert ids(get(client, "/leads", q="dan", **rng)["leads"], "client_id") == ["cid-dan"]
    lead = get(client, "/leads", q="alice", **rng)["leads"][0]
    assert lead["company"] == "Acme Robotics"
    # Words in the form's questions don't match; the answers do
    assert get(client, "/leads", q="gateway", **rng)["leads"] == []
    assert get(client, "/leads", q="gateway", **rng)["total_count"] == 0
    assert ids(get(client, "/leads", q="robot", limit=1, **rng)["leads"], "client_id") == ["cid-alice"]


def test_search_ignores_form_questions(client):
    assert get(client, "/search", q="gateway")["results"] == []


def test_lead_path_facet(client):
    values = get(client, "/facets", field="leads.captured_path", start_date=WEEK_AGO, end_date=TODAY)["values"]
    assert values == [{"value": "/book-a-demo", "count": 2}, {"value": "/enterprise", "count": 1}]


def test_facet_rejects_unknown_field(client):
    assert client.get("/api/v1/analytics/facets", params={"field": "visits.ip_address"}).status_code == 422


def test_visit_source_facet_humans_only(client):
    values = get(client, "/facets", field="visits.source", humans_only="true", start_date=WEEK_AGO, end_date=TODAY)["values"]
    assert {v["value"]: v["count"] for v in values} == {"chatgpt.com": 2, "www.google.com": 1, "www.getmaxim.ai": 1}


def test_journey_filters_and_sort(client):
    rng = {"start_date": WEEK_AGO, "end_date": TODAY}
    assert ids(get(client, "/journeys", source="CHATGPT.COM", **rng)["journeys"], "client_id") == ["cid-bob"]
    assert ids(get(client, "/journeys", campaign="none", **rng)["journeys"], "client_id") == ["cid-alice"]
    by_views = get(client, "/journeys", sort="visit_count", order="desc", **rng)["journeys"]
    assert [j["client_id"] for j in by_views] == ["cid-bob", "cid-alice"]
    by_first = get(client, "/journeys", sort="first_seen", order="asc", **rng)["journeys"]
    assert [j["client_id"] for j in by_first] == ["cid-bob", "cid-alice"]
    assert client.get("/api/v1/analytics/journeys", params={"sort": "email"}).status_code == 422


def test_journey_export_uses_filters(client):
    r = client.get("/api/v1/analytics/journeys/export", params={"source": "chatgpt.com", "start_date": WEEK_AGO, "end_date": TODAY})
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert len(lines) == 2 and "cid-bob" in lines[1]


def test_timeseries(client):
    series = get(client, "/timeseries", start_date=WEEK_AGO, end_date=TODAY)["series"]
    totals = {}
    for row in series:
        totals[row["name"]] = totals.get(row["name"], 0) + row["count"]
    assert totals == {"Human": 5, "GoogleBot": 1}
    assert all(len(row["day"]) == 10 for row in series)


def test_top_pages(client):
    pages = get(client, "/top-pages", start_date=WEEK_AGO, end_date=TODAY)["pages"]
    top = pages[0]
    assert (top["domain"], top["path"], top["views"], top["visitors"]) == ("www.getmaxim.ai", "/pricing", 2, 2)
    with_bots = get(client, "/top-pages", humans_only="false", start_date=WEEK_AGO, end_date=TODAY)["pages"]
    assert with_bots[0]["views"] == 3


def test_channels(client):
    channels = {c["channel"]: c for c in get(client, "/channels", start_date=WEEK_AGO, end_date=TODAY)["channels"]}
    assert channels["AI assistants"]["views"] == 2 and channels["AI assistants"]["visitors"] == 1
    assert channels["AI assistants"]["leads"] == 1
    assert channels["Search"]["views"] == 1 and channels["Search"]["leads"] == 1
    assert channels["Internal"]["views"] == 1
    assert channels["Direct"]["views"] == 1 and channels["Direct"]["leads"] == 1
    assert "Paid" not in channels  # the cpc visit is 20 days old


def test_ai_referrals(client):
    data = get(client, "/ai-referrals", start_date=WEEK_AGO, end_date=TODAY)
    assert data["views"] == 2 and data["visitors"] == 1
    assert data["assistants"] == [{"assistant": "ChatGPT", "views": 2, "visitors": 1}]
    assert {p["path"] for p in data["pages"]} == {"/articles/gateways", "/pricing"}
    assert [(l["client_id"], l["assistant"]) for l in data["leads"]] == [("cid-bob", "ChatGPT")]


def test_companies_skip_isps_and_datacenters(client):
    data = get(client, "/companies", start_date="2000-01-01", end_date=TODAY)
    assert [c["domain"] for c in data["companies"]] == ["acme.dev"]
    acme = data["companies"][0]
    assert acme["views"] == 2 and acme["sessions"] == 1
    assert {p["path"] for p in acme["pages"]} == {"/pricing", "/book-a-demo"}
    # Four human sessions in all time, all looked up; one lookup is a bare name; one is a real company
    assert data["coverage"] == {"human_sessions": 4, "enriched_sessions": 4, "detailed_sessions": 3, "company_sessions": 1}


def test_tracking_health(client):
    data = get(client, "/tracking-health")
    sites = {s["domain"]: s for s in data["sites"]}
    assert "localhost:3000" not in sites and data["hidden_domains"] == 1
    assert sites["www.getmaxim.ai"]["status"] == "live" and sites["www.getmaxim.ai"]["ours"]
    assert sites["www.getmaxim.ai"]["views_24h"] == 3
    assert sites["docs.getbifrost.ai"]["status"] == "stale"
    assert sites["www.getmaxim.ai"]["tracking_ids"][0]["tracking_id"] == "maxim-site"


def test_search(client):
    def kinds(q):
        return [(r["kind"], r["id"]) for r in get(client, "/search", q=q)["results"]]

    assert kinds("alice@acme.dev") == [("journey", "cid-alice")]
    assert kinds("s-human-in") == [("session", "s-human-in")]
    assert ("journey", "cid-bob") in kinds("cid-bob")
    assert kinds("https://www.getmaxim.ai/pricing?cd_cid=cid-alice") == [
        ("journey", "cid-alice"), ("page", "https://www.getmaxim.ai/pricing?cd_cid=cid-alice")]
    page = get(client, "/search", q="www.getmaxim.ai/pricing")["results"][0]
    assert (page["kind"], page["domain"], page["path"]) == ("page", "www.getmaxim.ai", "/pricing")
    assert kinds("/pricing")[0][0] == "page"
    assert kinds("Robotics") == [("journey", "cid-alice")]
    assert kinds("zz") == []


def test_live_events_say_which_are_bots(client):
    events = {e["id"]: e for e in get(client, "/live-events")["events"]}
    assert events[100]["is_bot"] is True and events[100]["crawler_type"] == "GoogleBot"
    assert events[101]["is_bot"] is False
