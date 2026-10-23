# CrawlDoctor Database Schema

## Overview

CrawlDoctor is a web analytics and visitor tracking system that monitors website visits, tracks user journeys, detects bot/crawler traffic, and captures lead information from form submissions.

---

## Tables

### 1. `visit_sessions` (Primary Key: `id`)
**Purpose:** Stores unique visitor sessions identified by IP + User Agent combination. This is the top-level entity that groups multiple visits.

**Row Count:** ~369,563 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | VARCHAR(64) | NO | **PK** - Session hash (MD5 of IP + User Agent) |
| `ip_address` | VARCHAR(45) | NO | Visitor's IP address (supports IPv6) |
| `user_agent` | VARCHAR(1000) | NO | Full user agent string |
| `crawler_type` | VARCHAR(100) | YES | Bot type if detected: `GoogleBot`, `BingBot`, `GPTBot`, `ClaudeBot`, `ChatGPT-User`, `Bytespider`, `OpenAI`, `Suspicious Bot`, `Unknown Bot`, `Empty User Agent`, or NULL for humans |
| `first_visit` | TIMESTAMPTZ | YES | First visit timestamp (default: now()) |
| `last_visit` | TIMESTAMPTZ | YES | Most recent visit timestamp |
| `visit_count` | INTEGER | YES | Number of page visits in this session |
| `country` | VARCHAR(2) | YES | ISO 2-letter country code (e.g., `US`, `IN`, `XX` for unknown) |
| `country_name` | VARCHAR(100) | YES | Full country name |
| `city` | VARCHAR(100) | YES | City name from geo-IP lookup |
| `latitude` | DOUBLE PRECISION | YES | Geographic latitude |
| `longitude` | DOUBLE PRECISION | YES | Geographic longitude |
| `timezone` | VARCHAR(50) | YES | Server-detected timezone |
| `isp` | VARCHAR(200) | YES | Internet Service Provider name |
| `organization` | VARCHAR(200) | YES | Organization name from IP lookup |
| `asn` | VARCHAR(50) | YES | Autonomous System Number |
| `client_id` | VARCHAR(64) | YES | Client-side UUID (persistent across sessions) |
| `client_side_timezone` | VARCHAR(50) | YES | Client-reported timezone (e.g., `Asia/Calcutta`) |
| `client_side_language` | VARCHAR(50) | YES | Browser language (e.g., `en-US`) |
| `client_side_screen_resolution` | VARCHAR(50) | YES | Screen resolution (e.g., `1440x900`) |
| `client_side_viewport_size` | VARCHAR(50) | YES | Browser viewport size (e.g., `1428x776`) |
| `client_side_device_memory` | VARCHAR(20) | YES | Device memory (e.g., `8GB`) |
| `client_side_connection_type` | VARCHAR(50) | YES | Network connection type (e.g., `4g`) |

---

### 2. `visits` (Primary Key: `id`)
**Purpose:** Individual page visits/requests. The main event table for tracking every page load.

