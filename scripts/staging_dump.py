#!/usr/bin/env python3
"""Create a partial DB dump (last N days) from prod and load it into a staging DB.

Usage:
    # Dump last 15 days from prod to a SQL file
    python scripts/staging_dump.py dump --source-url "postgresql://..." --days 15 --out staging_data.sql

    # Load the dump into a Neon staging DB
    python scripts/staging_dump.py load --target-url "postgresql://...@ep-xxx.neon.tech/crawldoctor" --file staging_data.sql

    # One-shot: dump from prod and load into staging
    python scripts/staging_dump.py sync --source-url "postgresql://..." --target-url "postgresql://...@neon.tech/..." --days 15

Environment variables (alternative to CLI flags):
    CRAWLDOCTOR_DATABASE_URL          - prod DB (used as --source-url default)
    CRAWLDOCTOR_STAGING_DATABASE_URL  - staging DB (used as --target-url default)
"""

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta

# All tables in dependency order (FK targets before FK sources).
TABLES = [
    "users",
    "funnel_configs",
    "visit_sessions",
    "visits",
    "visit_events",
    "journey_summaries",
    "lead_summaries",
    "journey_form_fills",
]

# Small config/auth tables — dump in full (no date filter).
FULL_DUMP_TABLES = {"users", "funnel_configs"}

# Large tracking tables — filter by timestamp column.
DATE_FILTERED_TABLES = {
    "visit_sessions": "last_visit",
    "visits":         "timestamp",
    "visit_events":   "timestamp",
}

