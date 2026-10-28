"""JobScheduler runs each sweep once per interval across app workers. No Postgres needed."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.background import scheduler as scheduler_mod
from app.background.models import BackgroundJobState
from app.background.registry import RegisteredJob
from app.background.scheduler import JobScheduler, swept_recently

NOW = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("last, expected", [
    (None, False),
    (NOW - timedelta(seconds=30), True),
    (NOW - timedelta(minutes=59), True),
    (NOW - timedelta(minutes=60), False),
    (NOW - timedelta(hours=5), False),
    ((NOW - timedelta(minutes=10)).replace(tzinfo=None), True),  # naive values are UTC
])
def test_swept_recently(last, expected):
    assert swept_recently(last, NOW, 60) is expected


class _CountingJob:
    def __init__(self):
        self.sweeps = 0

    def sweep(self, db, since):
        self.sweeps += 1
        return []

    def handle(self, db, payload):
        pass


@pytest.fixture
def scheduler(monkeypatch):
    engine = create_engine("sqlite://")
    BackgroundJobState.__table__.create(engine)
    monkeypatch.setattr(scheduler_mod, "SessionLocal", sessionmaker(bind=engine))
    sched = JobScheduler()
    monkeypatch.setattr(sched, "_try_lock", lambda db, lock_id: object())
    monkeypatch.setattr(sched, "_unlock", lambda conn, lock_id: None)
    yield sched, sessionmaker(bind=engine)
    engine.dispose()


def _job(instance):
    return RegisteredJob(name="reconcile_leads", sweep_interval_minutes=60, instance=instance)


def test_sweep_another_worker_just_ran_is_skipped(scheduler):
    sched, Session = scheduler
    ran_at = datetime.now(timezone.utc) - timedelta(seconds=40)
    with Session() as db:
        db.add(BackgroundJobState(job_name="reconcile_leads", last_processed_at=ran_at))
        db.commit()
    job = _CountingJob()

    sched._run_sweep(_job(job), loop=None)

    assert job.sweeps == 0
    assert sched._last_run["reconcile_leads"] == ran_at  # next due an interval after that run


def test_due_sweep_runs_and_advances_the_watermark(scheduler):
    sched, Session = scheduler
    ran_at = datetime.now(timezone.utc) - timedelta(minutes=61)
    with Session() as db:
        db.add(BackgroundJobState(job_name="reconcile_leads", last_processed_at=ran_at))
        db.commit()
    job = _CountingJob()

    sched._run_sweep(_job(job), loop=None)

    assert job.sweeps == 1
    with Session() as db:
        watermark = db.get(BackgroundJobState, "reconcile_leads").last_processed_at
    assert watermark.replace(tzinfo=timezone.utc) > ran_at


def test_sweep_skipped_while_another_worker_holds_the_lock(scheduler, monkeypatch):
    sched, _ = scheduler
    monkeypatch.setattr(sched, "_try_lock", lambda db, lock_id: None)
    job = _CountingJob()

    sched._run_sweep(_job(job), loop=None)

    assert job.sweeps == 0