**Row Count:** ~788,383 rows | **Size:** 530 MB

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGINT | NO | **PK** - Auto-increment visit ID |
| `session_id` | VARCHAR(64) | YES | **FK** → `visit_sessions.id` |
| `timestamp` | TIMESTAMPTZ | YES | Visit timestamp (default: now()) |
| `ip_address` | VARCHAR(45) | NO | Visitor IP address |
| `user_agent` | VARCHAR(1000) | NO | User agent string |
| `page_url` | VARCHAR(2000) | YES | Full URL visited |
| `referrer` | VARCHAR(2000) | YES | HTTP referrer URL |
| `page_title` | VARCHAR(500) | YES | HTML page title |
| `page_domain` | VARCHAR(200) | YES | Domain of the visited page (e.g., `www.getmaxim.ai`) |
| `crawler_type` | VARCHAR(100) | YES | Detected bot type (same values as visit_sessions) |
| `crawler_confidence` | DOUBLE PRECISION | YES | Bot detection confidence score (0.0-1.0, typically 0.8) |
| `is_bot` | BOOLEAN | YES | True if classified as bot |
| `request_method` | VARCHAR(10) | YES | HTTP method (`GET`, `POST`, etc.) |
| `request_headers` | JSON | YES | Full request headers as JSON |
| `response_status` | INTEGER | YES | HTTP response status code |
| `response_size` | INTEGER | YES | Response size in bytes |
| `response_time_ms` | DOUBLE PRECISION | YES | Server response time in milliseconds |
| `country` | VARCHAR(2) | YES | ISO country code |
| `city` | VARCHAR(100) | YES | City name |
| `tracking_id` | VARCHAR(100) | YES | Site tracking identifier (e.g., `bifrost-main`, `maxim-site`) |
| `campaign` | VARCHAR(100) | YES | UTM campaign parameter |
| `source` | VARCHAR(100) | YES | Traffic source (e.g., `www.google.com`, `www.linkedin.com`) |
| `medium` | VARCHAR(100) | YES | UTM medium parameter |
| `content_type` | VARCHAR(100) | YES | Response content type |
| `content_language` | VARCHAR(10) | YES | Content language |
| `content_encoding` | VARCHAR(50) | YES | Content encoding |
| `protocol` | VARCHAR(10) | YES | Protocol (`http`, `https`) |
| `port` | INTEGER | YES | Port number |
| `path` | VARCHAR(1000) | YES | URL path (e.g., `/bifrost/llm-cost-calculator`) |
| `query_params` | JSON | YES | Query parameters as JSON |
| `client_id` | VARCHAR(64) | YES | Client-side persistent UUID |
| `client_side_timezone` | VARCHAR(50) | YES | Client-reported timezone |
| `client_side_language` | VARCHAR(50) | YES | Browser language |
| `client_side_screen_resolution` | VARCHAR(50) | YES | Screen resolution |
| `client_side_viewport_size` | VARCHAR(50) | YES | Viewport size |
| `client_side_device_memory` | VARCHAR(20) | YES | Device memory |
| `client_side_connection_type` | VARCHAR(50) | YES | Connection type |

---

### 3. `visit_events` (Primary Key: `id`)
**Purpose:** Granular user interaction events (scrolls, clicks, form inputs, page views). The most detailed tracking table.

**Row Count:** ~3,703,166 rows | **Size:** 2.08 GB

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGINT | NO | **PK** - Auto-increment event ID |
| `session_id` | VARCHAR(64) | YES | **FK** → `visit_sessions.id` |
| `visit_id` | BIGINT | YES | **FK** → `visits.id` |
| `timestamp` | TIMESTAMPTZ | YES | Event timestamp |
| `event_type` | VARCHAR(50) | YES | Event type - see values below |
| `page_url` | VARCHAR(2000) | YES | Page where event occurred |
| `referrer` | VARCHAR(2000) | YES | Referrer URL |
| `path` | VARCHAR(1000) | YES | URL path |
| `event_data` | JSON | YES | Event-specific data (scroll position, click target, etc.) |
| `client_id` | VARCHAR(64) | YES | Client-side UUID |
| `client_side_timezone` | VARCHAR(50) | YES | Client timezone |
| `client_side_language` | VARCHAR(50) | YES | Browser language |
| `client_side_screen_resolution` | VARCHAR(50) | YES | Screen resolution |
| `client_side_viewport_size` | VARCHAR(50) | YES | Viewport size |
| `client_side_device_memory` | VARCHAR(20) | YES | Device memory |
| `client_side_connection_type` | VARCHAR(50) | YES | Connection type |
| `page_domain` | VARCHAR(200) | YES | Page domain |
| `referrer_domain` | VARCHAR(200) | YES | Referrer domain |
| `tracking_id` | VARCHAR(100) | YES | Site tracking ID |
| `source` | VARCHAR(100) | YES | Traffic source |
| `medium` | VARCHAR(100) | YES | UTM medium |
| `campaign` | VARCHAR(100) | YES | UTM campaign |

**Event Types:**
- `page_view` - Page load event
- `scroll` - Scroll event (event_data contains: `y`, `percent`)
- `click` - Click event
- `form_start` - User started filling a form
- `form_input` - Form field input
- `form_submit` - Form submission
- `navigate` / `navigation` - Navigation events
- `heartbeat` - Session keepalive ping
- `visibility` - Page visibility change
- `docs.search.query` - Documentation search
- `docs.assistant.enter` - AI assistant interaction
- `docs.assistant.completed` - AI assistant response
- `docs.assistant.suggestion_click` - Clicked AI suggestion
- `docs.accordion.open` - Accordion expand
- `docs.content.view` - Content view tracking

---

### 4. `journey_summaries` (Primary Key: `client_id`)
**Purpose:** Aggregated visitor journey data showing the path each visitor took through the site.