# Summary tables — filter by client_id overlap with recent visits.
SUMMARY_TABLES = {"journey_summaries", "lead_summaries", "journey_form_fills"}


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess, printing the command for visibility."""
    printable = " ".join(cmd[:3]) + " ..."
    print(f"  -> {printable}")
    return subprocess.run(cmd, check=True, **kwargs)


def _psql(url: str, sql: str, capture: bool = False) -> str | None:
    """Execute SQL against a Postgres URL via psql."""
    result = subprocess.run(
        ["psql", url, "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=capture,
        text=True,
    )
    if result.returncode != 0:
        if capture:
            print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"psql command failed: {sql[:80]}...")
    return result.stdout if capture else None


def dump(source_url: str, days: int, out_path: str, since: str | None = None, until: str | None = None) -> None:
    """Dump the last `days` of data from source into a SQL file.

    If `since` is provided (ISO timestamp), it overrides `days`.
    If `until` is provided, only rows with timestamp < until are included.
    """
    if since:
        cutoff = since
        print(f"Dumping since {cutoff}{f' until {until}' if until else ''} to {out_path}")
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S+00")
        print(f"Dumping last {days} days (since {cutoff}{f' until {until}' if until else ''}) to {out_path}")

    with open(out_path, "w") as f:
        # Header
        f.write(f"-- CrawlDoctor staging dump — last {days} days (since {cutoff})\n")
        f.write("-- Generated at {}\n".format(datetime.now(timezone.utc).isoformat()))
        f.write("BEGIN;\n\n")
        # Drop FK constraints during load — partial dumps will have dangling references
        # (e.g. events pointing to visits older than the dump window).
        # session_replication_role requires superuser (not available on Neon),
        # so we drop and re-create the constraints instead.
        f.write("ALTER TABLE visit_events DROP CONSTRAINT IF EXISTS visit_events_session_id_fkey;\n")
        f.write("ALTER TABLE visit_events DROP CONSTRAINT IF EXISTS visit_events_visit_id_fkey;\n")
        f.write("ALTER TABLE visits DROP CONSTRAINT IF EXISTS visits_session_id_fkey;\n\n")

    for table in TABLES:
        print(f"  Dumping {table}...")

        if table in FULL_DUMP_TABLES:
            where_clause = ""
        elif table in DATE_FILTERED_TABLES:
            ts_col = DATE_FILTERED_TABLES[table]
            where_clause = f"WHERE {ts_col} >= '{cutoff}'"
            if until:
                where_clause += f" AND {ts_col} < '{until}'"
        elif table in SUMMARY_TABLES:
            visits_range = f"timestamp >= '{cutoff}'"
            if until:
                visits_range += f" AND timestamp < '{until}'"
            where_clause = (
                f"WHERE client_id IN ("
                f"SELECT DISTINCT client_id FROM visits WHERE {visits_range} AND client_id IS NOT NULL"
                f")"
            )
        else:
            where_clause = ""

        copy_sql = f"\\copy (SELECT * FROM {table} {where_clause}) TO STDOUT WITH (FORMAT csv, HEADER true)"

        # Use psql to run the COPY and capture CSV output
        result = subprocess.run(
            ["psql", source_url, "-c", copy_sql],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"    Warning: failed to dump {table}: {result.stderr.strip()}")
            continue

        csv_data = result.stdout
        if not csv_data.strip():
            print(f"    (empty — skipping)")
            continue

        # Parse the CSV header to get column names
        lines = csv_data.strip().split("\n")
        header = lines[0]
        data_lines = lines[1:]
        print(f"    {len(data_lines)} rows")

        with open(out_path, "a") as f:
            # Create a temp table approach: use COPY FROM STDIN with CSV
            f.write(f"-- {table}: {len(data_lines)} rows\n")
            f.write(f"\\copy {table} ({header}) FROM STDIN WITH (FORMAT csv, HEADER false);\n")
            for line in data_lines:
                f.write(line + "\n")
            f.write("\\.\n\n")

    with open(out_path, "a") as f:
        # Re-add FK constraints (allow invalid refs from partial dump)
        f.write("ALTER TABLE visits ADD CONSTRAINT visits_session_id_fkey FOREIGN KEY (session_id) REFERENCES visit_sessions(id) NOT VALID;\n")
        f.write("ALTER TABLE visit_events ADD CONSTRAINT visit_events_session_id_fkey FOREIGN KEY (session_id) REFERENCES visit_sessions(id) NOT VALID;\n")
        f.write("ALTER TABLE visit_events ADD CONSTRAINT visit_events_visit_id_fkey FOREIGN KEY (visit_id) REFERENCES visits(id) NOT VALID;\n\n")
        f.write("COMMIT;\n")

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"Done. Dump file: {out_path} ({size_mb:.1f} MB)")


def load(target_url: str, file_path: str) -> None:
    """Load a dump file into the target (staging) database.

    This:
    1. Runs alembic upgrade head (creates tables from scratch on a fresh DB)
    2. Truncates the target tables (staging is throwaway)
    3. Loads the dump
    """
    print(f"Loading {file_path} into staging DB")

    # Run migrations — on a fresh DB this creates all tables from the initial
    # migration onward; on an existing DB it applies any pending migrations.
    print("  Running alembic migrations...")
    env = os.environ.copy()
    env["CRAWLDOCTOR_DATABASE_URL"] = target_url
    try:
        _run(["alembic", "upgrade", "head"], env=env)
    except subprocess.CalledProcessError:
        print("  Warning: alembic upgrade failed — schema may already be current")

    # Truncate in reverse dependency order
    print("  Truncating staging tables...")
    truncate_sql = "TRUNCATE {} CASCADE;".format(", ".join(reversed(TABLES)))
    try:
        _psql(target_url, truncate_sql)
    except RuntimeError:
        # Tables might not exist yet on first run
        for table in reversed(TABLES):
            try:
                _psql(target_url, f"TRUNCATE {table} CASCADE;")
            except RuntimeError:
                pass

    # Load the dump table-by-table — strip BEGIN/COMMIT so each \copy
    # auto-commits independently instead of one giant transaction.
    print("  Loading data (per-table commits)...")
    with open(file_path) as f:
        content = f.read()

    # Split into per-table blocks by finding \copy ... \. sequences
    import re
    # Find: optional comment line, \copy line, data lines, \. terminator
    pattern = re.compile(
        r"(-- [^\n]*\n)?"                          # optional comment
        r"(\\copy\s+\S+[^\n]*\n)"                  # \copy command
        r"(.*?)"                                    # data
        r"(\\\.)",                                  # \. terminator
        re.DOTALL,
    )

    # Drop FK constraints before loading data — only run DROP statements,
    # not the ADD statements that appear later in the dump file.
    alter_stmts = re.findall(r"(ALTER TABLE[^\n]+DROP CONSTRAINT[^\n]+;)", content)
    for stmt in alter_stmts:
        print(f"    {stmt[:60]}...")
        try:
            _psql(target_url, stmt)
        except RuntimeError:
            pass

    # Max rows per COPY chunk — keeps memory pressure on the server manageable.
    CHUNK_SIZE = 50_000

    # Load each table block, splitting large tables into chunks
    for match in pattern.finditer(content):
        block = match.group(0)
        table_match = re.search(r"\\copy\s+(\S+)", block)
        table_name = table_match.group(1) if table_match else "unknown"

        # The \copy header line (includes FROM STDIN already)
        copy_line_match = re.search(r"(\\copy\s+[^\n]+)\n", block)
        copy_header = copy_line_match.group(1) if copy_line_match else ""

        # Extract data lines: everything between the \copy line and the \. terminator
        copy_line_end = copy_line_match.end() if copy_line_match else 0
        data_end = block.rfind("\\.")
        data_section = block[copy_line_end:data_end]
        data_lines = [l for l in data_section.split("\n") if l]

        total_rows = len(data_lines)
        print(f"    Loading {table_name} ({total_rows} rows)...")

        if total_rows == 0:
            continue

        # Split into chunks to avoid OOM on the server
        loaded = 0
        for chunk_start in range(0, total_rows, CHUNK_SIZE):
            chunk_lines = data_lines[chunk_start:chunk_start + CHUNK_SIZE]
            # Reuse the original \copy header (already has FROM STDIN clause)
            chunk_block = copy_header + "\n"
            chunk_block += "\n".join(chunk_lines) + "\n\\.\n"

            with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as tmp:
                tmp.write(chunk_block)
                tmp_path = tmp.name
            try:
                _run(["psql", target_url, "-f", tmp_path])
                loaded += len(chunk_lines)
                if total_rows > CHUNK_SIZE:
                    print(f"      {table_name}: {loaded}/{total_rows}")
            except subprocess.CalledProcessError as e:
                print(f"      Warning: chunk failed for {table_name} at row {chunk_start}: {e}")
            finally:
                os.unlink(tmp_path)

        print(f"    {table_name}: {loaded}/{total_rows} loaded")

    # Re-add FK constraints after all data is loaded
    add_stmts = re.findall(r"(ALTER TABLE[^\n]+ADD CONSTRAINT[^\n]+;)", content)
    for stmt in add_stmts:
        print(f"    {stmt[:60]}...")
        try:
            _psql(target_url, stmt)
        except RuntimeError as e:
            print(f"    Warning: {e}")

    # Quick row counts
    print("  Row counts:")
    for table in TABLES:
        try:
            out = _psql(target_url, f"SELECT count(*) FROM {table};", capture=True)
            count = out.strip().split("\n")[-2].strip() if out else "?"
            print(f"    {table}: {count}")
        except RuntimeError:
            print(f"    {table}: (not found)")

    print("Done. Staging DB is ready.")


def merge(target_url: str, file_path: str) -> None:
    """Merge a dump file into an existing DB, skipping rows that already exist.

    Unlike `load`, this does NOT truncate — it inserts with ON CONFLICT DO NOTHING
    so only genuinely new rows are added.  Designed for replaying new traffic into
    a restored backup.
    """
    print(f"Merging {file_path} into DB (ON CONFLICT DO NOTHING)")

    with open(file_path) as f:
        content = f.read()

    import re

    # Drop FK constraints before merge (same as load) — ignore errors if already dropped
    drop_stmts = re.findall(r"(ALTER TABLE[^\n]+DROP CONSTRAINT[^\n]+;)", content)
    for stmt in drop_stmts:
        print(f"  {stmt[:60]}...")
        try:
            _psql(target_url, stmt)
        except RuntimeError:
            pass

    # Match blocks like: \copy table (cols) FROM STDIN ... \n<data>\n\.
    pattern = re.compile(
        r"\\copy\s+(\w+)\s+\(([^)]+)\)\s+FROM STDIN[^\n]*\n(.*?)\\\\?\.",
        re.DOTALL,
    )

    CHUNK_SIZE = 50_000

    for match in pattern.finditer(content):
        table = match.group(1)
        columns = match.group(2).strip()
        csv_block = match.group(3)

        lines = [l for l in csv_block.strip().split("\n") if l.strip()]
        if not lines:
            print(f"  {table}: 0 rows — skipping")
            continue

        total_rows = len(lines)
        print(f"  {table}: {total_rows} rows")

        tmp_table = f"_tmp_merge_{table}"
        merged = 0

        for chunk_start in range(0, total_rows, CHUNK_SIZE):
            chunk_lines = lines[chunk_start:chunk_start + CHUNK_SIZE]

            tmp_csv = tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False, prefix=f"merge_{table}_"
            )
            tmp_csv.write("\n".join(chunk_lines) + "\n")
            tmp_csv.close()

            merge_sql = (
                f"INSERT INTO {table} ({columns}) "
                f"SELECT {columns} FROM {tmp_table} "
                f"ON CONFLICT DO NOTHING;"
            )
            script = (
                f"CREATE TEMP TABLE {tmp_table} (LIKE {table} INCLUDING ALL);\n"
                f"\\copy {tmp_table} ({columns}) FROM '{tmp_csv.name}' WITH (FORMAT csv)\n"
                f"{merge_sql}\n"
                f"DROP TABLE IF EXISTS {tmp_table};\n"
            )

            with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False, prefix=f"merge_script_{table}_") as tmp_script:
                tmp_script.write(script)
                tmp_script_path = tmp_script.name

            try:
                _run(["psql", target_url, "-f", tmp_script_path])
                merged += len(chunk_lines)
                if total_rows > CHUNK_SIZE:
                    print(f"      {table}: {merged}/{total_rows}")
            except subprocess.CalledProcessError as e:
                print(f"    Warning: chunk failed for {table} at row {chunk_start}: {e}")
            finally:
                os.unlink(tmp_csv.name)
                os.unlink(tmp_script_path)

        print(f"    {table}: {merged}/{total_rows} merged")

    # Re-add FK constraints after all data is loaded
    add_stmts = re.findall(r"(ALTER TABLE[^\n]+ADD CONSTRAINT[^\n]+;)", content)
    for stmt in add_stmts:
        print(f"  {stmt[:60]}...")
        try:
            _psql(target_url, stmt)
        except RuntimeError as e:
            print(f"    Warning: {e}")

    # Quick row counts
    print("  Row counts:")
    for table in TABLES:
        try:
            out = _psql(target_url, f"SELECT count(*) FROM {table};", capture=True)
            count = out.strip().split("\n")[-2].strip() if out else "?"
            print(f"    {table}: {count}")
        except RuntimeError:
            print(f"    {table}: (not found)")

    print("Done. New traffic merged.")


def sync(source_url: str, target_url: str, days: int) -> None:
    """Dump from prod and load into staging in one step."""
    with tempfile.NamedTemporaryFile(suffix=".sql", delete=False, mode="w") as tmp:
        tmp_path = tmp.name

    try:
        dump(source_url, days, tmp_path)
        load(target_url, tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Create a partial DB dump for staging (Neon).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- dump --
    p_dump = sub.add_parser("dump", help="Dump last N days from prod to a SQL file")
    p_dump.add_argument("--source-url", default=os.getenv("CRAWLDOCTOR_DATABASE_URL"),
                        help="Prod database URL (default: $CRAWLDOCTOR_DATABASE_URL)")
    p_dump.add_argument("--days", type=int, default=15, help="Number of days to include (default: 15)")
    p_dump.add_argument("--since", default=None, help="Absolute UTC cutoff timestamp (overrides --days), e.g. '2026-04-02 01:10:00+00'")
    p_dump.add_argument("--until", default=None, help="Exclusive upper bound UTC timestamp, e.g. '2026-06-09 00:00:00+00'")
    p_dump.add_argument("--out", default="staging_data.sql", help="Output file path")

    # -- load --
    p_load = sub.add_parser("load", help="Load a dump file into staging DB")
    p_load.add_argument("--target-url", default=os.getenv("CRAWLDOCTOR_STAGING_DATABASE_URL"),
                        help="Staging database URL (default: $CRAWLDOCTOR_STAGING_DATABASE_URL)")
    p_load.add_argument("--file", required=True, help="Dump file to load")

    # -- merge --
    p_merge = sub.add_parser("merge", help="Merge a dump into an existing DB (ON CONFLICT DO NOTHING)")
    p_merge.add_argument("--target-url", default=os.getenv("CRAWLDOCTOR_DATABASE_URL"),
                         help="Target database URL (default: $CRAWLDOCTOR_DATABASE_URL)")
    p_merge.add_argument("--file", required=True, help="Dump file to merge")

    # -- sync --
    p_sync = sub.add_parser("sync", help="Dump from prod and load into staging in one shot")
    p_sync.add_argument("--source-url", default=os.getenv("CRAWLDOCTOR_DATABASE_URL"),
                        help="Prod database URL")
    p_sync.add_argument("--target-url", default=os.getenv("CRAWLDOCTOR_STAGING_DATABASE_URL"),
                        help="Staging database URL")
    p_sync.add_argument("--days", type=int, default=15, help="Number of days to include")

    args = parser.parse_args()

    if args.command == "dump":
        if not args.source_url:
            parser.error("--source-url required (or set CRAWLDOCTOR_DATABASE_URL)")
        dump(args.source_url, args.days, args.out, since=args.since, until=args.until)

    elif args.command == "load":
        if not args.target_url:
            parser.error("--target-url required (or set CRAWLDOCTOR_STAGING_DATABASE_URL)")
        load(args.target_url, args.file)

    elif args.command == "merge":
        if not args.target_url:
            parser.error("--target-url required (or set CRAWLDOCTOR_DATABASE_URL)")
        merge(args.target_url, args.file)

    elif args.command == "sync":
        if not args.source_url:
            parser.error("--source-url required (or set CRAWLDOCTOR_DATABASE_URL)")
        if not args.target_url:
            parser.error("--target-url required (or set CRAWLDOCTOR_STAGING_DATABASE_URL)")
        sync(args.source_url, args.target_url, args.days)


if __name__ == "__main__":
    main()
