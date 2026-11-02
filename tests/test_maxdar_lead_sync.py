"""Leads the tracker missed, copied from maxdar: sync_maxdar_leads and recompute_journey. No server or Postgres."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.background.models import BackgroundJobState
from app.background.jobs import sync_maxdar_leads as sync_mod
from app.background.jobs.recompute_journey import RecomputeJourney
from app.background.jobs.sync_maxdar_leads import SyncMaxdarLeads
from app.models.summary import JourneyFormFill, JourneySummary, LeadSummary
from app.models.visit import Visit, VisitEvent, VisitSession
from app.services.lead_classification import DEMO_BIFROST, ENTERPRISE

DEMO_PAGE = "https://www.getmaxim.ai/book-a-demo"
SUBMITTED = datetime(2026, 11, 2, 4, 19, 40, tzinfo=timezone.utc)


@compiles(BigInteger, "sqlite")
def _bigint_primary_keys_autoincrement(type_, compiler, **kw):
    return "INTEGER"  # SQLite only autoincrements INTEGER PRIMARY KEY, not BIGINT


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for model in (VisitSession, Visit, VisitEvent, JourneySummary, JourneyFormFill, LeadSummary, BackgroundJobState):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _row(id=2807, category="Bifrost Demos", email="cmalson@uchicago.edu", at=SUBMITTED):
    return {"id": id, "category": category, "booked_email": email, "first_name": "Clinton",
            "last_name": "Malson", "company_size": "101-500", "company_location": "North America",
            "created_at": at}


@pytest.fixture
def maxdar(monkeypatch):
    """maxdar's events table: the rows fetch_submissions returns, and the windows it was asked for."""
    state = {"rows": [], "calls": []}

    def fake_fetch(since, until):
        state["calls"].append((since, until))
        return state["rows"]

    monkeypatch.setattr(sync_mod.settings, "maxdar_database_url", "postgresql://maxdar.example/neondb")
    monkeypatch.setattr(sync_mod, "fetch_submissions", fake_fetch)
    return state


def _tracker_fill(db, client_id, email, at):
    db.add(VisitEvent(client_id=client_id, event_type="form_submit", page_url=DEMO_PAGE, path="/book-a-demo",
                      timestamp=at, event_data={"form_values": {"FirstName": "Clinton", "Email": email},
                                                "tracking_method": "javascript"}))
    db.commit()


def _sync(db):
    job = SyncMaxdarLeads()
    payloads = job.sweep(db, since=SUBMITTED - timedelta(minutes=5))
    for payload in payloads:
        job.handle(db, payload)
    return payloads


def test_missed_submission_becomes_a_lead(db, maxdar):
    maxdar["rows"] = [_row()]

    [payload] = _sync(db)

    lead = db.get(LeadSummary, payload["client_id"])
    assert payload["client_id"].startswith("lead-")
    assert (lead.email, lead.name, lead.lead_type) == ("cmalson@uchicago.edu", "Clinton", DEMO_BIFROST)
    assert (lead.captured_path, lead.captured_at.replace(tzinfo=timezone.utc)) == ("/book-a-demo", SUBMITTED)
    event = db.query(VisitEvent).one()
    assert event.event_data["tracking_method"] == "server"
    assert event.event_data["origin"] == "maxdar:events:2807"


def test_enterprise_request_is_an_enterprise_lead(db, maxdar):
    maxdar["rows"] = [_row(category="Enterprise License Requests")]

    [payload] = _sync(db)

    lead = db.get(LeadSummary, payload["client_id"])
    assert (lead.lead_type, lead.captured_path) == (ENTERPRISE, "/enterprise")


def test_submission_the_tracker_recorded_is_left_alone(db, maxdar):
    _tracker_fill(db, "cid-1", "CMalson@uchicago.edu", SUBMITTED - timedelta(seconds=2))
    maxdar["rows"] = [_row()]

    assert _sync(db) == []
    assert db.query(VisitEvent).count() == 1


def test_tracker_fill_hours_apart_is_another_submission(db, maxdar):
    _tracker_fill(db, "cid-1", "cmalson@uchicago.edu", SUBMITTED - timedelta(hours=3))
    maxdar["rows"] = [_row()]

    assert len(_sync(db)) == 1
    assert db.query(VisitEvent).count() == 2


def test_submission_joins_an_existing_lead(db, maxdar):
    db.add(LeadSummary(client_id="cid-old", email="CMalson@UChicago.edu", last_seen=SUBMITTED - timedelta(days=30)))
    db.commit()
    maxdar["rows"] = [_row()]

    assert _sync(db) == [{"client_id": "cid-old"}]