**Row Count:** ~405 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `client_id` | VARCHAR(64) | NO | **PK** - Client UUID |
| `first_seen` | TIMESTAMPTZ | YES | First interaction timestamp |
| `last_seen` | TIMESTAMPTZ | YES | Most recent interaction |
| `visit_count` | INTEGER | YES | Total page visits |
| `entry_page` | TEXT | YES | First page visited (full URL) |
| `exit_page` | TEXT | YES | Last page visited (full URL) |
| `path_sequence` | TEXT | YES | Ordered list of paths visited |
| `email` | VARCHAR(255) | YES | Captured email if submitted |
| `name` | VARCHAR(255) | YES | Captured name or user agent |
| `has_captured_data` | INTEGER | YES | Flag: 1 if form data captured |
| `source` | VARCHAR(100) | YES | Traffic source |
| `medium` | VARCHAR(100) | YES | UTM medium |
| `campaign` | VARCHAR(100) | YES | UTM campaign |
| `updated_at` | TIMESTAMPTZ | YES | Last update timestamp |
| `form_fill_count` | INTEGER | YES | Number of form fills (default: 0) |

---

### 5. `lead_summaries` (Primary Key: `client_id`)
**Purpose:** Summary of captured lead/form submission data for each visitor.

**Row Count:** ~405 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `client_id` | VARCHAR(64) | NO | **PK** - Client UUID |
| `email` | VARCHAR(255) | YES | Captured email address |
| `name` | VARCHAR(255) | YES | Captured name or user agent |
| `captured_at` | TIMESTAMPTZ | YES | When data was captured |
| `captured_page` | TEXT | YES | Page where form was submitted |
| `captured_path` | TEXT | YES | URL path of capture |
| `form_data_shared` | TEXT | YES | Pipe-delimited form field values |
| `captured_data` | TEXT | YES | JSON string of all captured form data |
| `source` | VARCHAR(100) | YES | Traffic source |
| `medium` | VARCHAR(100) | YES | UTM medium |
| `campaign` | VARCHAR(100) | YES | UTM campaign |
| `first_referrer` | TEXT | YES | Original referrer URL |
| `first_referrer_domain` | VARCHAR(200) | YES | Original referrer domain |
| `first_seen` | TIMESTAMPTZ | YES | First visit timestamp |
| `last_seen` | TIMESTAMPTZ | YES | Last visit timestamp |
| `updated_at` | TIMESTAMPTZ | YES | Last update timestamp |

---

### 6. `journey_form_fills` (Primary Key: `id`)
**Purpose:** Detailed form interaction tracking - captures form field values when users fill forms.

**Row Count:** ~1,164 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGINT | NO | **PK** - Auto-increment ID |
| `client_id` | VARCHAR(64) | NO | Client UUID |
| `visit_event_id` | BIGINT | YES | **FK** → `visit_events.id` |
| `timestamp` | TIMESTAMPTZ | NO | Form fill timestamp |
| `page_url` | VARCHAR(2000) | YES | Page with the form |
| `path` | VARCHAR(1000) | YES | URL path |
| `form_values` | JSONB | YES | Captured form field values as JSON |
| `filled_fields` | INTEGER | YES | Number of fields filled |
| `form_id` | VARCHAR(255) | YES | HTML form ID attribute |
| `form_action` | VARCHAR(2000) | YES | Form action URL |

---

### 7. `users` (Primary Key: `id`)
**Purpose:** Application user accounts for dashboard access.

**Row Count:** 1 row

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | **PK** - Auto-increment user ID |
| `username` | VARCHAR(50) | NO | **UNIQUE** - Username |
| `email` | VARCHAR(100) | NO | **UNIQUE** - Email address |
| `hashed_password` | VARCHAR(255) | NO | bcrypt hashed password |
| `full_name` | VARCHAR(100) | YES | Full name |
| `is_active` | BOOLEAN | YES | Account active flag |
| `is_superuser` | BOOLEAN | YES | Admin privileges flag |
| `last_login` | TIMESTAMPTZ | YES | Last login timestamp |
| `created_at` | TIMESTAMPTZ | YES | Account creation time |
| `updated_at` | TIMESTAMPTZ | YES | Last update time |
| `api_key` | VARCHAR(64) | YES | **UNIQUE** - API authentication key |
| `api_key_created_at` | TIMESTAMPTZ | YES | API key creation time |
| `timezone` | VARCHAR(50) | YES | User's timezone preference |
| `notification_preferences` | TEXT | YES | Notification settings |

---

### 8. `funnel_configs` (Primary Key: `id`)
**Purpose:** User-defined conversion funnel configurations for tracking multi-step user flows.

