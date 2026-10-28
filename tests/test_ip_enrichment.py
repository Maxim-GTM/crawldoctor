"""Unit tests for the ipapi.is enrichment job. No server, Postgres or network needed.

ipapi.is changed its keyless tier on 2026-09-01: `company` became a string, the network flags
went away, and anonymous use is capped at 30 lookups a day per IP, with a 24-hour firewall
block for clients that keep sending after a 429. These tests pin how the job copes with that.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.background.models import BackgroundJobState
from app.models.enrichment import IpEnrichment
from app.services import ip_enrichment as mod
from app.services.ip_enrichment import (
    IpEnrichmentService,
    PermanentLookupError,
    ProviderUnavailable,
    TransientLookupError,
    priority_path_regex,
    retry_wait,
)

KEYED_ANSWER = {
    "ip": "203.0.113.7",
    "is_bogon": False,
    "is_datacenter": False,
    "is_vpn": False,
    "is_proxy": False,
    "is_tor": False,
    "company": {"name": "Acme Corp", "domain": "Acme.com", "type": "business"},
    "location": {"country_code": "DE", "country": "Germany"},
}
# The keyless answer, as returned for 8.8.8.8 on 2026-10-28.
ANONYMOUS_ANSWER = {
    "ip": "8.8.8.8",
    "is_bogon": False,
    "company": "Google LLC",
    "asn": "AS15169 Google LLC",
    "city": "Mountain View",
    "region": "California",
    "country": "United States",
    "lat": 37.38605,
    "lon": -122.08385,
    "timezone": "America/Los_Angeles",
    "docs": "https://ipapi.is/free-tier.html?ref=api",
}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_normalize_keyed_answer():
    data = IpEnrichmentService()._normalize("203.0.113.7", KEYED_ANSWER, None, None)
    assert data["company_name"] == "Acme Corp"
    assert data["company_domain"] == "acme.com"
    assert data["company_type"] == "business"
    assert data["country"] == "de"
    assert data["is_vpn"] is False
    assert data["status"] == "success"


def test_normalize_anonymous_answer_with_string_company():
    # The old code called company.get("domain") on this string: "'str' object has no attribute 'get'".
    data = IpEnrichmentService()._normalize("8.8.8.8", ANONYMOUS_ANSWER, None, None)
    assert data["company_name"] == "Google LLC"
    assert data["company_domain"] is None
    assert data["country"] is None  # a full country name doesn't fit the 2-letter column
    assert data["is_datacenter"] is None
    assert data["status"] == "success"


def test_call_api_sends_key_in_body_not_url(monkeypatch):
    monkeypatch.setattr(mod.settings, "ip_enrichment_api_key", "secret-key")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=KEYED_ANSWER)

    raw = IpEnrichmentService()._call_api("203.0.113.7", _client(handler))
    assert raw["company"]["name"] == "Acme Corp"
    assert seen["body"] == {"q": "203.0.113.7", "key": "secret-key"}
    assert "secret-key" not in seen["url"]


@pytest.mark.parametrize("status, error", [
    (500, TransientLookupError),
    (502, TransientLookupError),
    (400, PermanentLookupError),
    (404, PermanentLookupError),
])
def test_call_api_maps_status(status, error):
    with pytest.raises(error):
        IpEnrichmentService()._call_api("203.0.113.7", _client(lambda r: httpx.Response(status, text="x")))


def test_call_api_429_pauses_until_utc_midnight():
    with pytest.raises(ProviderUnavailable) as info:
        IpEnrichmentService()._call_api("203.0.113.7", _client(lambda r: httpx.Response(429, text="quota")))
    until = info.value.pause_until
    assert until > datetime.now(timezone.utc)
    assert (until.hour, until.minute, until.second) == (0, 0, 0)
    assert not info.value.record_ip


def test_call_api_refused_connection_pauses_a_day():
    def handler(request):
        raise httpx.ConnectError("[Errno 111] Connection refused")

    with pytest.raises(ProviderUnavailable) as info:
        IpEnrichmentService()._call_api("203.0.113.7", _client(handler))
    assert info.value.pause_until - datetime.now(timezone.utc) > timedelta(hours=23)


def test_call_api_403_stops_batch_and_records_ip():
    with pytest.raises(ProviderUnavailable) as info:
        IpEnrichmentService()._call_api("203.0.113.7", _client(lambda r: httpx.Response(403, text="")))
    assert info.value.record_ip
    assert info.value.pause_until is None


def test_call_api_unexpected_answer_is_transient():
    with pytest.raises(TransientLookupError):
        IpEnrichmentService()._call_api("203.0.113.7", _client(lambda r: httpx.Response(200, json="nope")))


def test_retry_wait_doubles_and_caps(monkeypatch):
    monkeypatch.setattr(mod.settings, "ip_enrichment_retry_base_minutes", 60)
    assert retry_wait(1) == timedelta(hours=1)
    assert retry_wait(2) == timedelta(hours=2)
    assert retry_wait(4) == timedelta(hours=8)
    assert retry_wait(2246) == timedelta(days=7)


def test_priority_regex_matches_path_segments():
    pattern = re.compile(priority_path_regex(["/pricing", "/enterprise", "/book-a-demo", "/contact"]))
    for path in ["/pricing", "/bifrost/pricing", "/enterprise", "/enterprise/", "/book-a-demo", "/contact"]:
        assert pattern.search(path), path
    for path in ["/", "/pricing-calculator", "/blog/enterprise-ai", "/articles/contact-us-today", ""]:
        assert not pattern.search(path), path


# --- run_batch against an in-memory database -------------------------------------------------

class _FakeService(IpEnrichmentService):
    def __init__(self, handler, candidates):
        self.handler = handler
        self.candidates = candidates
        self.calls = []

    def _http_client(self):
        def record(request):
            self.calls.append(json.loads(request.content)["q"])
            return self.handler(request)
        return _client(record)

    def _get_candidates(self, db, batch_size):
        return self.candidates[:batch_size]


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    IpEnrichment.__table__.create(engine)
    BackgroundJobState.__table__.create(engine)
    monkeypatch.setattr(mod.settings, "ip_enrichment_enabled", True)
    monkeypatch.setattr(mod.settings, "ip_enrichment_max_rps", 1000.0)
    monkeypatch.setattr(mod.settings, "ip_enrichment_api_key", "k")
    monkeypatch.setattr(mod.settings, "ip_enrichment_daily_limit", 1000)
    monkeypatch.setattr(mod.settings, "ip_enrichment_retry_base_minutes", 60)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _candidates(*ips):
    seen = datetime(2026, 10, 27, tzinfo=timezone.utc)
    return [{"ip": ip, "first_seen_at": seen, "last_seen_at": seen} for ip in ips]


def test_batch_stops_at_429_and_pauses(db):
    def handler(request):
        ip = json.loads(request.content)["q"]
        if ip == "198.51.100.1":
            return httpx.Response(200, json={**KEYED_ANSWER, "ip": ip})
        return httpx.Response(429, text="quota")

    service = _FakeService(handler, _candidates("198.51.100.1", "198.51.100.2", "198.51.100.3"))
    stats = service.run_batch(db)

    assert stats["success"] == 1
    assert stats["stopped"].startswith("HTTP 429")
    assert service.calls == ["198.51.100.1", "198.51.100.2"]  # nothing sent after the 429
    assert db.get(IpEnrichment, "198.51.100.1").status == "success"
    assert db.get(IpEnrichment, "198.51.100.2") is None  # the quota isn't this IP's fault
    assert db.get(BackgroundJobState, mod._PAUSE_KEY) is not None

    again = _FakeService(handler, _candidates("198.51.100.3"))
    assert again.run_batch(db)["reason"] == "paused"
    assert again.calls == []


def test_refused_connection_records_nothing(db):
    def handler(request):
        raise httpx.ConnectError("[Errno 111] Connection refused")

    service = _FakeService(handler, _candidates("198.51.100.1", "198.51.100.2"))
    stats = service.run_batch(db)

    assert stats["stopped"].startswith("connect failed")
    assert service.calls == ["198.51.100.1"]
    assert db.query(IpEnrichment).count() == 0


def test_transient_errors_back_off_instead_of_failing(db):
    handler = lambda request: httpx.Response(503, text="busy")
    for expected_attempts in (1, 2, 3, 4):
        _FakeService(handler, _candidates("198.51.100.1")).run_batch(db)
        row = db.get(IpEnrichment, "198.51.100.1")
        assert row.status == "error"  # never 'failed' for a transient error
        assert row.attempt_count == expected_attempts


def test_rows_wrongly_marked_failed_restart_their_count(db):
    db.add(IpEnrichment(ip="198.51.100.1", status="failed", error_code="transient",
                        error_message="[Errno 111] Connection refused", attempt_count=2246))
    db.commit()

    _FakeService(lambda r: httpx.Response(503, text="busy"), _candidates("198.51.100.1")).run_batch(db)
    row = db.get(IpEnrichment, "198.51.100.1")
    assert (row.status, row.attempt_count) == ("error", 1)

    _FakeService(lambda r: httpx.Response(200, json=ANONYMOUS_ANSWER), _candidates("198.51.100.1")).run_batch(db)
    row = db.get(IpEnrichment, "198.51.100.1")
    assert (row.status, row.attempt_count, row.company_name) == ("success", 0, "Google LLC")


def test_failed_refresh_keeps_earlier_company_data(db):
    old = datetime.now(timezone.utc) - timedelta(days=40)
    db.add(IpEnrichment(ip="198.51.100.1", status="success", company_name="Acme Corp",
                        company_domain="acme.com", attempt_count=0, enriched_at=old, ttl_expires_at=old))
    db.commit()

    _FakeService(lambda r: httpx.Response(503, text="busy"), _candidates("198.51.100.1")).run_batch(db)
    row = db.get(IpEnrichment, "198.51.100.1")
    assert (row.status, row.company_name, row.company_domain) == ("success", "Acme Corp", "acme.com")
    assert row.attempt_count == 1
    ttl = row.ttl_expires_at.replace(tzinfo=timezone.utc)
    assert timedelta(minutes=59) < ttl - datetime.now(timezone.utc) <= timedelta(hours=1)


def test_permanent_error_marks_failed(db):
    _FakeService(lambda r: httpx.Response(400, text="bad ip"), _candidates("198.51.100.1")).run_batch(db)
    row = db.get(IpEnrichment, "198.51.100.1")
    assert (row.status, row.error_code) == ("failed", "api_4xx")


def test_daily_limit_without_key(db, monkeypatch):
    monkeypatch.setattr(mod.settings, "ip_enrichment_api_key", None)
    now = datetime.now(timezone.utc)
    for i in range(24):
        db.add(IpEnrichment(ip=f"192.0.2.{i}", status="success", attempt_count=0, enriched_at=now))
    db.commit()

    service = _FakeService(lambda r: httpx.Response(200, json=ANONYMOUS_ANSWER),
                           _candidates("198.51.100.1", "198.51.100.2", "198.51.100.3"))
    stats = service.run_batch(db)
    assert service.calls == ["198.51.100.1"]  # 25 a day without a key; 24 were used
    assert stats["success"] == 1
    assert service.run_batch(db)["reason"] == "daily limit reached"