def test_one_client_per_email_for_blocked_visitors(db, maxdar):
    maxdar["rows"] = [_row(id=1), _row(id=2, category="Enterprise License Requests", at=SUBMITTED + timedelta(hours=1)),
                      _row(id=3, email="pritesh.jain@krazybee.com")]

    payloads = _sync(db)

    assert len(payloads) == 2
    assert db.query(JourneyFormFill).count() == 3
    lead = db.query(LeadSummary).filter_by(email="cmalson@uchicago.edu").one()
    assert lead.lead_type == ENTERPRISE  # the most valuable of its two requests


def test_rows_read_again_are_copied_once(db, maxdar):
    maxdar["rows"] = [_row()]
    _sync(db)

    assert _sync(db) == []
    assert db.query(VisitEvent).count() == 1


def test_row_without_an_email_is_skipped(db, maxdar):
    maxdar["rows"] = [_row(email="not an email"), _row(id=2, email=None)]

    assert _sync(db) == []
    assert db.query(VisitEvent).count() == 0


def _utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def test_first_read_goes_back_the_backfill_window(db, maxdar):
    SyncMaxdarLeads().sweep(db, since=datetime.now(timezone.utc) - timedelta(minutes=5))

    [(read_from, read_until)] = maxdar["calls"]
    now = datetime.now(timezone.utc)
    assert now - read_from >= timedelta(days=sync_mod.settings.summary_backfill_days)
    assert now - read_until >= timedelta(minutes=2)  # the tracker's own copy may still be on its way


def test_next_read_starts_before_where_the_last_one_ended(db, maxdar):
    job = SyncMaxdarLeads()
    job.sweep(db, since=SUBMITTED)
    job.sweep(db, since=SUBMITTED)

    [(_, first_until), (second_from, _)] = maxdar["calls"]
    assert _utc(second_from) == _utc(first_until) - timedelta(minutes=15)


def test_url_set_after_the_deploy_still_backfills(db, maxdar, monkeypatch):
    # The scheduler's watermark moves on every sweep, also while the job is off; the cursor doesn't.
    monkeypatch.setattr(sync_mod.settings, "maxdar_database_url", None)
    for _ in range(3):
        assert SyncMaxdarLeads().sweep(db, since=SUBMITTED) == []
    assert maxdar["calls"] == []
    assert db.get(BackgroundJobState, "sync_maxdar_leads:read_until") is None

    monkeypatch.setattr(sync_mod.settings, "maxdar_database_url", "postgresql://maxdar.example/neondb")
    maxdar["rows"] = [_row()]
    assert len(SyncMaxdarLeads().sweep(db, since=datetime.now(timezone.utc))) == 1
    [(read_from, _)] = maxdar["calls"]
    assert datetime.now(timezone.utc) - read_from >= timedelta(days=sync_mod.settings.summary_backfill_days)


def test_failed_read_keeps_the_cursor(db, maxdar, monkeypatch):
    def unreachable(since, until):
        raise ConnectionError("maxdar is down")

    monkeypatch.setattr(sync_mod, "fetch_submissions", unreachable)
    with pytest.raises(ConnectionError):
        SyncMaxdarLeads().sweep(db, since=SUBMITTED)
    db.rollback()

    assert db.get(BackgroundJobState, "sync_maxdar_leads:read_until") is None


# --- recompute_journey with copied fills ---------------------------------------------------------

def _fill(db, client_id, method, ts, email="jane@acme.com"):
    db.add(VisitEvent(client_id=client_id, event_type="form_submit", page_url=DEMO_PAGE, path="/book-a-demo",
                      timestamp=ts, event_data={"form_values": {"FirstName": "Jane", "Email": email},
                                                "tracking_method": method}))


def test_copied_fill_of_a_tracked_submission_is_dropped(db):
    # The sync joined a known lead before the tracker's copy of the same submission arrived.
    _fill(db, "c1", "javascript", SUBMITTED)
    _fill(db, "c1", "server", SUBMITTED + timedelta(seconds=20), email="Jane@Acme.com")
    db.commit()

    RecomputeJourney().handle(db, {"client_id": "c1"})

    [fill] = db.query(JourneyFormFill).all()
    assert fill.visit_event_id == db.query(VisitEvent).order_by(VisitEvent.id).first().id
    assert db.get(JourneySummary, "c1").form_fill_count == 1


@pytest.mark.parametrize("email, gap", [("joe@acme.com", timedelta(seconds=20)), ("jane@acme.com", timedelta(hours=2))])
def test_other_copied_fills_are_kept(db, email, gap):
    _fill(db, "c1", "javascript", SUBMITTED)
    _fill(db, "c1", "server", SUBMITTED + gap, email=email)
    db.commit()

    RecomputeJourney().handle(db, {"client_id": "c1"})

    assert db.query(JourneyFormFill).count() == 2