**Row Count:** 1 row

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | **PK** - Auto-increment ID |
| `user_id` | INTEGER | NO | **FK** → `users.id`, **UNIQUE** |
| `config` | JSON | NO | Funnel configuration JSON |
| `created_at` | TIMESTAMPTZ | YES | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | YES | Last update timestamp |

**Config JSON Structure:**
```json
{
  "funnels": [
    {
      "key": "demo_to_schedule",
      "label": "Any Page → /demo → Form Submit → /schedule",
      "steps": [
        {"label": "Visited /demo", "type": "page", "path": "/demo", "event_type": "form_submit"},
        {"label": "Submitted form", "type": "event", "path": "/demo", "event_type": "form_submit"},
        {"label": "Visited /schedule", "type": "page", "path": "/schedule", "event_type": "form_submit"}
      ]
    }
  ]
}
```

---

### 9. `tracking_metadata` (Primary Key: `id`)
**Purpose:** Configuration for different tracking IDs/sites being monitored.

**Row Count:** 0 rows (configuration table)

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | **PK** - Auto-increment ID |
| `tracking_id` | VARCHAR(100) | YES | **UNIQUE** - Tracking identifier |
| `domain` | VARCHAR(200) | NO | Domain being tracked |
| `created_by` | INTEGER | YES | **FK** → `users.id` |
| `name` | VARCHAR(200) | NO | Display name |
| `description` | TEXT | YES | Description |
| `is_active` | BOOLEAN | YES | Active flag |
| `track_pageviews` | BOOLEAN | YES | Track page views |
| `track_events` | BOOLEAN | YES | Track events |
| `track_sessions` | BOOLEAN | YES | Track sessions |
| `track_geographic` | BOOLEAN | YES | Track geo data |
| `track_performance` | BOOLEAN | YES | Track performance |
| `max_requests_per_minute` | INTEGER | YES | Rate limit per minute |
| `max_requests_per_hour` | INTEGER | YES | Rate limit per hour |
| `data_retention_days` | INTEGER | YES | Data retention period |
| `auto_delete_enabled` | BOOLEAN | YES | Auto-delete old data |
| `total_visits` | BIGINT | YES | Aggregate visit count |
| `total_events` | BIGINT | YES | Aggregate event count |
| `unique_visitors` | INTEGER | YES | Unique visitor count |
| `last_visit` | TIMESTAMPTZ | YES | Last visit timestamp |
| `created_at` | TIMESTAMPTZ | YES | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | YES | Last update timestamp |

---

### 10. `tracking_events` (Primary Key: `id`)
**Purpose:** Custom tracking events with detailed device/performance metrics.

**Row Count:** 0 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGINT | NO | **PK** - Auto-increment ID |
| `visit_id` | BIGINT | YES | **FK** → `visits.id` |
| `event_type` | VARCHAR(50) | NO | Event type |
| `event_name` | VARCHAR(100) | YES | Custom event name |
| `timestamp` | TIMESTAMPTZ | YES | Event timestamp |
| `event_data` | JSON | YES | Event payload |
| `event_value` | DOUBLE PRECISION | YES | Numeric event value |
| `event_category` | VARCHAR(100) | YES | Event category |
| `event_label` | VARCHAR(200) | YES | Event label |
| `load_time_ms` | DOUBLE PRECISION | YES | Page load time |
| `network_type` | VARCHAR(50) | YES | Network type |
| `connection_speed` | VARCHAR(50) | YES | Connection speed |
| `screen_resolution` | VARCHAR(20) | YES | Screen resolution |
| `viewport_size` | VARCHAR(20) | YES | Viewport size |
| `color_depth` | INTEGER | YES | Screen color depth |
| `pixel_ratio` | DOUBLE PRECISION | YES | Device pixel ratio |
| `javascript_enabled` | BOOLEAN | YES | JS enabled flag |
| `cookies_enabled` | BOOLEAN | YES | Cookies enabled flag |
| `local_storage_enabled` | BOOLEAN | YES | LocalStorage enabled |
| `custom_dimension_1` | VARCHAR(200) | YES | Custom dimension 1 |
| `custom_dimension_2` | VARCHAR(200) | YES | Custom dimension 2 |
| `custom_dimension_3` | VARCHAR(200) | YES | Custom dimension 3 |
| `custom_dimension_4` | VARCHAR(200) | YES | Custom dimension 4 |
| `custom_dimension_5` | VARCHAR(200) | YES | Custom dimension 5 |

