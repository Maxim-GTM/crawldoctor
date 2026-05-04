"""One-off script to backfill IP enrichment for all historical visitor IPs.

Usage:
    # Against prod via fly proxy (run `fly proxy 15432:5432 -a <app>` first):
    CRAWLDOCTOR_DATABASE_URL="postgresql://postgres:postgres@localhost:15432/crawldoctor" \
    python backfill_ip_enrichment.py

    # Dry-run: just print how many IPs need enrichment, don't call the API:
    ... python backfill_ip_enrichment.py --dry-run

Options:
    --dry-run       Count candidates without calling the API.
    --batch-size N  IPs per API batch (default: 25).
    --max-rps N     API requests per second (default: 1.0).
"""

import argparse
import sys
import time
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Bootstrap app settings so the service picks up env vars.
from app.config import settings
from app.services.ip_enrichment import IpEnrichmentService

import structlog
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()


def count_candidates(db) -> int:
    row = db.execute(text("""
        SELECT COUNT(DISTINCT v.ip_address)
        FROM visits v
        WHERE v.is_bot = false
          AND v.ip_address IS NOT NULL
          AND v.ip_address NOT IN ('127.0.0.1', '::1', '')
          AND NOT EXISTS (
            SELECT 1 FROM ip_enrichment e
            WHERE e.ip = v.ip_address
              AND e.status = 'success'
              AND e.ttl_expires_at > now()
          )
          AND NOT EXISTS (
            SELECT 1 FROM ip_enrichment e
            WHERE e.ip = v.ip_address
              AND e.status = 'error'
              AND e.attempt_count >= :max_attempts
          )
    """), {"max_attempts": settings.ip_enrichment_max_attempts}).scalar()
    return row or 0


def main():
    parser = argparse.ArgumentParser(description="Backfill IP enrichment for all visitor IPs.")
    parser.add_argument("--dry-run", action="store_true", help="Count candidates only, no API calls.")
    parser.add_argument("--batch-size", type=int, default=None, help="IPs per batch (default: from config).")
    parser.add_argument("--max-rps", type=float, default=None, help="Max API requests/sec (default: from config).")
    args = parser.parse_args()

    if not settings.database_url:
        print("ERROR: CRAWLDOCTOR_DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        total_candidates = count_candidates(db)
        print(f"\nCandidates needing enrichment: {total_candidates}")

        if args.dry_run:
            print("Dry-run mode — exiting without making API calls.")
            return

        if total_candidates == 0:
            print("Nothing to do.")
            return

        # Override config knobs if provided on the command line.
        if args.batch_size:
            settings.ip_enrichment_batch_size = args.batch_size
        if args.max_rps:
            settings.ip_enrichment_max_rps = args.max_rps

        batch_size = settings.ip_enrichment_batch_size
        estimated_minutes = total_candidates / max(settings.ip_enrichment_max_rps, 0.01) / 60
        print(f"Batch size: {batch_size} IPs  |  Rate: {settings.ip_enrichment_max_rps} req/s")
        print(f"Estimated time: ~{estimated_minutes:.1f} minutes\n")

        svc = IpEnrichmentService()
        totals = {"success": 0, "error": 0, "failed": 0, "batches": 0}
        start = time.monotonic()

        # Loop until no candidates remain. Each run_batch call processes one
        # batch; we cap max_batches high enough that it won't stop us early.
        while True:
            result = svc.run_batch(db, batch_size=batch_size)

            if result.get("skipped"):
                print(f"Batch skipped: {result.get('reason')}")
                break

            totals["batches"] += 1
            totals["success"] += result["success"]
            totals["error"] += result["error"]
            totals["failed"] += result["failed"]

            remaining = count_candidates(db)
            elapsed = time.monotonic() - start
            print(
                f"  batch {totals['batches']:>4} | "
                f"+{result['success']} ok  +{result['error']} err  +{result['failed']} fail | "
                f"{remaining} remaining | {elapsed:.0f}s elapsed"
            )

            if result["candidates"] == 0 or remaining == 0:
                break

        elapsed = time.monotonic() - start
        print(f"\nDone in {elapsed:.1f}s — "
              f"{totals['success']} enriched, "
              f"{totals['error']} transient errors, "
              f"{totals['failed']} permanent failures, "
              f"{totals['batches']} batches.")

        # Final coverage stats
        stats = svc.get_coverage_stats(db)
        print(f"Coverage: {stats['coverage_percent']}% "
              f"({stats['enriched_success_total']}/{stats['candidates_total']} IPs)")

    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
