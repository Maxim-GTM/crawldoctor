-- Backfill visits.source / medium written before the attribution fix (October 2026).
--
-- Not run by the app. Run it on a Neon branch of production first, compare step 0 before and
-- after, then run it on production. Each UPDATE covers one month; run them one at a time.
--
-- Until the fix, a page without UTM parameters took its referrer's host as source, so:
--   * every internal link click became source 'www.getmaxim.ai' (16-20% of human visits a month:
--     14,661 of 89,397 in October 2026, 83,941 of 415,103 in June);
--   * search traffic was 'www.google.com', 'cn.bing.com', ... while UTM traffic was 'google'.
-- The tracker now writes the session's entry attribution for internal navigation and
-- ('google', 'organic') style values for search engines. This makes the history match.
-- The raw referrer stays in visits.referrer, so nothing is lost.

-- 0. What would change, per month
SELECT date_trunc('month', timestamp)::date AS month,
       count(*) FILTER (WHERE source ~* '(^|\.)(getmaxim|getbifrost)\.ai(:\d+)?$') AS self_referrals,
       count(*) FILTER (WHERE source ~* '^(www\.)?google(\.[a-z]{2,3}){1,2}$'
                           OR source ~* '^((www|cn)\.)?bing\.com$'
                           OR source ~* '^((html|lite)\.)?duckduckgo\.com$') AS search_hosts
FROM visits
WHERE timestamp >= '2025-12-01'
GROUP BY 1
ORDER BY 1;

-- 1. Search-engine hosts -> engine name, medium 'organic' (one statement per engine; fast).
UPDATE visits SET source = 'google', medium = coalesce(medium, 'organic')
WHERE source ~* '^(www\.)?google(\.[a-z]{2,3}){1,2}$';
UPDATE visits SET source = 'bing', medium = coalesce(medium, 'organic')
WHERE source ~* '^((www|cn)\.)?bing\.com$';
UPDATE visits SET source = 'duckduckgo', medium = coalesce(medium, 'organic')
WHERE source ~* '^((html|lite)\.)?duckduckgo\.com$';

-- 2. Self-referrals -> the attribution of the session's first visit that isn't one.
--    NULL (direct) when the session has none. Repeat with each month's bounds,
--    from '2025-12-01' to '2026-11-01'.
UPDATE visits v
SET (source, medium, campaign) = (
    SELECT f.source, f.medium, f.campaign
    FROM visits f
    WHERE f.session_id = v.session_id
      AND (f.source IS NULL OR f.source !~* '(^|\.)(getmaxim|getbifrost)\.ai(:\d+)?$')
    ORDER BY f.timestamp
    LIMIT 1
)
WHERE v.timestamp >= '2026-10-01' AND v.timestamp < '2026-11-01'
  AND v.source ~* '(^|\.)(getmaxim|getbifrost)\.ai(:\d+)?$';

-- 3. Afterwards: lead_summaries / journey_summaries copy source from each client's first visit.
--    POST /api/v1/admin/rebuild-summaries recomputes them from the corrected visits.
--    visit_events.source has the same pollution. It is 18M rows and the dashboard's source
--    breakdowns read visits, not events, so leave it unless a report needs it.