---

### 11. `visitors` (Primary Key: `id`)
**Purpose:** Long-term visitor profiles with aggregated metrics.

**Row Count:** 0 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | VARCHAR(64) | NO | **PK** - Visitor UUID |
| `first_seen` | TIMESTAMPTZ | YES | First visit |
| `last_seen` | TIMESTAMPTZ | YES | Last visit |
| `total_visits` | INTEGER | YES | Total visits |
| `total_pageviews` | INTEGER | YES | Total page views |
| `total_events` | INTEGER | YES | Total events |
| `is_returning` | BOOLEAN | YES | Returning visitor flag |
| `visitor_type` | VARCHAR(50) | YES | Visitor classification |
| `primary_ip` | VARCHAR(45) | YES | Primary IP address |
| `primary_user_agent` | VARCHAR(1000) | YES | Primary user agent |
| `primary_country` | VARCHAR(2) | YES | Primary country |
| `primary_city` | VARCHAR(100) | YES | Primary city |
| `countries_visited_from` | JSON | YES | Countries array |
| `browser_fingerprint` | VARCHAR(64) | YES | Browser fingerprint |
| `screen_resolution` | VARCHAR(20) | YES | Screen resolution |
| `color_depth` | INTEGER | YES | Color depth |
| `timezone_offset` | INTEGER | YES | Timezone offset |
| `timezone_name` | VARCHAR(50) | YES | Timezone name |
| `device_type` | VARCHAR(20) | YES | Device type |
| `browser_name` | VARCHAR(50) | YES | Browser name |
| `browser_version` | VARCHAR(50) | YES | Browser version |
| `os_name` | VARCHAR(50) | YES | OS name |
| `os_version` | VARCHAR(50) | YES | OS version |
| `avg_session_duration` | DOUBLE PRECISION | YES | Average session duration |
| `avg_pages_per_session` | DOUBLE PRECISION | YES | Pages per session |
| `total_session_duration` | DOUBLE PRECISION | YES | Total session time |
| `bounce_rate` | DOUBLE PRECISION | YES | Bounce rate |
| `custom_attributes` | JSON | YES | Custom attributes |

---

### 12. `crawler_patterns` (Primary Key: `id`)
**Purpose:** Bot/crawler detection patterns for identifying bots by user agent.

**Row Count:** 0 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | **PK** - Auto-increment ID |
| `crawler_name` | VARCHAR(100) | NO | Crawler name (e.g., `GoogleBot`) |
| `user_agent_pattern` | VARCHAR(500) | NO | Regex pattern to match user agent |
| `description` | TEXT | YES | Description of crawler |
| `is_active` | BOOLEAN | YES | Active flag |
| `confidence_score` | DOUBLE PRECISION | YES | Detection confidence |
| `created_at` | TIMESTAMPTZ | YES | Creation time |
| `updated_at` | TIMESTAMPTZ | YES | Update time |
| `ip_ranges` | JSON | YES | Known IP ranges |
| `request_headers` | JSON | YES | Header patterns |
| `behavioral_patterns` | JSON | YES | Behavioral patterns |

---

### 13. `enhanced_crawler_patterns` (Primary Key: `id`)
**Purpose:** Extended crawler detection patterns with AI-specific metadata.

**Row Count:** 0 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | **PK** - Auto-increment ID |
| `name` | VARCHAR(100) | YES | **UNIQUE** - Pattern name |
| `crawler_type` | VARCHAR(50) | YES | Crawler type |
| `user_agent_pattern` | TEXT | YES | User agent regex |
| `ip_range_pattern` | VARCHAR(100) | YES | IP range pattern |
| `request_pattern` | JSON | YES | Request patterns |
| `confidence_weight` | DOUBLE PRECISION | YES | Confidence weight |
| `is_active` | BOOLEAN | YES | Active flag |
| `created_at` | TIMESTAMPTZ | YES | Creation time |
| `last_detected` | TIMESTAMPTZ | YES | Last detection |
| `detection_count` | INTEGER | YES | Detection count |
| `ai_company` | VARCHAR(100) | YES | AI company (OpenAI, Anthropic, etc.) |
| `ai_purpose` | VARCHAR(100) | YES | Purpose (training, search, etc.) |
| `data_collection_scope` | VARCHAR(200) | YES | Data collection scope |

---

### 14. `crawler_visit_logs` (Primary Key: `id`)
**Purpose:** Detailed logs of crawler/bot visits for analysis.

