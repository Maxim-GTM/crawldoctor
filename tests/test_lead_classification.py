"""Lead classification: per form fill, per lead, and through recompute_journey / reconcile_leads.

The cases mirror the form fills of the 50 leads production classified on 2026-08-26 (field
names and pages only), plus forms on today's site.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.background.jobs.reconcile_leads import ReconcileLeads
from app.background.jobs.recompute_journey import RecomputeJourney
from app.models.summary import JourneyFormFill, JourneySummary, LeadSummary
from app.models.visit import Visit, VisitEvent, VisitSession
from app.services.lead_classification import (
    DEMO_BIFROST,
    DEMO_MAXIM,
    ENTERPRISE,
    OTHER,
    classify_form_fill,
    summarize_lead,
)

ENTERPRISE_FORM = ["Email", "Company HQ", "Company size", "Enter your name",
                   "Have you tried Bifrost OSS?", "Are you using an LLM Gateway today?"]
DEMO_FORM = ["Email", "LastName", "Location", "FirstName", "CompanySize"]
DOWNLOAD_FORM = ["role", "email", "lastName", "firstName", "companyName", "companySize"]
BEFORE_MERGE = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
AFTER_MERGE = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _fill(url, keys, ts=AFTER_MERGE, form_id=None, action=None):
    path = url.split("://", 1)[1].split("/", 1)[1].split("#")[0].split("?")[0]
    return classify_form_fill(url, "/" + path, {k: "x" for k in keys}, form_id, action, ts)


@pytest.mark.parametrize("url, keys, ts, form_id, expected", [
    # Labels production had (2026-08-26)
    ("https://www.getmaxim.ai/enterprise#free-license", ENTERPRISE_FORM, BEFORE_MERGE, None, ENTERPRISE),
    ("https://www.getmaxim.ai/#enterprise-trial", ENTERPRISE_FORM, BEFORE_MERGE, None, ENTERPRISE),
    ("https://www.getmaxim.ai/bifrost/enterprise", ENTERPRISE_FORM, BEFORE_MERGE, None, ENTERPRISE),
    ("https://www.getmaxim.ai/llm-gateway", ["name", "companyHQ", "usingGateway"], BEFORE_MERGE, None, ENTERPRISE),
    ("https://www.getmaxim.ai/bifrost/resources/buyers-guide#comparison",
     ["name", "email", "companyHQ", "companySize", "usingGateway", "existingGatewaySolution"], BEFORE_MERGE, None, ENTERPRISE),
    ("https://www.getmaxim.ai/pricing#enterprise-support", DOWNLOAD_FORM, BEFORE_MERGE, "bfr-dl-form", ENTERPRISE),
    ("https://www.getmaxim.ai/bifrost/book-a-demo", DEMO_FORM, BEFORE_MERGE, None, DEMO_BIFROST),
    ("https://www.getmaxim.ai/book-a-demo", DEMO_FORM, BEFORE_MERGE, None, DEMO_MAXIM),
    ("https://www.getmaxim.ai/demo", ["Last-name", "First-name", "Work-email", "Company-HQ-2"], BEFORE_MERGE, "email-form", DEMO_MAXIM),
    ("https://www.getmaxim.ai/pricing", ["email"], BEFORE_MERGE, None, OTHER),
    ("https://www.getmaxim.ai/contact", ["email", "message", "last_name", "first_name"], BEFORE_MERGE, None, OTHER),
    ("https://www.getmaxim.ai/bifrost/llm-cost-calculator", DOWNLOAD_FORM, BEFORE_MERGE, "bfr-dl-form", OTHER),
    ("https://www.getmaxim.ai/bifrost", ["bifrost-support-email"], BEFORE_MERGE, None, OTHER),
    # Since the 2026-08-26 merge /book-a-demo is the Bifrost demo
    ("https://www.getmaxim.ai/book-a-demo", DEMO_FORM, AFTER_MERGE, None, DEMO_BIFROST),
    ("https://www.getmaxim.ai/book-a-demo", ["CompanySize", "Email", "Location"], AFTER_MERGE, None, DEMO_BIFROST),
    # Where these rules differ from the 2026-08-26 labels, on purpose:
    # the enterprise form opened on the home page without its #enterprise-trial anchor ...
    ("https://www.getmaxim.ai/", ENTERPRISE_FORM, AFTER_MERGE, None, ENTERPRISE),
    # ... and the footer email box, wherever it was filled in.
    ("https://www.getmaxim.ai/book-a-demo", ["bifrost-support-email"], AFTER_MERGE, None, OTHER),
    ("https://www.getmaxim.ai/enterprise#free-license", ["bifrost-support-email"], AFTER_MERGE, None, OTHER),
    # Other forms on today's site
    ("https://www.getmaxim.ai/partners-program/become-a-partner",
     ["companyHQ", "companyName", "companySize", "firstName", "lastName", "message", "workEmail"], AFTER_MERGE, None, OTHER),
    ("https://www.getmaxim.ai/articles/top-5-llm-routing-techniques/", DOWNLOAD_FORM, AFTER_MERGE, "bfr-dl-form", OTHER),
])
def test_classify_form_fill(url, keys, ts, form_id, expected):
    assert _fill(url, keys, ts, form_id) == expected


def test_enterprise_trial_api_submission_is_enterprise():
    assert _fill("https://www.getmaxim.ai/bifrost", ["email", "name"],
                 action="https://www.getmaxim.ai/bifrost/api/enterprise-trial") == ENTERPRISE


@pytest.mark.parametrize("types, expected", [
    ([DEMO_BIFROST, DEMO_MAXIM], (DEMO_BIFROST, "demo_bifrost,demo_maxim")),
    ([DEMO_MAXIM, OTHER], (DEMO_MAXIM, "demo_maxim,other")),
    ([OTHER, ENTERPRISE, DEMO_BIFROST, DEMO_MAXIM, OTHER],
     (ENTERPRISE, "demo_bifrost,demo_maxim,enterprise_license_request,other")),
    ([OTHER], (OTHER, "other")),
    ([], (None, None)),
])
def test_summarize_lead(types, expected):
    assert summarize_lead(types) == expected


# --- recompute_journey writes the classification -------------------------------------------

@compiles(BigInteger, "sqlite")
def _bigint_primary_keys_autoincrement(type_, compiler, **kw):
    return "INTEGER"  # SQLite only autoincrements INTEGER PRIMARY KEY, not BIGINT


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for model in (VisitSession, Visit, VisitEvent, JourneySummary, JourneyFormFill, LeadSummary):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _submit(db, client_id, url, keys, ts):
    path = "/" + url.split("://", 1)[1].split("/", 1)[1].split("#")[0]
    db.add(VisitEvent(session_id="s1", client_id=client_id, event_type="form_submit", page_url=url,
                      path=path, timestamp=ts,
                      event_data={"form_values": {k: "Jane" if "name" in k.lower() else "jane@acme.com" for k in keys},
                                  "filled_fields": len(keys)}))


def test_recompute_classifies_fills_and_lead(db):
    db.add(VisitSession(id="s1", ip_address="192.0.2.1", user_agent="ua", client_id="c1"))
    db.add(Visit(session_id="s1", client_id="c1", ip_address="192.0.2.1", user_agent="ua",
                 page_url="https://www.getmaxim.ai/", path="/", timestamp=AFTER_MERGE))
    _submit(db, "c1", "https://www.getmaxim.ai/book-a-demo", DEMO_FORM, AFTER_MERGE)
    _submit(db, "c1", "https://www.getmaxim.ai/enterprise#free-license", ENTERPRISE_FORM, AFTER_MERGE)
    _submit(db, "c1", "https://www.getmaxim.ai/", ["bifrost-support-email"], AFTER_MERGE)
    db.commit()

    RecomputeJourney().handle(db, {"client_id": "c1"})

    fills = db.query(JourneyFormFill).order_by(JourneyFormFill.id).all()
    assert [f.form_type for f in fills] == [DEMO_BIFROST, ENTERPRISE, OTHER]
    lead = db.get(LeadSummary, "c1")
    assert lead.lead_type == ENTERPRISE
    assert lead.form_types == "demo_bifrost,enterprise_license_request,other"


def test_reconcile_picks_up_unclassified_leads(db):
    db.add(JourneySummary(client_id="classified", has_captured_data=1))
    db.add(LeadSummary(client_id="classified", lead_type=OTHER))
    db.add(JourneySummary(client_id="unclassified", has_captured_data=1))
    db.add(LeadSummary(client_id="unclassified", lead_type=None))
    db.add(JourneySummary(client_id="missing", has_captured_data=1))
    db.commit()

    payloads = ReconcileLeads().sweep(db, since=AFTER_MERGE)
    assert sorted(p["client_id"] for p in payloads) == ["missing", "unclassified"]


def test_reconcile_repairs_duplicated_form_fills(db):
    # Two workers recomputing one client at once inserted its fills twice (2026-10-28).
    for client_id, copies in (("clean", 1), ("doubled", 2)):
        db.add(JourneySummary(client_id=client_id, has_captured_data=1))
        db.add(LeadSummary(client_id=client_id, lead_type=DEMO_BIFROST))
        for _ in range(copies):
            db.add(JourneyFormFill(client_id=client_id, visit_event_id=7, timestamp=AFTER_MERGE))
    db.commit()

    payloads = ReconcileLeads().sweep(db, since=AFTER_MERGE)
    assert [p["client_id"] for p in payloads] == ["doubled"]


def test_recompute_replaces_duplicated_fills(db):
    db.add(VisitSession(id="s1", ip_address="192.0.2.1", user_agent="ua", client_id="c1"))
    _submit(db, "c1", "https://www.getmaxim.ai/book-a-demo", DEMO_FORM, AFTER_MERGE)
    db.commit()
    RecomputeJourney().handle(db, {"client_id": "c1"})
    event_id = db.query(JourneyFormFill).one().visit_event_id
    db.add(JourneyFormFill(client_id="c1", visit_event_id=event_id, timestamp=AFTER_MERGE))
    db.commit()

    RecomputeJourney().handle(db, {"client_id": "c1"})

    assert db.query(JourneyFormFill).filter_by(client_id="c1").count() == 1
