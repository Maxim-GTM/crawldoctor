-- Proposal: heartbeat retention for visit_events. Not run by the app; nothing here has been run.
--
-- Numbers from production, 2026-10-28:
--   visit_events: 11 GB heap + 13 GB in 22 indexes, about 1.4 KB per row.
--   heartbeat rows: 7.72M of 18.3M events (42%), about 10-11 GB of the 24 GB.
--   About 7.5M heartbeats are older than 30 days and about 6.5M older than 90 days.
--   Per page view in the last 7 days: median 1 heartbeat, p90 11, max 1,570 (a tab left open
--   for 13 hours).
--   No CrawlDoctor code reads heartbeats; the live feed filters them out. Time on page is also
--   on the unload event (event_type 'navigation', data.kind 'unload': time_on_page_ms, idle_time_ms).
--
-- Check first that Airflow and Weekly Metrics (they share this database) don't read heartbeats.
--
-- 1. Going forward, downsample in the tracker (app/static/tracker.js): send the first 4 beats
--    at 30 s, then one every 5 minutes. On last week's traffic that keeps 13,364 of 44,354
--    heartbeats (-70%) and still records how long people stay.
--
-- 2. Retention: delete heartbeats older than 30 days, in batches so locks and WAL stay small.
--    Repeat until it deletes 0 rows (about 150 runs of 50,000).
DELETE FROM visit_events
WHERE id IN (
    SELECT id FROM visit_events
    WHERE event_type = 'heartbeat'
      AND timestamp < now() - interval '30 days'
    LIMIT 50000
);

-- 3. Then let Postgres reuse the space. A plain VACUUM doesn't shrink the files; new rows fill
--    the freed pages, so the table stops growing for months. To return the ~10 GB to Neon at
--    once, rebuild the table with pg_repack (no long lock) instead of VACUUM FULL (locks
--    visit_events for the whole rebuild and stops ingestion).
VACUUM (ANALYZE) visit_events;

-- 4. To keep it bounded, schedule step 2 daily (e.g. as a background job deleting heartbeats
--    older than 30 days), together with visibility events (2.67M rows, 15%, also unread).