**Row Count:** 0 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | **PK** - Auto-increment ID |
| `timestamp` | TIMESTAMPTZ | YES | Visit timestamp |
| `crawler_name` | VARCHAR(100) | YES | Crawler name |
| `crawler_type` | VARCHAR(50) | YES | Crawler type |
| `crawler_confidence` | DOUBLE PRECISION | YES | Detection confidence |
| `user_agent` | TEXT | YES | User agent string |
| `page_url` | TEXT | YES | Visited URL |
| `page_title` | VARCHAR(500) | YES | Page title |
| `page_domain` | VARCHAR(255) | YES | Domain |
| `page_path` | VARCHAR(1000) | YES | Path |
| `page_query_params` | JSON | YES | Query params |
| `tracking_id` | VARCHAR(255) | YES | Tracking ID |
| `session_id` | VARCHAR(64) | YES | Session ID |
| `ip_address` | VARCHAR(45) | YES | IP address |
| `country` | VARCHAR(2) | YES | Country code |
| `city` | VARCHAR(100) | YES | City |
| `referrer` | TEXT | YES | Referrer |
| `request_method` | VARCHAR(10) | YES | HTTP method |
| `request_headers` | JSON | YES | Request headers |
| `response_time_ms` | INTEGER | YES | Response time |
| `visit_id` | INTEGER | YES | **FK** → `visits.id` |
| `content_category` | VARCHAR(100) | YES | Content category |
| `content_tags` | JSON | YES | Content tags |
| `page_depth` | INTEGER | YES | Page depth |
| `session_page_number` | INTEGER | YES | Page number in session |
| `ai_model_version` | VARCHAR(50) | YES | AI model version |
| `ai_training_phase` | VARCHAR(50) | YES | Training phase |
| `potential_dataset_usage` | BOOLEAN | YES | Potential training data |

---

### 15. `analytics_summary` (Primary Key: `id`)
**Purpose:** Pre-aggregated analytics data for dashboard performance.

**Row Count:** 0 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGINT | NO | **PK** - Auto-increment ID |
| `date` | TIMESTAMPTZ | NO | Summary date |
| `hour` | INTEGER | YES | Hour (0-23) |
| `crawler_type` | VARCHAR(100) | YES | Crawler type |
| `country` | VARCHAR(2) | YES | Country code |
| `domain` | VARCHAR(200) | YES | Domain |
| `visit_count` | BIGINT | YES | Visit count |
| `unique_sessions` | INTEGER | YES | Unique sessions |
| `unique_ips` | INTEGER | YES | Unique IPs |
| `total_requests` | BIGINT | YES | Total requests |
| `avg_response_time` | DOUBLE PRECISION | YES | Average response time |
| `error_count` | INTEGER | YES | Error count |
| `bandwidth_bytes` | BIGINT | YES | Bandwidth used |
| `unique_pages` | INTEGER | YES | Unique pages visited |
| `bounce_rate` | DOUBLE PRECISION | YES | Bounce rate |
| `created_at` | TIMESTAMPTZ | YES | Creation time |

---

### 16. `analytics_alerts` (Primary Key: `id`)
**Purpose:** Analytics alerts for anomaly detection.

**Row Count:** 0 rows

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | NO | **PK** - Auto-increment ID |
| `timestamp` | TIMESTAMPTZ | YES | Alert timestamp |
| `alert_type` | VARCHAR(50) | YES | Alert type |
| `severity` | VARCHAR(20) | YES | Severity level |
| `title` | VARCHAR(200) | YES | Alert title |
| `description` | TEXT | YES | Alert description |
| `affected_pages` | JSON | YES | Affected pages |
| `crawler_types` | JSON | YES | Crawler types involved |
| `visit_count` | INTEGER | YES | Related visit count |
| `time_window_minutes` | INTEGER | YES | Time window |
| `threshold_exceeded` | DOUBLE PRECISION | YES | Threshold value |
| `is_acknowledged` | BOOLEAN | YES | Acknowledged flag |
| `acknowledged_at` | TIMESTAMPTZ | YES | Acknowledgement time |
| `acknowledged_by` | VARCHAR(100) | YES | Who acknowledged |
| `context_data` | JSON | YES | Additional context |

---

### 17. `alembic_version` (Primary Key: `version_num`)
**Purpose:** Database migration version tracking for Alembic.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `version_num` | VARCHAR(32) | NO | **PK** - Migration version |

---

## Foreign Key Relationships

```
crawler_visit_logs.visit_id    → visits.id
funnel_configs.user_id         → users.id
tracking_events.visit_id       → visits.id
tracking_metadata.created_by   → users.id
visit_events.session_id        → visit_sessions.id
visit_events.visit_id          → visits.id
visits.session_id              → visit_sessions.id
```

---

## Entity Relationship Diagram (Logical)

```
users (1) ─────────── (*) funnel_configs
  │
  └──────────────────── (*) tracking_metadata

visit_sessions (1) ─── (*) visits ─── (*) visit_events
                                  │
                                  └─── (*) tracking_events
                                  │
                                  └─── (*) crawler_visit_logs

visit_events (1) ─────── (*) journey_form_fills

[Materialized Views / Summaries]
client_id ──── journey_summaries
           └── lead_summaries
```

---

## Indexes

### visit_sessions
- `visit_sessions_pkey` (id) - PRIMARY KEY
- `ix_visit_sessions_client_id` (client_id)
- `ix_visit_sessions_client_id_last_visit` (client_id, last_visit)
- `ix_visit_sessions_crawler_type` (crawler_type)
- `ix_visit_sessions_ip_address` (ip_address)
- `idx_sessions_client_last_visit` (client_id, last_visit DESC)
- `idx_sessions_crawler_first_visit` (crawler_type, first_visit)

### visits
- `visits_pkey` (id) - PRIMARY KEY
- `ix_visits_client_id` (client_id)
- `ix_visits_client_id_timestamp` (client_id, timestamp)
- `ix_visits_timestamp` (timestamp)
- `ix_visits_crawler_type` (crawler_type)
- `ix_visits_page_domain` (page_domain)
- `ix_visits_page_url` (page_url)
- `ix_visits_session_id` (session_id)
- `ix_visits_tracking_id` (tracking_id)
- `ix_visits_ip_address` (ip_address)
- `ix_visits_country` (country)
- `ix_visits_is_bot` (is_bot)
- `idx_visits_client_timestamp` (client_id, timestamp DESC)
- `idx_visits_domain_timestamp` (page_domain, timestamp)
- `idx_visits_ip_timestamp` (ip_address, timestamp)
- `idx_visits_timestamp_crawler` (timestamp, crawler_type)

### visit_events
- `visit_events_pkey` (id) - PRIMARY KEY
- `ix_visit_events_client_id` (client_id)
- `ix_visit_events_client_id_timestamp` (client_id, timestamp)
- `ix_visit_events_timestamp` (timestamp)
- `ix_visit_events_event_type` (event_type)
- `ix_visit_events_session_id` (session_id)
- `ix_visit_events_visit_id` (visit_id)
- `ix_visit_events_page_domain` (page_domain)
- `ix_visit_events_page_url` (page_url)
- `ix_visit_events_tracking_id` (tracking_id)
- `ix_visit_events_source` (source)
- `ix_visit_events_medium` (medium)
- `ix_visit_events_campaign` (campaign)
- `ix_visit_events_referrer_domain` (referrer_domain)
- `idx_events_client_timestamp` (client_id, timestamp DESC)

### journey_summaries
- `journey_summaries_pkey` (client_id) - PRIMARY KEY
- `ix_journey_summaries_client_id` (client_id)
- `ix_journey_summaries_email` (email)
- `ix_journey_summaries_last_seen` (last_seen)

### lead_summaries
- `lead_summaries_pkey` (client_id) - PRIMARY KEY
- `ix_lead_summaries_client_id` (client_id)
- `ix_lead_summaries_email` (email)
- `ix_lead_summaries_name` (name)
- `ix_lead_summaries_captured_at` (captured_at)
- `ix_lead_summaries_source` (source)

### journey_form_fills
- `journey_form_fills_pkey` (id) - PRIMARY KEY
- `ix_journey_form_fills_client_id` (client_id)
- `ix_journey_form_fills_timestamp` (timestamp)
- `ix_journey_form_fills_client_timestamp` (client_id, timestamp)

### users
- `users_pkey` (id) - PRIMARY KEY
- `ix_users_username` (username) - UNIQUE
- `ix_users_email` (email) - UNIQUE
- `ix_users_api_key` (api_key) - UNIQUE

---

## Common Query Patterns

### Get all visits for a specific client
```sql
SELECT * FROM visits 
WHERE client_id = 'uuid-here' 
ORDER BY timestamp DESC;
```

### Get visitor journey with events
```sql
SELECT ve.*, v.page_title, v.source, v.medium
FROM visit_events ve
LEFT JOIN visits v ON ve.visit_id = v.id
WHERE ve.client_id = 'uuid-here'
ORDER BY ve.timestamp;
```

### Get form submissions by date range
```sql
SELECT * FROM journey_form_fills 
WHERE timestamp BETWEEN '2026-01-01' AND '2026-02-01'
ORDER BY timestamp DESC;
```

### Get bot traffic summary
```sql
SELECT crawler_type, COUNT(*) as visit_count, 
       MIN(timestamp) as first_seen, MAX(timestamp) as last_seen
FROM visits 
WHERE crawler_type IS NOT NULL
GROUP BY crawler_type
ORDER BY visit_count DESC;
```

### Get traffic sources
```sql
SELECT source, medium, campaign, COUNT(*) as visits
FROM visits 
WHERE source IS NOT NULL
GROUP BY source, medium, campaign
ORDER BY visits DESC;
```

### Get page view funnel
```sql
SELECT path, event_type, COUNT(*) as event_count
FROM visit_events
WHERE path LIKE '/demo%' OR path LIKE '/sign-up%'
GROUP BY path, event_type
ORDER BY path, event_count DESC;
```

### Get lead capture data
```sql
SELECT ls.client_id, ls.email, ls.name, ls.captured_at,
       ls.source, ls.campaign, js.path_sequence
FROM lead_summaries ls
LEFT JOIN journey_summaries js ON ls.client_id = js.client_id
WHERE ls.email IS NOT NULL
ORDER BY ls.captured_at DESC;
```

### Get events by type in time range
```sql
SELECT event_type, DATE_TRUNC('hour', timestamp) as hour, COUNT(*)
FROM visit_events
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY event_type, DATE_TRUNC('hour', timestamp)
ORDER BY hour DESC, event_type;
```

### Get unique visitors per day
```sql
SELECT DATE_TRUNC('day', timestamp) as day,
       COUNT(DISTINCT client_id) as unique_visitors,
       COUNT(*) as total_visits
FROM visits
WHERE timestamp > NOW() - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', timestamp)
ORDER BY day DESC;
```

### Get top pages by visits
```sql
SELECT path, page_domain, COUNT(*) as visits,
       COUNT(DISTINCT client_id) as unique_visitors
FROM visits
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY path, page_domain
ORDER BY visits DESC
LIMIT 20;
```

### Get visitor path analysis
```sql
SELECT js.client_id, js.entry_page, js.exit_page, 
       js.visit_count, js.path_sequence,
       js.source, js.campaign
FROM journey_summaries js
WHERE js.last_seen > NOW() - INTERVAL '7 days'
ORDER BY js.visit_count DESC
LIMIT 100;
```

### Get scroll depth analysis
```sql
SELECT path,
       AVG((event_data->>'percent')::int) as avg_scroll_percent,
       MAX((event_data->>'percent')::int) as max_scroll_percent,
       COUNT(*) as scroll_events
FROM visit_events
WHERE event_type = 'scroll'
  AND timestamp > NOW() - INTERVAL '7 days'
GROUP BY path
ORDER BY avg_scroll_percent DESC;
```

### Get conversion funnel (page to form submit)
```sql
WITH page_visitors AS (
    SELECT DISTINCT client_id
    FROM visit_events
    WHERE path = '/demo'
      AND event_type = 'page_view'
      AND timestamp > NOW() - INTERVAL '30 days'
),
form_submitters AS (
    SELECT DISTINCT client_id
    FROM visit_events
    WHERE path = '/demo'
      AND event_type = 'form_submit'
      AND timestamp > NOW() - INTERVAL '30 days'
)
SELECT 
    (SELECT COUNT(*) FROM page_visitors) as page_visitors,
    (SELECT COUNT(*) FROM form_submitters) as form_submitters,
    ROUND(100.0 * (SELECT COUNT(*) FROM form_submitters) / 
          NULLIF((SELECT COUNT(*) FROM page_visitors), 0), 2) as conversion_rate;
```

---

## Data Flow Summary

1. **Visitor arrives** → `visit_sessions` created/updated (keyed by IP + UA hash)
2. **Page loads** → `visits` record created with full request details
3. **User interacts** → `visit_events` records created (scroll, click, form_input, etc.)
4. **Form submitted** → `journey_form_fills` captures form data
5. **Background job** → Updates `journey_summaries` and `lead_summaries` aggregates

The `client_id` (UUID stored in browser localStorage) is the primary key for tracking individual users across sessions.
