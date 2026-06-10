"""Simplified analytics service for visitor categorization and page tracking."""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
import json
from urllib.parse import urlparse, parse_qs
from sqlalchemy.orm import Session, aliased
from sqlalchemy import func, desc, text, and_, select, case, or_
from sqlalchemy.exc import OperationalError, TimeoutError as SQLTimeoutError
import structlog
import time

from app.models.visit import Visit, VisitSession, VisitEvent
from app.models.funnel import FunnelConfig
from app.models.summary import LeadSummary, JourneySummary, JourneyFormFill
from app.config import settings

logger = structlog.get_logger()

# Keys that indicate user-provided form data (not analytics/RUM junk)
MEANINGFUL_FORM_KEYS = frozenset([
    "email", "name", "company", "message", "phone", "organization",
    "user_email", "full_name", "company_name", "first_name", "last_name",
    "subject", "comments", "inquiry", "body",
])


def is_real_form_submit(event_data: Optional[Dict[str, Any]]) -> bool:
    """True if event_data is a real form submission with user-provided data (not RUM/analytics noise)."""
    if not event_data or not isinstance(event_data, dict):
        return False
    data_str = str(event_data)
    if any(k in data_str for k in ("timingsV2", "memory.totalJSHeapSize", "eventType", '"data":')):
        return False
    if len(data_str) > 5000:
        return False
    form_vals = event_data.get("form_values") or event_data.get("values")
    if not form_vals or not isinstance(form_vals, dict):
        return False
    
    # Reject empty form_values (must have actual data, not just filled_fields count)
    if len(form_vals) == 0:
        return False
    
    # Reject search/query forms (query, search, page_size, filters, highlight_options, etc.)
    search_keys = ['query', 'search', 'page_size', 'group_size', 'search_type', 'score_threshold', 
                   'highlight_options', 'filters.must_not', 'extend_results']
    if any(k in form_vals for k in search_keys):
        return False
    
    # Reject forms with only 'events' and 'timestamp' (analytics payloads like {events: "[object Object]", timestamp: "..."})
    if set(form_vals.keys()) == {'events', 'timestamp'}:
        return False
    if len(form_vals) <= 2 and 'events' in form_vals and '[object Object]' in str(form_vals.get('events', '')):
        return False
    
    # Reject forms with only 'data' key containing long/base64 payloads (PostHog, analytics)
    if len(form_vals) == 1 and 'data' in form_vals:
        data_val = str(form_vals.get('data', ''))
        if len(data_val) > 200 or data_val.startswith('eyJ'):
            return False
    
    # Reject if all values look like tokens/analytics (long base64-like strings)
    suspicious_values = 0
    for k, v in form_vals.items():
        val_str = str(v)
        if len(val_str) > 200 and (val_str.startswith('eyJ') or val_str.startswith('phc_')):
            suspicious_values += 1
    if suspicious_values >= len(form_vals):
        return False
    
    meaningful = [k for k in form_vals if k and str(k).lower() in MEANINGFUL_FORM_KEYS]
    if meaningful:
        return True
    if any("email" in str(k).lower() or "name" in str(k).lower() or "company" in str(k).lower() for k in form_vals):
        return True
    return event_data.get("filled_fields", 0) >= 1

DEFAULT_FUNNEL_CONFIG = {
    "funnels": [
        {
            "key": "demo_to_schedule",
            "label": "Any Page → /demo → Form Submit → /schedule",
            "steps": [
                {"label": "Visited /demo", "type": "page", "path": "/demo"},
                {"label": "Submitted form", "type": "event", "path": "/demo", "event_type": "form_submit"},
                {"label": "Visited /schedule", "type": "page", "path": "/schedule"},
            ],
        },
        {
            "key": "signup",
            "label": "Any Page → /sign-up → Form Submit",
            "steps": [
                {"label": "Visited /sign-up", "type": "page", "path": "/sign-up"},
                {"label": "Submitted form", "type": "event", "path": "/sign-up", "event_type": "form_submit"},
            ],
        },
        {
            "key": "bifrost_book_a_demo",
            "label": "Any Page → /bifrost/book-a-demo → Form Submit",
            "steps": [
                {"label": "Visited /bifrost/book-a-demo", "type": "page", "path": "/bifrost/book-a-demo"},
                {"label": "Submitted form", "type": "event", "path": "/bifrost/book-a-demo", "event_type": "form_submit"},
            ],
        },
        {
            "key": "bifrost_enterprise",
            "label": "Any Bifrost Page → Enterprise Trial Form Submit",
            "steps": [
                {"label": "Visited Bifrost page", "type": "page", "path": "/bifrost/"},
                {"label": "Submitted Enterprise Trial form", "type": "event", "path": "/bifrost/", "event_type": "form_submit"},
            ],
        },
    ]
}


class AnalyticsService:
    """Simplified analytics service for visitor insights."""
    
    def get_visitor_summary(
        self,
        db: Session,
        days: int = 30,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get summary of visitors by category using optimized single-pass aggregation."""
        if start_date or end_date:
            since = start_date or (datetime.now(timezone.utc) - timedelta(days=days))
            until = end_date
        else:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            until = None
        
        # Optimized: Single query for all visit counts using conditional aggregation
        filters = [Visit.timestamp >= since]
        if until:
            filters.append(Visit.timestamp <= until)
        
        stats = db.query(
            func.count(Visit.id).label('total'),
            func.count(func.distinct(func.coalesce(Visit.client_id, Visit.session_id))).label('unique_visitors'),
            func.sum(case((Visit.is_bot == True, 1), else_=0)).label('ai_crawlers'),
            func.sum(case((and_(Visit.is_bot == False, Visit.user_agent.ilike('%mobile%')), 1), else_=0)).label('mobile_humans'),
            func.sum(case((and_(Visit.is_bot == False, ~Visit.user_agent.ilike('%mobile%')), 1), else_=0)).label('desktop_humans')
        ).filter(*filters).first()

        total_visits = stats.total or 0
        unique_visitors = stats.unique_visitors or 0

        # NEW: Get conversion count (form_submit) for this period
        event_filters = [VisitEvent.timestamp >= since]
        if until:
            event_filters.append(VisitEvent.timestamp <= until)
            
        conversions = db.query(
            func.count(func.distinct(func.coalesce(VisitEvent.client_id, VisitEvent.session_id)))
        ).filter(
            *event_filters,
            VisitEvent.event_type == 'form_submit'
        ).scalar() or 0
        
        visits_by_category = [
            {'category': 'AI Crawlers', 'count': int(stats.ai_crawlers or 0)},
            {'category': 'Mobile Humans', 'count': int(stats.mobile_humans or 0)},
            {'category': 'Desktop Humans', 'count': int(stats.desktop_humans or 0)}
        ]
        
        # Get top user agents
        top_user_agents_query = db.query(
            Visit.user_agent,
            func.count(Visit.id).label('count')
        ).filter(*filters)
        
        top_user_agents = top_user_agents_query.group_by(Visit.user_agent).order_by(
            desc('count')
        ).limit(10).all()

        # Top sources and campaigns
        top_sources = db.query(
            Visit.source,
            func.count(Visit.id).label('count')
        ).filter(*filters).group_by(Visit.source).order_by(desc('count')).limit(5).all()

        top_campaigns = db.query(
            Visit.campaign,
            func.count(Visit.id).label('count')
        ).filter(*filters).group_by(Visit.campaign).order_by(desc('count')).limit(5).all()
        
        return {
            "total_visits": total_visits,
            "unique_visitors": unique_visitors,
            "conversions": conversions,
            "conversion_rate": round((conversions / unique_visitors * 100), 2) if unique_visitors > 0 else 0,
            "visits_by_category": visits_by_category,
            "top_sources": [
                {"source": row.source or "direct", "count": row.count}
                for row in top_sources
            ],
            "top_campaigns": [
                {"campaign": row.campaign or "none", "count": row.count}
                for row in top_campaigns
            ],
            "top_user_agents": [
                {"user_agent": row.user_agent[:100], "count": row.count}
                for row in top_user_agents
            ],
            "period_days": days
        }

    def _step_uid_ts_subquery(
        self,
        db: Session,
        step: Dict[str, Any],
        start_date: Optional[datetime],
        end_date: Optional[datetime],
    ):
        """Return a subquery of (uid, min_ts) for a single funnel step."""
        step_type = step.get("type", "page")
        path = step.get("path", "")

        if step_type == "event":
            event_type = step.get("event_type", "form_submit")
            uid_col = func.coalesce(VisitEvent.client_id, VisitEvent.session_id)
            q = db.query(
                uid_col.label("uid"),
                func.min(VisitEvent.timestamp).label("min_ts"),
            )
            if start_date:
                q = q.filter(VisitEvent.timestamp >= start_date)
            if end_date:
                q = q.filter(VisitEvent.timestamp <= end_date)
            q = q.filter(VisitEvent.event_type == event_type)
            q = q.filter(VisitEvent.path.ilike(f"{path}%"))
            q = q.filter(text("event_data::text NOT LIKE '%timingsV2%'"))
            q = q.filter(text("event_data::text NOT LIKE '%memory.totalJSHeapSize%'"))
            q = q.filter(text("event_data::text NOT LIKE '%eventType%'"))
        else:
            uid_col = func.coalesce(Visit.client_id, Visit.session_id)
            q = db.query(
                uid_col.label("uid"),
                func.min(Visit.timestamp).label("min_ts"),
            )
            if start_date:
                q = q.filter(Visit.timestamp >= start_date)
            if end_date:
                q = q.filter(Visit.timestamp <= end_date)
            q = q.filter(Visit.path.ilike(f"{path}%"))

        return q.group_by(uid_col).subquery()

    def get_funnel_summary(
        self,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Get funnel summary with strict temporal ordering between steps."""

        funnels = (config or DEFAULT_FUNNEL_CONFIG).get("funnels", [])
        funnel_results = []

        for funnel in funnels:
            steps = funnel.get("steps", [])
            stages = []
            prev_sub = None

            for step in steps:
                label = step.get("label") or step.get("path") or step.get("type", "page")
                cur_sub = self._step_uid_ts_subquery(db, step, start_date, end_date)

                if prev_sub is None:
                    # First step — count all unique users
                    count = db.execute(
                        select(func.count()).select_from(cur_sub)
                    ).scalar() or 0
                else:
                    # Subsequent steps — only users present in the previous step
                    # whose step-N min_ts >= step-(N-1) min_ts (temporal ordering).
                    joined = (
                        select(cur_sub.c.uid, cur_sub.c.min_ts)
                        .join(prev_sub, cur_sub.c.uid == prev_sub.c.uid)
                        .where(cur_sub.c.min_ts >= prev_sub.c.min_ts)
                        .subquery()
                    )
                    count = db.execute(
                        select(func.count()).select_from(joined)
                    ).scalar() or 0
                    # Use the joined result (with filtered users) as the base for
                    # the next step so the temporal chain is maintained.
                    cur_sub = joined

                prev_sub = cur_sub
                stages.append({
                    "label": label,
                    "count": count,
                    "type": step.get("type", "page"),
                    "path": step.get("path", ""),
                })

            # Calculate rates
            rates = []
            for idx in range(1, len(stages)):
                prev_count = stages[idx - 1]["count"]
                current_count = stages[idx]["count"]
                dropoff_count = max(prev_count - current_count, 0)
                rate = round((current_count / prev_count) * 100, 2) if prev_count else 0
                rates.append({
                    "label": f"{stages[idx - 1]['label']} → {stages[idx]['label']}",
                    "rate": rate,
                    "dropoff_count": dropoff_count,
                })

            funnel_results.append({
                "key": funnel.get("key"),
                "label": funnel.get("label") or funnel.get("key"),
                "stages": stages,
                "rates": rates,
            })

        return {"funnels": funnel_results}

    def get_funnel_time_metrics(
        self,
        db: Session,
        funnel_key: str,
        config: Dict[str, Any],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_rows: int = 5000,
    ) -> Dict[str, Any]:
        """Compute time-to-convert metrics for funnel steps."""
        funnels = config.get("funnels", [])
        funnel = next((f for f in funnels if f.get("key") == funnel_key), None)
        if not funnel:
            return {"error": "not_found"}

        visit_filters = [Visit.client_id.isnot(None)]
        event_filters = [VisitEvent.client_id.isnot(None)]
        if start_date:
            visit_filters.append(Visit.timestamp >= start_date)
            event_filters.append(VisitEvent.timestamp >= start_date)
        if end_date:
            visit_filters.append(Visit.timestamp <= end_date)
            event_filters.append(VisitEvent.timestamp <= end_date)

        def step_min_ts(step: Dict[str, Any]):
            step_type = step.get("type", "page")
            path = step.get("path", "")
            if step_type == "event":
                event_type = step.get("event_type", "form_submit")
                return (
                    db.query(
                        VisitEvent.client_id.label("client_id"),
                        func.min(VisitEvent.timestamp).label("ts"),
                    )
                    .filter(
                        *event_filters,
                        VisitEvent.event_type == event_type,
                        VisitEvent.path.ilike(f"{path}%"),
                    )
                    .group_by(VisitEvent.client_id)
                    .subquery()
                )
            return (
                db.query(
                    Visit.client_id.label("client_id"),
                    func.min(Visit.timestamp).label("ts"),
                )
                .filter(
                    *visit_filters,
                    Visit.path.ilike(f"{path}%"),
                )
                .group_by(Visit.client_id)
                .subquery()
            )

        def percentile(values: list[float], pct: float) -> float:
            if not values:
                return 0.0
            values_sorted = sorted(values)
            k = max(int(len(values_sorted) * pct) - 1, 0)
            return round(values_sorted[k], 2)

        steps = funnel.get("steps", [])
        transitions = []
        for idx in range(len(steps) - 1):
            step_a = steps[idx]
            step_b = steps[idx + 1]
            sub_a = step_min_ts(step_a)
            sub_b = step_min_ts(step_b)

            rows = (
                db.query(sub_a.c.client_id, sub_a.c.ts.label("ts_a"), sub_b.c.ts.label("ts_b"))
                .join(sub_b, sub_a.c.client_id == sub_b.c.client_id)
                .filter(sub_b.c.ts >= sub_a.c.ts)
                .order_by(sub_b.c.ts.asc())
                .limit(max_rows)
                .all()
            )

            deltas = [(row.ts_b - row.ts_a).total_seconds() for row in rows]
            if deltas:
                avg = round(sum(deltas) / len(deltas), 2)
            else:
                avg = 0.0
            transitions.append({
                "from": step_a.get("label") or step_a.get("path"),
                "to": step_b.get("label") or step_b.get("path"),
                "sample_size": len(deltas),
                "avg_seconds": avg,
                "median_seconds": percentile(deltas, 0.5),
                "p90_seconds": percentile(deltas, 0.9),
            })

        return {
            "funnel_key": funnel_key,
            "label": funnel.get("label"),
            "transitions": transitions,
            "max_rows": max_rows,
        }

    def get_funnel_dropoffs(
        self,
        db: Session,
        funnel_key: str,
        step_index: int,
        config: Dict[str, Any],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        funnels = config.get("funnels", [])
        funnel = next((f for f in funnels if f.get("key") == funnel_key), None)
        if not funnel:
            return {"error": "not_found"}

        steps = funnel.get("steps", [])
        if step_index < 0 or step_index >= len(steps) - 1:
            return {"error": "invalid_step"}

        visit_filters = [Visit.client_id.isnot(None)]
        event_filters = [VisitEvent.client_id.isnot(None)]
        if start_date:
            visit_filters.append(Visit.timestamp >= start_date)
            event_filters.append(VisitEvent.timestamp >= start_date)
        if end_date:
            visit_filters.append(Visit.timestamp <= end_date)
            event_filters.append(VisitEvent.timestamp <= end_date)

        def step_ids(step: Dict[str, Any]):
            step_type = step.get("type", "page")
            path = step.get("path", "")
            if step_type == "event":
                event_type = step.get("event_type", "form_submit")
                return (
                    db.query(VisitEvent.client_id.label("client_id"))
                    .filter(
                        *event_filters,
                        VisitEvent.event_type == event_type,
                        VisitEvent.path.ilike(f"{path}%"),
                    )
                    .distinct()
                    .subquery()
                )
            return (
                db.query(Visit.client_id.label("client_id"))
                .filter(
                    *visit_filters,
                    Visit.path.ilike(f"{path}%"),
                )
                .distinct()
                .subquery()
            )

        step_a = step_ids(steps[step_index])
        step_b = step_ids(steps[step_index + 1])

        dropoff_query = (
            db.query(step_a.c.client_id)
            .outerjoin(step_b, step_a.c.client_id == step_b.c.client_id)
            .filter(step_b.c.client_id.is_(None))
        )
        total = dropoff_query.count()
        dropoff_ids = [row[0] for row in dropoff_query.offset(offset).limit(limit).all()]

        if not dropoff_ids:
            return {"users": [], "total": total, "limit": limit, "offset": offset}

        first_visit_subq = (
            db.query(
                Visit.client_id.label("client_id"),
                func.min(Visit.timestamp).label("first_ts"),
            )
            .filter(Visit.client_id.in_(dropoff_ids))
            .group_by(Visit.client_id)
            .subquery()
        )

        last_visit_subq = (
            db.query(
                Visit.client_id.label("client_id"),
                func.max(Visit.timestamp).label("last_ts"),
            )
            .filter(Visit.client_id.in_(dropoff_ids))
            .group_by(Visit.client_id)
            .subquery()
        )

        first_visits = (
            db.query(Visit)
            .join(first_visit_subq, and_(Visit.client_id == first_visit_subq.c.client_id, Visit.timestamp == first_visit_subq.c.first_ts))
            .all()
        )

        last_visits = (
            db.query(Visit)
            .join(last_visit_subq, and_(Visit.client_id == last_visit_subq.c.client_id, Visit.timestamp == last_visit_subq.c.last_ts))
            .all()
        )

        last_map = {visit.client_id: visit for visit in last_visits}

        users = []
        for visit in first_visits:
            last = last_map.get(visit.client_id)
            users.append({
                "client_id": visit.client_id,
                "first_seen": visit.timestamp.isoformat() if visit.timestamp else None,
                "last_seen": last.timestamp.isoformat() if last and last.timestamp else None,
                "source": visit.source or "direct",
                "medium": visit.medium or "none",
                "campaign": visit.campaign or "none",
                "entry_page": visit.page_url,
            })

        return {"users": users, "total": total, "limit": limit, "offset": offset}

    def get_funnel_stage_users(
        self,
        db: Session,
        funnel_key: str,
        step_index: int,
        config: Dict[str, Any],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        funnels = config.get("funnels", [])
        funnel = next((f for f in funnels if f.get("key") == funnel_key), None)
        if not funnel:
            return {"error": "not_found"}

        steps = funnel.get("steps", [])
        if step_index < 0 or step_index >= len(steps):
            return {"error": "invalid_step"}

        visit_filters = [Visit.client_id.isnot(None)]
        event_filters = [VisitEvent.client_id.isnot(None)]
        if start_date:
            visit_filters.append(Visit.timestamp >= start_date)
            event_filters.append(VisitEvent.timestamp >= start_date)
        if end_date:
            visit_filters.append(Visit.timestamp <= end_date)
            event_filters.append(VisitEvent.timestamp <= end_date)

        def step_ids(step: Dict[str, Any], current_ids=None):
            step_type = step.get("type", "page")
            path = step.get("path", "")
            if step_type == "event":
                event_type = step.get("event_type", "form_submit")
                client_col = VisitEvent.client_id
                query = db.query(client_col.label("client_id")).filter(
                    *event_filters,
                    VisitEvent.event_type == event_type,
                    VisitEvent.path.ilike(f"{path}%"),
                )
            else:
                client_col = Visit.client_id
                query = db.query(client_col.label("client_id")).filter(
                    *visit_filters,
                    Visit.path.ilike(f"{path}%"),
                )

            if current_ids is not None:
                query = query.filter(client_col.in_(select(current_ids.c.client_id)))

            return query.distinct().subquery()

        current_ids = None
        for step in steps[: step_index + 1]:
            current_ids = step_ids(step, current_ids)

        if current_ids is None:
            return {"users": [], "total": 0, "limit": limit, "offset": offset}

        total = db.query(func.count()).select_from(current_ids).scalar() or 0
        stage_rows = (
            db.query(current_ids.c.client_id)
            .order_by(current_ids.c.client_id.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        client_ids = [row[0] for row in stage_rows]

        if not client_ids:
            return {"users": [], "total": total, "limit": limit, "offset": offset}

        stage_step = steps[step_index]
        stage_seen_map: Dict[str, datetime] = {}
        stage_type = stage_step.get("type", "page")
        stage_path = stage_step.get("path", "")
        if stage_type == "event":
            event_type = stage_step.get("event_type", "form_submit")
            stage_times = (
                db.query(
                    VisitEvent.client_id.label("client_id"),
                    func.min(VisitEvent.timestamp).label("stage_ts"),
                )
                .filter(
                    *event_filters,
                    VisitEvent.client_id.in_(client_ids),
                    VisitEvent.event_type == event_type,
                    VisitEvent.path.ilike(f"{stage_path}%"),
                )
                .group_by(VisitEvent.client_id)
                .all()
            )
        else:
            stage_times = (
                db.query(
                    Visit.client_id.label("client_id"),
                    func.min(Visit.timestamp).label("stage_ts"),
                )
                .filter(
                    *visit_filters,
                    Visit.client_id.in_(client_ids),
                    Visit.path.ilike(f"{stage_path}%"),
                )
                .group_by(Visit.client_id)
                .all()
            )

        stage_seen_map = {row.client_id: row.stage_ts for row in stage_times}

        # Batch-fetch first/last visits for all client_ids (avoids N+1)
        first_visit_subq = (
            db.query(
                Visit.client_id.label("client_id"),
                func.min(Visit.timestamp).label("first_ts"),
            )
            .filter(Visit.client_id.in_(client_ids))
        )
        last_visit_subq = (
            db.query(
                Visit.client_id.label("client_id"),
                func.max(Visit.timestamp).label("last_ts"),
            )
            .filter(Visit.client_id.in_(client_ids))
        )
        # Apply date filters to the visit lookups
        if start_date:
            first_visit_subq = first_visit_subq.filter(Visit.timestamp >= start_date)
            last_visit_subq = last_visit_subq.filter(Visit.timestamp >= start_date)
        if end_date:
            first_visit_subq = first_visit_subq.filter(Visit.timestamp <= end_date)
            last_visit_subq = last_visit_subq.filter(Visit.timestamp <= end_date)

        first_visit_subq = first_visit_subq.group_by(Visit.client_id).subquery()
        last_visit_subq = last_visit_subq.group_by(Visit.client_id).subquery()

        first_visits = (
            db.query(Visit)
            .join(first_visit_subq, and_(
                Visit.client_id == first_visit_subq.c.client_id,
                Visit.timestamp == first_visit_subq.c.first_ts,
            ))
            .all()
        )
        last_visits = (
            db.query(Visit)
            .join(last_visit_subq, and_(
                Visit.client_id == last_visit_subq.c.client_id,
                Visit.timestamp == last_visit_subq.c.last_ts,
            ))
            .all()
        )
        first_map = {v.client_id: v for v in first_visits}
        last_map = {v.client_id: v for v in last_visits}

        # Batch-fetch most recent form_submit event per client
        latest_event_subq = (
            db.query(
                VisitEvent.client_id.label("client_id"),
                func.max(VisitEvent.timestamp).label("max_ts"),
            )
            .filter(
                VisitEvent.client_id.in_(client_ids),
                VisitEvent.event_type == "form_submit",
            )
            .group_by(VisitEvent.client_id)
            .subquery()
        )
        captured_events = (
            db.query(VisitEvent)
            .join(latest_event_subq, and_(
                VisitEvent.client_id == latest_event_subq.c.client_id,
                VisitEvent.timestamp == latest_event_subq.c.max_ts,
            ))
            .filter(VisitEvent.event_type == "form_submit")
            .all()
        )
        captured_map = {e.client_id: e for e in captured_events}

        # Batch-fetch path sequences (visit paths in order, within date range)
        all_visits_q = (
            db.query(Visit.client_id, Visit.path, Visit.timestamp)
            .filter(Visit.client_id.in_(client_ids), Visit.path.isnot(None))
        )
        if start_date:
            all_visits_q = all_visits_q.filter(Visit.timestamp >= start_date)
        if end_date:
            all_visits_q = all_visits_q.filter(Visit.timestamp <= end_date)
        all_visits_rows = all_visits_q.order_by(Visit.client_id, Visit.timestamp.asc()).all()

        path_map: Dict[str, str] = {}
        from itertools import groupby as _groupby
        for cid, rows in _groupby(all_visits_rows, key=lambda r: r.client_id):
            path_map[cid] = " → ".join(r.path for r in rows if r.path)

        users = []
        for cid in client_ids:
            first = first_map.get(cid)
            last = last_map.get(cid)
            if not first:
                continue

            captured_event = captured_map.get(cid)
            captured_values = None
            captured_page = None
            captured_at = None
            if captured_event and captured_event.event_data:
                captured_values = captured_event.event_data.get("form_values") or captured_event.event_data.get("values")
                captured_page = captured_event.page_url
                captured_at = captured_event.timestamp.isoformat() if captured_event.timestamp else None

            email = None
            name = None
            if isinstance(captured_values, dict):
                for key, value in captured_values.items():
                    if not email and "email" in key.lower():
                        email = value
                    if not name and "name" in key.lower():
                        name = value

            duration_seconds = None
            if first.timestamp and last and last.timestamp:
                duration_seconds = int((last.timestamp - first.timestamp).total_seconds())

            stage_seen_at = stage_seen_map.get(cid)
            users.append({
                "client_id": cid,
                "stage_reached_at": stage_seen_at.isoformat() if stage_seen_at else None,
                "first_seen": first.timestamp.isoformat() if first.timestamp else None,
                "last_seen": last.timestamp.isoformat() if last and last.timestamp else None,
                "entry_page": first.page_url,
                "exit_page": last.page_url if last else first.page_url,
                "source": first.source or "direct",
                "medium": first.medium or "none",
                "campaign": first.campaign or "none",
                "entry_referrer": first.referrer,
                "has_captured_data": bool(captured_values),
                "captured_data": captured_values,
                "captured_page": captured_page,
                "captured_at": captured_at,
                "email": email,
                "name": name,
                "path_sequence": path_map.get(cid, ""),
                "duration_seconds": duration_seconds,
            })

        return {"users": users, "total": total, "limit": limit, "offset": offset}

    def get_funnel_config(self, db: Session, user_id: int) -> Dict[str, Any]:
        config = db.query(FunnelConfig).filter(FunnelConfig.user_id == user_id).first()
        if config:
            return config.config
        return DEFAULT_FUNNEL_CONFIG

    def save_funnel_config(self, db: Session, user_id: int, config: Dict[str, Any]) -> Dict[str, Any]:
        funnel_config = db.query(FunnelConfig).filter(FunnelConfig.user_id == user_id).first()
        if funnel_config:
            funnel_config.config = config
        else:
            funnel_config = FunnelConfig(user_id=user_id, config=config)
            db.add(funnel_config)
        db.commit()
        db.refresh(funnel_config)
        return funnel_config.config
    
    def get_page_analytics(
        self,
        db: Session,
        days: int = 30,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get analytics by page."""
        if start_date or end_date:
            since = start_date or (datetime.now(timezone.utc) - timedelta(days=days))
            until = end_date
        else:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            until = None
        
        # Get visits by page domain
        page_visits_query = db.query(
            Visit.page_domain,
            func.count(Visit.id).label('count'),
            func.count(func.distinct(func.coalesce(Visit.client_id, Visit.session_id))).label('unique_visitors')
        ).filter(
            Visit.timestamp >= since,
            Visit.page_domain.isnot(None)
        )
        if until:
            page_visits_query = page_visits_query.filter(Visit.timestamp <= until)
        page_visits = page_visits_query.group_by(Visit.page_domain).order_by(
            desc('count')
        ).limit(20).all()
        
        # Get crawler visits by page
        crawler_visits_query = db.query(
            Visit.page_domain,
            Visit.crawler_type,
            func.count(Visit.id).label('count')
        ).filter(
            Visit.timestamp >= since,
            Visit.is_bot == True,
            Visit.page_domain.isnot(None)
        )
        if until:
            crawler_visits_query = crawler_visits_query.filter(Visit.timestamp <= until)
        crawler_visits = crawler_visits_query.group_by(Visit.page_domain, Visit.crawler_type).order_by(
            desc('count')
        ).limit(20).all()
        
        return {
            "page_visits": [
                {
                    "domain": row.page_domain,
                    "total_visits": row.count,
                    "unique_visitors": row.unique_visitors
                }
                for row in page_visits
            ],
            "crawler_visits": [
                {
                    "domain": row.page_domain,
                    "crawler": row.crawler_type,
                    "count": row.count
                }
                for row in crawler_visits
            ],
            "period_days": days
        }
    
    def get_recent_activity(
        self,
        db: Session,
        limit: int = 50,
        offset: int = 0,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Get recent visitor activity with pagination - optimized for large datasets with retry logic."""
        from sqlalchemy.orm import joinedload
        
        # Default to last 7 days to avoid full table scans if no range is provided
        if not start_date and not end_date:
            start_date = datetime.now(timezone.utc) - timedelta(days=7)
        
        # Try to get data with retries
        for attempt in range(max_retries):
            try:
                # Use indexed timestamp for fast counting - limit to recent data only
                # For very large DBs, estimate count for better performance
                query = db.query(Visit).options(joinedload(Visit.session)).order_by(desc(Visit.timestamp))
                if start_date:
                    query = query.filter(Visit.timestamp >= start_date)
                if end_date:
                    query = query.filter(Visit.timestamp <= end_date)

                if offset == 0:
                    # Only get exact count on first page
                    total_count = query.order_by(None).with_entities(func.count(Visit.id)).scalar() or 0
                else:
                    # For subsequent pages, use cached estimate (10x faster)
                    total_count = offset + limit + 1000  # Rough estimate
                
                # Optimized query: eager load session to prevent N+1 queries
                recent_visits = query.offset(offset).limit(limit).all()
                
                visits_data = []
                for visit in recent_visits:
                    # Fallback to session geo if visit geo is missing
                    country = visit.country
                    city = visit.city
                    if not country and visit.session:
                        country = visit.session.country
                        city = visit.session.city
                    
                    visits_data.append({
                        "id": visit.id,
                        "timestamp": visit.timestamp.isoformat() if visit.timestamp else None,
                        "user_agent": visit.user_agent or "",
                        "page_url": visit.page_url or "",
                        "is_bot": visit.is_bot or False,
                        "crawler_type": visit.crawler_type or "",
                        "country": country or "",
                        "city": city or "",
                        "session_id": visit.session_id or "",
                        "tracking_id": visit.tracking_id or "",
                        "source": visit.source or "",
                        "medium": visit.medium or "",
                        "campaign": visit.campaign or "",
                        # Client-side captured data
                        "client_side_timezone": visit.client_side_timezone or "",
                        "client_side_language": visit.client_side_language or "",
                        "client_side_screen_resolution": visit.client_side_screen_resolution or "",
                        "client_side_viewport_size": visit.client_side_viewport_size or "",
                        "client_side_device_memory": visit.client_side_device_memory or "",
                        "client_side_connection_type": visit.client_side_connection_type or ""
                    })
                
                return {
                    "visits": visits_data,
                    "total_count": total_count,
                    "has_next": (offset + limit) < total_count,
                    "has_prev": offset > 0,
                    "current_page": (offset // limit) + 1,
                    "total_pages": ((total_count - 1) // limit) + 1 if total_count > 0 else 0
                }
            except (OperationalError, SQLTimeoutError) as e:
                logger.warning(f"Recent activity query timeout, attempt {attempt + 1}/{max_retries}", error=str(e), offset=offset)
                db.rollback()
                if attempt < max_retries - 1:
                    pass
                else:
                    logger.error("Failed to get recent activity after retries", error=str(e))
                    # Return empty result on final failure
                    return {
                        "visits": [],
                        "total_count": 0,
                        "has_next": False,
                        "has_prev": False,
                        "current_page": 1,
                        "total_pages": 0,
                        "error": "Database timeout - please try again or reduce page size"
                    }
            except Exception as e:
                logger.error("Error in get_recent_activity", error=str(e))
                # Return empty result on other errors
                return {
                    "visits": [],
                    "total_count": 0,
                    "has_next": False,
                    "has_prev": False,
                    "current_page": 1,
                    "total_pages": 0,
                    "error": str(e)
                }
        
        # Should never reach here, but just in case
        return {
            "visits": [],
            "total_count": 0,
            "has_next": False,
            "has_prev": False,
            "current_page": 1,
            "total_pages": 0
        }

    def list_sessions(self, db: Session, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """List sessions with summary info - OPTIMIZED for large datasets."""
        try:
            # Fast count with estimation for pagination
            if offset == 0:
                total = db.query(func.count(VisitSession.id)).scalar() or 0
            else:
                total = offset + limit + 100  # Estimate for speed
            
            # Single optimized query with only what we need
            sessions = db.query(VisitSession).order_by(desc(VisitSession.last_visit)).offset(offset).limit(limit).all()
            
            # Batch-fetch all visit data for these sessions in ONE query (massive speedup)
            session_ids = [s.id for s in sessions]
            if session_ids:
                # Get visit counts per session in one query
                visit_counts = dict(
                    db.query(Visit.session_id, func.count(Visit.id))
                    .filter(Visit.session_id.in_(session_ids))
                    .group_by(Visit.session_id)
                    .all()
                )
                
                # Get bot classification per session in one query
                bot_classifications = {}
                bot_data = db.query(
                    Visit.session_id, 
                    Visit.is_bot,
                    func.count(Visit.id).label('count')
                ).filter(Visit.session_id.in_(session_ids)).group_by(Visit.session_id, Visit.is_bot).all()
                
                for session_id, is_bot, count in bot_data:
                    if session_id not in bot_classifications or count > bot_classifications[session_id][1]:
                        bot_classifications[session_id] = (is_bot, count)
            else:
                visit_counts = {}
                bot_classifications = {}
            
            data = []
            for s in sessions:
                # Use cached session geo data (already populated during tracking)
                sess_country = s.country or ""
                sess_city = s.city or ""
                
                # Use batch-fetched data instead of per-session queries
                visit_count = visit_counts.get(s.id, 0)
                is_bot_session = bot_classifications.get(s.id, (None, 0))[0]
                
                crawler_label = None
                if is_bot_session is True:
                    crawler_label = 'AI Crawler'
                elif is_bot_session is False:
                    crawler_label = 'Human'

                data.append({
                    "session_id": s.id,
                    "client_id": s.client_id,
                    "first_visit": s.first_visit.isoformat() if s.first_visit else None,
                    "last_visit": s.last_visit.isoformat() if s.last_visit else None,
                    "visit_count": visit_count,
                    "ip_address": s.ip_address or "",
                    "country": sess_country,
                    "city": sess_city,
                    "classification": crawler_label or "Unknown",
                    # Client-side captured data
                    "client_side_timezone": s.client_side_timezone or "",
                    "client_side_language": s.client_side_language or "",
                    "client_side_screen_resolution": s.client_side_screen_resolution or "",
                    "client_side_viewport_size": s.client_side_viewport_size or "",
                    "client_side_device_memory": s.client_side_device_memory or "",
                    "client_side_connection_type": s.client_side_connection_type or ""
                })
            return {
                "sessions": data,
                "total_count": total,
                "has_next": (offset + limit) < total,
                "has_prev": offset > 0,
                "current_page": (offset // limit) + 1,
                "total_pages": ((total - 1) // limit) + 1 if total > 0 else 0
            }
        except Exception as e:
            logger.error("Error in list_sessions", error=str(e))
            return {
                "sessions": [],
                "total_count": 0,
                "has_next": False,
                "has_prev": False,
                "current_page": 1,
                "total_pages": 0
            }

    def get_session_detail(self, db: Session, session_id: str) -> Dict[str, Any]:
        """Get a session with all visits and events in chronological order."""
        session = db.query(VisitSession).filter(VisitSession.id == session_id).first()
        if not session:
            return {"error": "not_found"}

        visits = db.query(Visit).filter(Visit.session_id == session_id).order_by(Visit.timestamp.asc()).all()
        events = db.query(VisitEvent).filter(VisitEvent.session_id == session_id).order_by(VisitEvent.timestamp.asc()).all()

        visits_json = [
            {
                "id": v.id,
                "timestamp": v.timestamp.isoformat() if v.timestamp else None,
                "page_url": v.page_url,
                "referrer": v.referrer,
                "path": v.path,
                "source": v.source,
                "medium": v.medium,
                "campaign": v.campaign,
                "tracking_id": v.tracking_id,
                "is_bot": v.is_bot,
                "crawler_type": v.crawler_type,
                # Client-side captured data
                "client_side_timezone": v.client_side_timezone or "",
                "client_side_language": v.client_side_language or "",
                "client_side_screen_resolution": v.client_side_screen_resolution or "",
                "client_side_viewport_size": v.client_side_viewport_size or "",
                "client_side_device_memory": v.client_side_device_memory or "",
                "client_side_connection_type": v.client_side_connection_type or ""
            }
            for v in visits
        ]

        # Create a mapping of visit IDs to visits for efficient lookup
        visits_dict = {v.id: v for v in visits}

        # Process events with enhanced location fallback logic and debugging
        events_json = []
        for e in events:
            # Try to get location from multiple sources (priority: Visit -> Session -> event_data)
            country = None
            city = None
            location_source = "none"

            # First try Visit table (if event is linked to a visit)
            if e.visit_id and e.visit_id in visits_dict:
                visit = visits_dict[e.visit_id]
                if visit.country and visit.country != "XX":
                    country = visit.country
                    city = visit.city
                    location_source = "visit"
                elif visit.country == "XX":
                    # Visit has XX, try session instead
                    if session and session.country and session.country != "XX":
                        country = session.country
                        city = session.city
                        location_source = "session"

            # If not in Visit, try Session table directly
            if not country and session:
                if session.country and session.country != "XX":
                    country = session.country
                    city = session.city
                    location_source = "session"

            # Fallback to event_data JSON (legacy/backup) - but only if it's not XX
            if not country and e.event_data:
                event_country = e.event_data.get("country")
                if event_country and event_country != "XX":
                    country = event_country
                    city = e.event_data.get("city")
                    location_source = "event_data"

            # Final fallback: if we still don't have country but event_data has XX, use session or visit XX
            if not country and e.event_data and e.event_data.get("country") == "XX":
                # Use XX from event_data, but prefer session/visit if available
                if session and session.country:
                    country = session.country  # Even if it's XX, it's more accurate
                    city = session.city
                    location_source = "session_xx"
                elif e.visit_id and e.visit_id in visits_dict:
                    visit = visits_dict[e.visit_id]
                    if visit.country:
                        country = visit.country
                        city = visit.city
                        location_source = "visit_xx"

            # If we still don't have anything, use the original event_data XX
            if not country and e.event_data:
                country = e.event_data.get("country")
                city = e.event_data.get("city")
                location_source = "event_data_xx"

            # Log for debugging (only in development)
            if settings.debug and (country == "XX" or not country):
                logger.warning(
                    "Event location fallback",
                    event_id=e.id,
                    visit_id=e.visit_id,
                    session_id=e.session_id,
                    session_country=session.country if session else None,
                    visit_country=visits_dict[e.visit_id].country if e.visit_id and e.visit_id in visits_dict else None,
                    event_country=e.event_data.get("country") if e.event_data else None,
                    final_country=country,
                    location_source=location_source
                )

            events_json.append({
                "id": e.id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "event_type": e.event_type,
                "page_url": e.page_url,
                "referrer": e.referrer,
                "path": e.path,
                "page_domain": e.page_domain,
                "referrer_domain": e.referrer_domain,
                "country": country,
                "city": city,
                "source": e.source or (e.event_data or {}).get("source"),
                "medium": e.medium or (e.event_data or {}).get("medium"),
                "campaign": e.campaign or (e.event_data or {}).get("campaign"),
                "tracking_id": e.tracking_id or (e.event_data or {}).get("tracking_id"),
                "tracking_method": (e.event_data or {}).get("tracking_method"),
                "crawler_type": (e.event_data or {}).get("crawler_type"),
                "is_bot": (e.event_data or {}).get("is_bot"),
                "data": e.event_data,
                "visit_id": e.visit_id,
                "_debug_location_source": location_source if settings.debug else None,
                # Client-side captured data
                "client_side_timezone": e.client_side_timezone or "",
                "client_side_language": e.client_side_language or "",
                "client_side_screen_resolution": e.client_side_screen_resolution or "",
                "client_side_viewport_size": e.client_side_viewport_size or "",
                "client_side_device_memory": e.client_side_device_memory or "",
                "client_side_connection_type": e.client_side_connection_type or ""
            })

        # Timeline: merge visits and events
        timeline = [
            {"type": "visit", **vj} for vj in visits_json
        ] + [
            {"type": "event", **ej} for ej in events_json
        ]
        timeline.sort(key=lambda x: x.get("timestamp") or "")

        return {
            "session": {
                "session_id": session.id,
                "client_id": session.client_id,
                "ip_address": session.ip_address,
                "first_visit": session.first_visit.isoformat() if session.first_visit else None,
                "last_visit": session.last_visit.isoformat() if session.last_visit else None,
                "country": session.country,
                "city": session.city,
                "visit_count": session.visit_count,
                # Client-side captured data
                "client_side_timezone": session.client_side_timezone or "",
                "client_side_language": session.client_side_language or "",
                "client_side_screen_resolution": session.client_side_screen_resolution or "",
                "client_side_viewport_size": session.client_side_viewport_size or "",
                "client_side_device_memory": session.client_side_device_memory or "",
                "client_side_connection_type": session.client_side_connection_type or ""
            },
            "visits": visits_json,
            "events": events_json,
            "timeline": timeline,
        }

    def get_all_visits_for_export(self, db: Session, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None, batch_size: int = None, max_retries: int = 3):
        """Get visits for CSV export with optional date filtering.
        
        Uses KEYSET PAGINATION (id-based) to handle massive datasets without the OFFSET performance penalty.
        Includes retry logic for reliability and smaller batches for memory efficiency.
        """
        if batch_size is None:
            batch_size = settings.analytics_export_batch_size or 2000
        
        # Build base query
        base_query = db.query(Visit)
        if start_date:
            base_query = base_query.filter(Visit.timestamp >= start_date)
        if end_date:
            base_query = base_query.filter(Visit.timestamp <= end_date)
        
        logger.info(f"Starting optimized keyset export of visits")
        
        processed = 0
        last_id = 0 # Starting point for keyset pagination
        
        while True:
            retry_count = 0
            batch_success = False
            
            while retry_count < max_retries and not batch_success:
                try:
                    # Optimized: filter by id > last_id instead of OFFSET
                    # We sort by id ASC for stable streaming
                    batch = base_query.filter(Visit.id > last_id).order_by(Visit.id.asc()).limit(batch_size).all()
                    
                    if not batch:
                        return # Finished
                    
                    # Batch fetch sessions for these visits to reduce total query count
                    session_ids = list(set([v.session_id for v in batch if v.session_id and not v.country]))
                    sessions_dict = {}
                    if session_ids:
                        sessions = db.query(VisitSession).filter(VisitSession.id.in_(session_ids)).all()
                        sessions_dict = {s.id: s for s in sessions}
                        
                    for visit in batch:
                        country = visit.country
                        city = visit.city
                        if not country and visit.session_id in sessions_dict:
                            s = sessions_dict[visit.session_id]
                            country = s.country
                            city = s.city
                        
                        yield {
                            "id": visit.id,
                            "timestamp": visit.timestamp.isoformat() if visit.timestamp else "",
                            "session_id": visit.session_id or "",
                            "client_id": visit.client_id or "",
                            "user_agent": visit.user_agent or "",
                            "page_url": visit.page_url or "",
                            "page_domain": visit.page_domain or "",
                            "path": visit.path or "",
                            "is_bot": str(visit.is_bot) if visit.is_bot is not None else "",
                            "crawler_type": visit.crawler_type or "",
                            "country": country or "",
                            "city": city or "",
                            "tracking_id": visit.tracking_id or "",
                            "source": visit.source or "",
                            "medium": visit.medium or "",
                            "campaign": visit.campaign or "",
                            "referrer": visit.referrer or "",
                            "page_title": visit.page_title or "",
                            "request_method": visit.request_method or "",
                            "response_status": str(visit.response_status) if visit.response_status is not None else "",
                            "ip_address": visit.ip_address or "",
                            "client_side_timezone": visit.client_side_timezone or "",
                            "client_side_language": visit.client_side_language or "",
                            "client_side_screen_resolution": visit.client_side_screen_resolution or "",
                            "client_side_viewport_size": visit.client_side_viewport_size or "",
                            "client_side_device_memory": visit.client_side_device_memory or "",
                            "client_side_connection_type": visit.client_side_connection_type or ""
                        }
                        last_id = visit.id # Update for next batch
                    
                    processed += len(batch)
                    batch_success = True
                    if processed % 10000 == 0:
                        logger.info(f"Exported {processed} visits...")
                    
                except (OperationalError, SQLTimeoutError) as e:
                    retry_count += 1
                    logger.warning(f"Export timeout at id {last_id}, retry {retry_count}")
                    db.rollback()
                    if retry_count >= max_retries:
                        raise
                    time.sleep(1)
            
            # Free memory periodically
            db.expire_all()


    def get_all_events_for_export(self, db: Session, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None, batch_size: int = None, max_retries: int = 3):
        """Get visit events for CSV export with optional date filtering.
        
        Uses KEYSET PAGINATION (id-based) to handle massive datasets.
        """
        import json
        if batch_size is None:
            batch_size = settings.analytics_export_batch_size or 2000
        
        # Build base query
        base_query = db.query(VisitEvent)
        if start_date:
            base_query = base_query.filter(VisitEvent.timestamp >= start_date)
        if end_date:
            base_query = base_query.filter(VisitEvent.timestamp <= end_date)
        
        logger.info(f"Starting optimized keyset export of events")
        
        processed = 0
        last_id = 0
        
        while True:
            retry_count = 0
            batch_success = False
            
            while retry_count < max_retries and not batch_success:
                try:
                    # Optimized keyset fetch
                    batch = base_query.filter(VisitEvent.id > last_id).order_by(VisitEvent.id.asc()).limit(batch_size).all()
                    
                    if not batch:
                        return # Done
                    
                    # Batch fetch sessions and visits for location mapping
                    session_ids = list(set([ev.session_id for ev in batch if ev.session_id]))
                    sessions_dict = {}
                    if session_ids:
                        sessions = db.query(VisitSession).filter(VisitSession.id.in_(session_ids)).all()
                        sessions_dict = {s.id: s for s in sessions}
                    
                    for ev in batch:
                        event_data = ev.event_data or {}

                        country = event_data.get("country")
                        city = event_data.get("city")
                        if (not country or country == "XX") and ev.session_id in sessions_dict:
                            s = sessions_dict[ev.session_id]
                            country = s.country
                            city = s.city

                        data_str = json.dumps(event_data) if event_data else ""
                        source = ev.source or event_data.get("source") or ""
                        medium = ev.medium or event_data.get("medium") or ""
                        campaign = ev.campaign or event_data.get("campaign") or ""
                        tracking_id = ev.tracking_id or event_data.get("tracking_id") or ""
                        crawler_type = event_data.get("crawler_type") or ""
                        is_bot = event_data.get("is_bot")

                        yield {
                            "id": ev.id,
                            "timestamp": ev.timestamp.isoformat() if ev.timestamp else "",
                            "session_id": ev.session_id or "",
                            "visit_id": ev.visit_id or "",
                            "client_id": ev.client_id or "",
                            "event_type": ev.event_type or "",
                            "page_url": ev.page_url or "",
                            "referrer": ev.referrer or "",
                            "path": ev.path or "",
                            "page_domain": ev.page_domain or "",
                            "referrer_domain": ev.referrer_domain or "",
                            "country": country or "",
                            "city": city or "",
                            "source": source,
                            "medium": medium,
                            "campaign": campaign,
                            "tracking_id": tracking_id,
                            "crawler_type": crawler_type,
                            "is_bot": str(is_bot) if is_bot is not None else "",
                            "event_data_json": data_str,
                            "client_side_timezone": ev.client_side_timezone or "",
                            "client_side_language": ev.client_side_language or "",
                            "client_side_screen_resolution": ev.client_side_screen_resolution or "",
                            "client_side_viewport_size": ev.client_side_viewport_size or "",
                            "client_side_device_memory": ev.client_side_device_memory or "",
                            "client_side_connection_type": ev.client_side_connection_type or ""
                        }
                        last_id = ev.id
                    
                    processed += len(batch)
                    batch_success = True
                    if processed % 10000 == 0:
                        logger.info(f"Exported {processed} events...")
                        
                except Exception as e:
                    retry_count += 1
                    logger.warning(f"Event export timeout, retry {retry_count}")
                    db.rollback()
                    if retry_count >= max_retries:
                        raise
                    time.sleep(1)
            
            db.expire_all()


    def backfill_event_locations(self, db: Session, batch_size: int = 1000) -> Dict[str, Any]:
        """Backfill missing location data in events from their visits and sessions."""
        try:
            # Get events that have XX or missing location data
            events_needing_update = db.query(VisitEvent).filter(
                VisitEvent.event_data.isnot(None),
                db.or_(
                    VisitEvent.event_data["country"].astext == "XX",
                    VisitEvent.event_data["country"].is_(None)
                )
            ).all()

            if not events_needing_update:
                return {
                    "success": True,
                    "updated_events": 0,
                    "message": "No events need location backfilling"
                }

            total_to_update = len(events_needing_update)
            updated_count = 0

            logger.info(f"Starting backfill of {total_to_update} events with missing/XX location data")

            # Get all visit and session IDs for batch processing
            visit_ids = list(set([e.visit_id for e in events_needing_update if e.visit_id]))
            session_ids = list(set([e.session_id for e in events_needing_update if e.session_id]))

            # Batch fetch visits and sessions
            visits_dict = {}
            if visit_ids:
                visits = db.query(Visit).filter(Visit.id.in_(visit_ids)).all()
                visits_dict = {v.id: v for v in visits}

            sessions_dict = {}
            if session_ids:
                sessions = db.query(VisitSession).filter(VisitSession.id.in_(session_ids)).all()
                sessions_dict = {s.id: s for s in sessions}

            # Process events and update their location data
            for event in events_needing_update:
                updated = False
                event_data = event.event_data or {}

                # Try to get location from visit first
                if event.visit_id and event.visit_id in visits_dict:
                    visit = visits_dict[event.visit_id]
                    if visit.country and visit.country != "XX":
                        event_data["country"] = visit.country
                        event_data["city"] = visit.city or "Unknown"
                        updated = True

                # Fall back to session if visit didn't have good data
                if not updated and event.session_id in sessions_dict:
                    session = sessions_dict[event.session_id]
                    if session.country and session.country != "XX":
                        event_data["country"] = session.country
                        event_data["city"] = session.city or "Unknown"
                        updated = True

                # Update the event if we found better location data
                if updated:
                    event.event_data = event_data
                    db.add(event)
                    updated_count += 1

            # Commit all changes
            db.commit()

            logger.info(f"Backfilled location data for {updated_count}/{total_to_update} events")

            return {
                "success": True,
                "updated_events": updated_count,
                "total_processed": total_to_update,
                "message": f"Successfully backfilled location data for {updated_count} events"
            }

        except Exception as e:
            db.rollback()
            logger.error("Error backfilling event locations", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to backfill location data: {str(e)}"
            }

    def delete_all_visits(self, db: Session) -> Dict[str, Any]:
        """Delete all visit data, handling foreign key constraints."""
        try:
            # Count visits before deletion
            visit_count = db.query(func.count(Visit.id)).scalar()
            session_count = db.query(func.count(VisitSession.id)).scalar()
            
            # First, let's try a simple approach - delete visits with cascade
            # This should handle foreign keys automatically if they're set up properly
            deleted_visits = db.query(Visit).delete()
            deleted_sessions = db.query(VisitSession).delete()
            
            db.commit()
            
            return {
                "success": True,
                "deleted_visits": deleted_visits,
                "deleted_sessions": deleted_sessions,
                "original_visit_count": visit_count,
                "original_session_count": session_count,
                "message": f"Successfully deleted {deleted_visits} visits and {deleted_sessions} sessions"
            }
            
        except Exception as e:
            # If that fails, try the manual approach
            try:
                db.rollback()
                
                # Manual cleanup approach - delete all possible dependent records first
                dependent_deletions = []
                
                # Only clean up known FK-dependent tables — never visit_events,
                # which holds valuable event data unrelated to visit deletion.
                dependent_tables = [
                    "crawler_visit_logs",
                    "tracking_events",
                    "crawler_logs",
                    "analytics_summaries",
                    "crawler_patterns",
                ]

                for table in dependent_tables:
                    try:
                        result = db.execute(text(f"DELETE FROM {table}"))
                        count = result.rowcount if hasattr(result, 'rowcount') else 0
                        if count > 0:
                            dependent_deletions.append(f"{table}: {count}")
                            logger.info("Deleted dependent table rows", table=table, count=count)
                        db.commit()
                    except Exception:
                        db.rollback()
                        continue
                
                # Now try to delete visits and sessions
                deleted_visits = db.query(Visit).delete()
                deleted_sessions = db.query(VisitSession).delete()
                db.commit()
                
                return {
                    "success": True,
                    "deleted_visits": deleted_visits,
                    "deleted_sessions": deleted_sessions,
                    "dependent_deletions": dependent_deletions,
                    "message": f"Successfully deleted {deleted_visits} visits, {deleted_sessions} sessions, and dependencies: {', '.join(dependent_deletions) if dependent_deletions else 'none'}"
                }
                
            except Exception as e2:
                try:
                    db.rollback()
                except:
                    pass
                return {
                    "success": False,
                    "error": str(e2),
                    "original_error": str(e),
                    "message": f"Failed to delete data. Original error: {str(e)}. Cleanup error: {str(e2)}"
                }
    
    def backfill_visit_locations(self, db: Session, batch_size: int = 1000) -> Dict[str, Any]:
        """Backfill missing location data in Visits from their Sessions with batch processing."""
        from sqlalchemy.orm import joinedload

        try:
            # Get total count of visits needing update (missing or XX location)
            total_to_update = db.query(func.count(Visit.id)).join(
                VisitSession, Visit.session_id == VisitSession.id
            ).filter(
                db.or_(
                    Visit.country.is_(None),
                    Visit.country == "XX",
                    and_(Visit.city.is_(None), VisitSession.city.isnot(None)),
                    and_(Visit.city == "Unknown", VisitSession.city.isnot(None))
                )
            ).scalar() or 0

            if total_to_update == 0:
                return {
                    "success": True,
                    "updated_visits": 0,
                    "message": "No visits need location backfilling"
                }

            updated_count = 0

            # Process in batches — always query from offset 0 because updated
            # rows drop out of the filter on the next iteration.
            while True:
                batch = db.query(Visit).options(
                    joinedload(Visit.session)
                ).join(
                    VisitSession, Visit.session_id == VisitSession.id
                ).filter(
                    db.or_(
                        Visit.country.is_(None),
                        Visit.country == "XX",
                        and_(Visit.city.is_(None), VisitSession.city.isnot(None)),
                        and_(Visit.city == "Unknown", VisitSession.city.isnot(None))
                    )
                ).limit(batch_size).all()

                if not batch:
                    break

                batch_updated = 0
                for visit in batch:
                    if visit.session:
                        changed = False
                        if (not visit.country or visit.country == "XX") and visit.session.country and visit.session.country != "XX":
                            visit.country = visit.session.country
                            changed = True

                        if (not visit.city or visit.city == "Unknown") and visit.session.city and visit.session.city != "Unknown":
                            visit.city = visit.session.city
                            changed = True

                        if changed:
                            db.add(visit)
                            updated_count += 1
                            batch_updated += 1

                db.commit()
                logger.info(f"Backfilled location for {len(batch)} visits (total: {updated_count}/{total_to_update})")

                # If nothing in this batch was updatable (session has no good data either),
                # the same rows would be fetched again — break to avoid infinite loop.
                if batch_updated == 0:
                    break

            return {
                "success": True,
                "updated_visits": updated_count,
                "total_processed": total_to_update,
                "message": f"Successfully backfilled location data for {updated_count} visits"
            }
        except Exception as e:
            db.rollback()
            logger.error("Error backfilling visit locations", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to backfill location data: {str(e)}"
            }

    def backfill_session_locations(self, db: Session, batch_size: int = 1000) -> Dict[str, Any]:
        """Backfill missing location data in Sessions from their Visits with batch processing."""
        try:
            # Get total count of sessions needing update (missing or XX location)
            total_to_update = db.query(func.count(VisitSession.id)).filter(
                db.or_(
                    VisitSession.country.is_(None),
                    VisitSession.country == "XX",
                    and_(VisitSession.city.is_(None)),
                    and_(VisitSession.city == "Unknown")
                )
            ).scalar() or 0

            if total_to_update == 0:
                return {
                    "success": True,
                    "updated_sessions": 0,
                    "message": "No sessions need location backfilling"
                }

            updated_count = 0

            # Process in batches — always query from offset 0 because updated
            # rows drop out of the filter on the next iteration.
            while True:
                batch = db.query(VisitSession).filter(
                    db.or_(
                        VisitSession.country.is_(None),
                        VisitSession.country == "XX",
                        and_(VisitSession.city.is_(None)),
                        and_(VisitSession.city == "Unknown")
                    )
                ).limit(batch_size).all()

                if not batch:
                    break

                batch_updated = 0
                for session in batch:
                    changed = False

                    best_visit = db.query(Visit).filter(
                        Visit.session_id == session.id,
                        Visit.country.isnot(None),
                        Visit.country != "XX"
                    ).order_by(Visit.timestamp.desc()).first()

                    if best_visit:
                        if (not session.country or session.country == "XX") and best_visit.country:
                            session.country = best_visit.country
                            changed = True

                        if (not session.city or session.city == "Unknown") and best_visit.city:
                            session.city = best_visit.city
                            changed = True

                        if changed:
                            db.add(session)
                            updated_count += 1
                            batch_updated += 1

                db.commit()
                logger.info(f"Backfilled location for {len(batch)} sessions (total: {updated_count}/{total_to_update})")

                if batch_updated == 0:
                    break

            return {
                "success": True,
                "updated_sessions": updated_count,
                "total_processed": total_to_update,
                "message": f"Successfully backfilled location data for {updated_count} sessions"
            }
        except Exception as e:
            db.rollback()
            logger.error("Error backfilling session locations", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to backfill session location data: {str(e)}"
            }

    def get_visitor_categories(
        self,
        db: Session,
        days: int = 30,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get detailed visitor categorization."""
        if start_date or end_date:
            since = start_date or (datetime.now(timezone.utc) - timedelta(days=days))
            until = end_date
        else:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            until = None
        
        filters = [Visit.timestamp >= since]
        if until:
            filters.append(Visit.timestamp <= until)
            
        categories_query = db.query(
            Visit.crawler_type,
            func.count(Visit.id).label('count')
        ).filter(*filters).group_by(Visit.crawler_type).all()
        
        categories = []
        for row in categories_query:
            label = row.crawler_type or "Human"
            categories.append({"name": label, "count": row.count})
            
        return {"categories": categories, "period_days": days}

    
    def get_unified_user_activity(self, db: Session, client_id: str) -> Dict[str, Any]:
        """Get all activity (sessions, visits, events) for a unified user identified by client_id."""
        try:
            # Get all sessions for this client_id
            sessions = db.query(VisitSession).filter(
                VisitSession.client_id == client_id
            ).order_by(VisitSession.first_visit.asc()).all()
            
            # Get all visits for this client_id
            visits = db.query(Visit).filter(
                Visit.client_id == client_id
            ).order_by(Visit.timestamp.asc()).all()
            
            # Get all events for this client_id
            events = db.query(VisitEvent).filter(
                VisitEvent.client_id == client_id
            ).order_by(VisitEvent.timestamp.asc()).all()
            
            # Build a unified timeline
            timeline = []
            
            # Add visits to timeline
            for v in visits:
                timeline.append({
                    "type": "visit",
                    "id": v.id,
                    "timestamp": v.timestamp.isoformat() if v.timestamp else None,
                    "session_id": v.session_id,
                    "page_url": v.page_url,
                    "referrer": v.referrer,
                    "country": v.country,
                    "city": v.city,
                    "is_bot": v.is_bot,
                    "crawler_type": v.crawler_type,
                    "source": v.source,
                    "medium": v.medium,
                    "campaign": v.campaign,
                })
            
            # Add events to timeline
            for e in events:
                timeline.append({
                    "type": "event",
                    "id": e.id,
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                    "session_id": e.session_id,
                    "visit_id": e.visit_id,
                    "event_type": e.event_type,
                    "page_url": e.page_url,
                    "data": e.event_data,
                })
            
            # Sort timeline by timestamp
            timeline.sort(key=lambda x: x.get("timestamp") or "")
            
            # Calculate summary stats
            unique_sessions = len(sessions)
            unique_domains = len(set(v.page_domain for v in visits if v.page_domain))
            first_seen = sessions[0].first_visit if sessions else None
            last_seen = sessions[-1].last_visit if sessions else None
            conversion_count = sum(1 for e in events if e.event_type == "form_submit")
            
            # Get First Touch Attribution
            first_visit = visits[0] if visits else None
            attribution = {
                "source": first_visit.source or "direct" if first_visit else "unknown",
                "medium": first_visit.medium or "none" if first_visit else "none",
                "campaign": first_visit.campaign or "none" if first_visit else "none",
                "landing_page": first_visit.page_url if first_visit else None
            }

            return {
                "client_id": client_id,
                "summary": {
                    "unique_sessions": unique_sessions,
                    "total_visits": len(visits),
                    "total_events": len(events),
                    "unique_domains": unique_domains,
                    "conversions": conversion_count,
                    "first_seen": first_seen.isoformat() if first_seen else None,
                    "last_seen": last_seen.isoformat() if last_seen else None,
                },
                "attribution": attribution,
                "sessions": [
                    {
                        "session_id": s.id,
                        "first_visit": s.first_visit.isoformat() if s.first_visit else None,
                        "last_visit": s.last_visit.isoformat() if s.last_visit else None,
                        "visit_count": s.visit_count,
                        "ip_address": s.ip_address,
                        "country": s.country,
                        "city": s.city,
                    }
                    for s in sessions
                ],
                "timeline": timeline,
            }
        except Exception as e:
            logger.error("Error getting unified user activity", error=str(e), client_id=client_id)
            return {
                "client_id": client_id,
                "error": str(e),
                "summary": {},
                "sessions": [],
                "timeline": [],
            }

    def get_journey_timeline(self, db: Session, client_id: str, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
        """Get a unified journey timeline for a client_id with pagination."""
        import json

        try:
            visits_count = db.query(func.count(Visit.id)).filter(Visit.client_id == client_id).scalar() or 0
            events_count = db.query(func.count(VisitEvent.id)).filter(VisitEvent.client_id == client_id).scalar() or 0
            total = visits_count + events_count

            rows = db.execute(
                text(
                    """
                    SELECT
                        'visit' AS item_type,
                        id,
                        timestamp,
                        page_url,
                        referrer,
                        path,
                        page_domain,
                        NULL::text AS referrer_domain,
                        source,
                        medium,
                        campaign,
                        tracking_id,
                        is_bot,
                        crawler_type,
                        NULL::text AS event_type,
                        NULL::json AS event_data
                    FROM visits
                    WHERE client_id = :client_id
                    UNION ALL
                    SELECT
                        'event' AS item_type,
                        id,
                        timestamp,
                        page_url,
                        referrer,
                        path,
                        page_domain,
                        referrer_domain,
                        source,
                        medium,
                        campaign,
                        tracking_id,
                        NULL::boolean AS is_bot,
                        NULL::text AS crawler_type,
                        event_type,
                        event_data
                    FROM visit_events
                    WHERE client_id = :client_id
                    ORDER BY timestamp ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"client_id": client_id, "limit": limit, "offset": offset},
            ).mappings().all()

            timeline = []
            for row in rows:
                event_data = row.get("event_data")
                if isinstance(event_data, str):
                    try:
                        event_data = json.loads(event_data)
                    except Exception:
                        event_data = None
                timeline.append(
                    {
                        "type": row.get("item_type"),
                        "id": row.get("id"),
                        "timestamp": row.get("timestamp").isoformat() if row.get("timestamp") else None,
                        "page_url": row.get("page_url"),
                        "referrer": row.get("referrer"),
                        "path": row.get("path"),
                        "page_domain": row.get("page_domain"),
                        "referrer_domain": row.get("referrer_domain"),
                        "source": row.get("source"),
                        "medium": row.get("medium"),
                        "campaign": row.get("campaign"),
                        "tracking_id": row.get("tracking_id"),
                        "is_bot": row.get("is_bot"),
                        "crawler_type": row.get("crawler_type"),
                        "event_type": row.get("event_type"),
                        "data": event_data,
                    }
                )

            return {
                "client_id": client_id,
                "timeline": timeline,
                "total_count": total,
                "has_next": (offset + limit) < total,
                "has_prev": offset > 0,
                "current_page": (offset // limit) + 1,
                "total_pages": ((total - 1) // limit) + 1 if total > 0 else 0,
            }
        except Exception as e:
            logger.error("Error getting journey timeline", error=str(e), client_id=client_id)
            return {
                "client_id": client_id,
                "timeline": [],
                "total_count": 0,
                "has_next": False,
                "has_prev": False,
                "current_page": 1,
                "total_pages": 0,
                "error": str(e),
            }

    def get_conversion_attribution(self, db: Session, client_id: str) -> Dict[str, Any]:
        """Get attribution data for a specific user (First-Touch model)."""
        # 1. Find the very first visit (entry point)
        first_visit = db.query(Visit).filter(
            Visit.client_id == client_id
        ).order_by(Visit.timestamp.asc()).first()
        
        if not first_visit:
            return {"status": "no_visits"}
            
        # 2. Find conversion events (form_submit)
        conversions = db.query(VisitEvent).filter(
            VisitEvent.client_id == client_id,
            VisitEvent.event_type == 'form_submit'
        ).order_by(VisitEvent.timestamp.asc()).all()
        
        attribution = {
            "client_id": client_id,
            "first_touch": {
                "timestamp": first_visit.timestamp.isoformat() if first_visit.timestamp else None,
                "source": first_visit.source or "direct",
                "medium": first_visit.medium or "none",
                "campaign": first_visit.campaign or "none",
                "landing_page": first_visit.page_url,
                "referrer": first_visit.referrer
            },
            "conversion_count": len(conversions),
            "conversions": []
        }
        
        for conv in conversions:
            attribution["conversions"].append({
                "timestamp": conv.timestamp.isoformat() if conv.timestamp else None,
                "page": conv.page_url,
                "data": conv.event_data.get('form_values') if conv.event_data else {}
            })
            
        return attribution

    def list_journey_summaries(
        self,
        db: Session,
        target_path: Optional[str] = None,
        with_captured_only: bool = False,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """List journeys from pre-computed summary table."""
        try:
            query = db.query(JourneySummary)
            
            if start_date: query = query.filter(JourneySummary.last_seen >= start_date)
            if end_date: query = query.filter(JourneySummary.last_seen <= end_date)
            if target_path:
                for p in [x.strip() for x in target_path.split(',')]:
                    query = query.filter(JourneySummary.path_sequence.ilike(f"%{p}%"))
            
            if with_captured_only:
                query = query.filter(JourneySummary.has_captured_data == 1)

            total = query.count()
            rows = query.order_by(JourneySummary.last_seen.desc()).offset(offset).limit(limit).all()

            journeys = []
            for r in rows:
                journeys.append({
                    "client_id": r.client_id,
                    "visit_count": r.visit_count,
                    "form_fill_count": r.form_fill_count or 0,
                    "first_seen": r.first_seen.isoformat() if r.first_seen else None,
                    "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                    "entry_page": r.entry_page,
                    "exit_page": r.exit_page,
                    "source": r.source or "direct",
                    "medium": r.medium or "none",
                    "campaign": r.campaign or "none",
                    "has_captured_data": bool(r.has_captured_data),
                    "email": r.email,
                    "name": r.name,
                    "path_sequence": r.path_sequence,
                })
                
            return {
                "journeys": journeys,
                "total_count": total,
                "has_next": (offset + limit) < total,
                "has_prev": offset > 0,
                "current_page": (offset // limit) + 1,
                "total_pages": ((total - 1) // limit) + 1 if total > 0 else 0
            }
        except Exception as e:
            logger.error("Error listing journey summaries from table", error=str(e))
            return {"journeys": [], "total_count": 0, "error": str(e)}

    def list_leads(
        self,
        db: Session,
        captured_path: Optional[str] = None,
        source: Optional[str] = None,
        medium: Optional[str] = None,
        campaign: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List leads from pre-computed summary table."""
        try:
            query = db.query(LeadSummary)
            
            if start_date: query = query.filter(LeadSummary.last_seen >= start_date)
            if end_date: query = query.filter(LeadSummary.last_seen <= end_date)
            if captured_path: query = query.filter(LeadSummary.captured_path.ilike(f"{captured_path}%"))
            if source: query = query.filter(func.lower(LeadSummary.source) == source.lower())
            if medium: query = query.filter(func.lower(LeadSummary.medium) == medium.lower())
            if campaign: query = query.filter(func.lower(LeadSummary.campaign) == campaign.lower())
            
            total = query.count()
            rows = query.order_by(LeadSummary.last_seen.desc()).offset(offset).limit(limit).all()
            
            leads = []
            for r in rows:
                leads.append({
                    "client_id": r.client_id,
                    "captured_at": r.captured_at.isoformat() if r.captured_at else None,
                    "captured_page": r.captured_page,
                    "captured_path": r.captured_path,
                    "email": r.email,
                    "name": r.name,
                    "source": r.source or "direct",
                    "medium": r.medium or "none",
                    "campaign": r.campaign or "none",
                    "form_data_shared": r.form_data_shared,
                    "captured_data": r.captured_data,
                })
                
            return {
                "leads": leads,
                "total_count": total,
                "has_next": (offset + limit) < total,
                "has_prev": offset > 0,
                "current_page": (offset // limit) + 1,
                "total_pages": ((total - 1) // limit) + 1 if total > 0 else 0
            }
        except Exception as e:
            logger.error("Error listing leads from table", error=str(e))
            return {"leads": [], "total_count": 0, "error": str(e)}



    def get_journey_form_fills(self, db: Session, client_id: str) -> List[Dict[str, Any]]:
        """Get all pre-computed form fills for a client (ordered by timestamp). Multiple forms preserved."""
        rows = (
            db.query(JourneyFormFill)
            .filter(JourneyFormFill.client_id == client_id)
            .order_by(JourneyFormFill.timestamp.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "page_url": r.page_url,
                "path": r.path,
                "form_values": r.form_values,
                "filled_fields": r.filled_fields,
                "form_id": r.form_id,
                "form_action": r.form_action,
            }
            for r in rows
        ]

    def get_lead_detail(self, db: Session, client_id: str, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
        """Get full lead details including journey timeline and all form fills (multiple preserved)."""
        form_fills = self.get_journey_form_fills(db, client_id)
        lead_events = db.query(VisitEvent).filter(
            VisitEvent.client_id == client_id,
            or_(VisitEvent.event_type == "form_submit", VisitEvent.event_type.ilike("%submit%"))
        ).order_by(VisitEvent.timestamp.desc()).all()

        if not lead_events and not form_fills:
            return {"error": "Lead not found"}

        latest_event = lead_events[0] if lead_events else None
        event_data = (latest_event.event_data or {}) if latest_event else {}
        form_values = event_data.get("form_values") or event_data.get("values") or {}
        if not form_values and form_fills:
            form_values = form_fills[-1].get("form_values") or {}

        url_params = {}
        if latest_event and latest_event.page_url:
            try:
                parsed = urlparse(latest_event.page_url)
                url_params = {k: v[0] if isinstance(v, list) else v for k, v in parse_qs(parsed.query).items()}
            except Exception:
                url_params = {}

        journey = self.get_journey_timeline(db, client_id, limit=limit, offset=offset)

        return {
            "client_id": client_id,
            "form_fills": form_fills,
            "captured_events": [
                {
                    "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
                    "page_url": ev.page_url,
                    "path": ev.path,
                    "form_values": (ev.event_data or {}).get("form_values") or (ev.event_data or {}).get("values"),
                }
                for ev in lead_events
            ],
            "latest_capture": {
                "timestamp": (latest_event.timestamp.isoformat() if latest_event and latest_event.timestamp else None)
                    or (form_fills[-1]["timestamp"] if form_fills else None),
                "page_url": (latest_event.page_url if latest_event else None) or (form_fills[-1]["page_url"] if form_fills else None),
                "path": (latest_event.path if latest_event else None) or (form_fills[-1]["path"] if form_fills else None),
                "form_values": form_values,
            },
            "url_params": url_params,
            "journey": journey,
        }

    def export_leads(
        self,
        db: Session,
        captured_path: Optional[str] = None,
        source: Optional[str] = None,
        medium: Optional[str] = None,
        campaign: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 200000,
    ):
        """Export captured leads as a generator."""
        data = self.list_leads(
            db,
            captured_path=captured_path,
            source=source,
            medium=medium,
            campaign=campaign,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=0,
        )

        for row in data.get("leads", []):
            yield {
                "client_id": row.get("client_id") or "",
                "captured_at": row.get("captured_at") or "",
                "captured_page": row.get("captured_page") or "",
                "captured_path": row.get("captured_path") or "",
                "email": row.get("email") or "",
                "name": row.get("name") or "",
                "source": row.get("source") or "",
                "medium": row.get("medium") or "",
                "campaign": row.get("campaign") or "",
                "form_values": json.dumps(row.get("form_values")) if row.get("form_values") else "",
            }

    def get_page_flow_summary(self, db: Session, days: int = 7, limit: int = 100) -> Dict[str, Any]:
        """Summarize page-to-page flows across sessions."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = db.execute(
            text(
                """
                SELECT prev_path, path, COUNT(*) AS count
                FROM (
                    SELECT
                        session_id,
                        path,
                        LAG(path) OVER (PARTITION BY session_id ORDER BY timestamp) AS prev_path
                    FROM visits
                    WHERE timestamp >= :since AND path IS NOT NULL
                ) t
                WHERE prev_path IS NOT NULL AND path IS NOT NULL
                GROUP BY prev_path, path
                ORDER BY count DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        ).mappings().all()

        flows = [{"from": row["prev_path"], "to": row["path"], "count": row["count"]} for row in rows]
        return {"flows": flows, "period_days": days}
    
    def list_unified_users(self, db: Session, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """List unique users by client_id with their activity summary and attribution."""
        try:
            total = db.query(func.count(func.distinct(Visit.client_id))).filter(
                Visit.client_id.isnot(None)
            ).scalar() or 0
            
            user_stats = db.query(
                Visit.client_id,
                func.count(func.distinct(Visit.session_id)).label('session_count'),
                func.count(Visit.id).label('visit_count'),
                func.min(Visit.timestamp).label('first_seen'),
                func.max(Visit.timestamp).label('last_seen'),
            ).filter(
                Visit.client_id.isnot(None)
            ).group_by(Visit.client_id).order_by(desc('last_seen')).offset(offset).limit(limit).all()
            
            if not user_stats:
                return {
                    "users": [],
                    "total_count": total,
                    "has_next": False,
                    "has_prev": offset > 0,
                    "current_page": (offset // limit) + 1,
                    "total_pages": 0
                }

            client_ids = [u.client_id for u in user_stats]

            first_visit_subq = db.query(
                Visit.client_id.label("client_id"),
                func.min(Visit.timestamp).label("first_ts")
            ).filter(
                Visit.client_id.in_(client_ids)
            ).group_by(Visit.client_id).subquery()

            first_visits = db.query(
                Visit.client_id,
                Visit.source,
                Visit.medium,
                Visit.campaign,
                Visit.page_url
            ).join(
                first_visit_subq,
                and_(Visit.client_id == first_visit_subq.c.client_id, Visit.timestamp == first_visit_subq.c.first_ts)
            ).all()

            attribution_data = {}
            for row in first_visits:
                if row.client_id not in attribution_data:
                    attribution_data[row.client_id] = {
                        "source": row.source or "direct",
                        "medium": row.medium or "none",
                        "campaign": row.campaign or "none",
                        "landing_page": row.page_url
                    }

            event_counts = dict(
                db.query(VisitEvent.client_id, func.count(VisitEvent.id))
                .filter(VisitEvent.client_id.in_(client_ids))
                .group_by(VisitEvent.client_id).all()
            )

            conversion_counts = dict(
                db.query(VisitEvent.client_id, func.count(VisitEvent.id))
                .filter(VisitEvent.client_id.in_(client_ids), VisitEvent.event_type == 'form_submit')
                .group_by(VisitEvent.client_id).all()
            )

            last_session_subq = db.query(
                VisitSession.client_id.label("client_id"),
                func.max(VisitSession.last_visit).label("last_ts")
            ).filter(
                VisitSession.client_id.in_(client_ids)
            ).group_by(VisitSession.client_id).subquery()

            last_sessions = db.query(
                VisitSession.client_id,
                VisitSession.country,
                VisitSession.city
            ).join(
                last_session_subq,
                and_(VisitSession.client_id == last_session_subq.c.client_id, VisitSession.last_visit == last_session_subq.c.last_ts)
            ).all()

            location_map = {row.client_id: {"country": row.country, "city": row.city} for row in last_sessions}

            user_list = []
            for u in user_stats:
                attr = attribution_data.get(u.client_id, {})
                loc = location_map.get(u.client_id, {})
                user_list.append({
                    "client_id": u.client_id,
                    "session_count": u.session_count,
                    "visit_count": u.visit_count,
                    "event_count": event_counts.get(u.client_id, 0),
                    "conversion_count": conversion_counts.get(u.client_id, 0),
                    "first_seen": u.first_seen.isoformat() if u.first_seen else None,
                    "last_seen": u.last_seen.isoformat() if u.last_seen else None,
                    "last_country": loc.get("country"),
                    "last_city": loc.get("city"),
                    "attribution": attr,
                })
            
            return {
                "users": user_list,
                "total_count": total,
                "has_next": (offset + limit) < total,
                "has_prev": offset > 0,
                "current_page": (offset // limit) + 1,
                "total_pages": ((total - 1) // limit) + 1 if total > 0 else 0
            }
        except Exception as e:
            logger.error("Error listing unified users", error=str(e))
            return {"users": [], "total_count": 0, "error": str(e)}

    def analyze_journey_path(
        self,
        db: Session,
        target_path: str,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """Analyze journeys for a specific target path using dynamic SQL."""
        
        # Prepare the regex for the target path
        # If user passes "/schedule", we want to match it robustly
        clean_path = target_path.strip()
        if not clean_path.startswith('^'):
            clean_path = '^.*' + clean_path.lstrip('.*')
        if not clean_path.endswith('([/?#]|$)'):
            clean_path = clean_path.rstrip('$') + '([/?#]|$)'
            
        sql = text("""
        WITH schedule_converters AS (
            -- 1. Identify users who hit the target path and their conversion time
            SELECT 
                COALESCE(client_id, session_id) as unique_user_key,
                MIN(timestamp) as first_scheduled_at
            FROM visits
            WHERE path ~* :path_regex
              AND timestamp >= NOW() - INTERVAL '1 day' * :days
            GROUP BY 1
        ),
        converters_with_params AS (
            -- 2. Pre-extract form data from URL parameters
            SELECT DISTINCT ON (COALESCE(client_id, session_id))
                COALESCE(client_id, session_id) as unique_user_key,
                (
                    SELECT STRING_AGG(key || ': ' || (value->>0), ' | ') 
                    FROM jsonb_each(query_params::jsonb) 
                    WHERE key IN ('email', 'name', 'company', 'organization', 'user_email')
                ) as extracted_params
            FROM visits
            WHERE path ~* :path_regex
              AND timestamp >= NOW() - INTERVAL '1 day' * :days
            ORDER BY COALESCE(client_id, session_id), timestamp ASC
        ),
        user_attribution AS (
            -- 3. Find original source
            SELECT DISTINCT ON (unique_user_key)
                COALESCE(client_id, session_id) as unique_user_key,
                referrer as original_referrer,
                source as original_utm_source,
                medium as original_utm_medium,
                timestamp as first_ever_visit
            FROM visits
            WHERE COALESCE(client_id, session_id) IN (SELECT unique_user_key FROM schedule_converters)
              AND timestamp >= NOW() - INTERVAL '1 day' * :days
            ORDER BY unique_user_key, timestamp ASC
        ),
        journey_data AS (
            -- 4. Get chronological paths (deduplicated)
            SELECT 
                COALESCE(v.client_id, v.session_id) as unique_user_key,
                v.path,
                v.timestamp,
                CASE WHEN v.path = LAG(v.path) OVER (PARTITION BY COALESCE(v.client_id, v.session_id) ORDER BY v.timestamp ASC) 
                     THEN 1 ELSE 0 END as is_duplicate
            FROM visits v
            INNER JOIN schedule_converters sc ON COALESCE(v.client_id, v.session_id) = sc.unique_user_key
            WHERE v.timestamp <= sc.first_scheduled_at
              AND v.timestamp >= NOW() - INTERVAL '1 day' * :days
        ),
        forms_captured AS (
            -- 5. Aggregate form-submit events
            SELECT 
                COALESCE(ve.client_id, ve.session_id) as unique_user_key,
                STRING_AGG(
                    DISTINCT ('Form on ' || ve.path || ': ' || ve.event_data::text), 
                    ' | '
                ) as journey_forms
            FROM visit_events ve
            INNER JOIN schedule_converters sc ON COALESCE(ve.client_id, ve.session_id) = sc.unique_user_key
            WHERE ve.event_type = 'form_submit'
            AND ve.timestamp <= sc.first_scheduled_at
            AND ve.timestamp >= NOW() - INTERVAL '1 day' * :days
            -- Filter out performance/RUM noise that might be misclassified
            AND ve.event_data::text NOT LIKE '%timingsV2%' 
            AND ve.event_data::text NOT LIKE '%memory.totalJSHeapSize%'
            AND ve.event_data::text NOT LIKE '%eventType%'
            GROUP BY 1
        )
        SELECT 
            jd.unique_user_key,
            
            -- Combine URL data and form submissions
            COALESCE(cp.extracted_params, fc.journey_forms, 'No info shared') as form_data_shared,
            
            -- Journey Details
            STRING_AGG(jd.path, ' → ' ORDER BY jd.timestamp ASC) as journey_to_schedule,
            
            -- Attribution
            ua.original_referrer,
            ua.original_utm_source,
            ua.original_utm_medium,
            
            -- Stats
            ua.first_ever_visit AT TIME ZONE 'UTC' as user_acquired_at,
            sc.first_scheduled_at AT TIME ZONE 'UTC' as conversion_at,
            EXTRACT(EPOCH FROM (sc.first_scheduled_at - ua.first_ever_visit)) as time_to_convert_seconds
        FROM journey_data jd
        JOIN schedule_converters sc ON jd.unique_user_key = sc.unique_user_key
        JOIN user_attribution ua ON jd.unique_user_key = ua.unique_user_key
        LEFT JOIN converters_with_params cp ON jd.unique_user_key = cp.unique_user_key
        LEFT JOIN forms_captured fc ON jd.unique_user_key = fc.unique_user_key
        WHERE jd.is_duplicate = 0
        GROUP BY 
            jd.unique_user_key, 
            cp.extracted_params, 
            fc.journey_forms, 
            ua.original_referrer, 
            ua.original_utm_source, 
            ua.original_utm_medium, 
            ua.first_ever_visit, 
            sc.first_scheduled_at
        ORDER BY conversion_at DESC;
        """)
        
        try:
            # Set a custom timeout for this heavy query
            db.execute(text("SET statement_timeout = 60000")) # 60 seconds
            
            results = db.execute(sql, {"path_regex": clean_path, "days": days}).mappings().all()
            
            # Format the results
            return [
                {
                    "unique_user_key": row["unique_user_key"],
                    "form_data_shared": row["form_data_shared"],
                    "journey_to_conversion": row["journey_to_schedule"],
                    "original_referrer": row["original_referrer"],
                    "original_utm_source": row["original_utm_source"],
                    "original_utm_medium": row["original_utm_medium"],
                    "user_acquired_at": row["user_acquired_at"].isoformat() if row["user_acquired_at"] else None,
                    "conversion_at": row["conversion_at"].isoformat() if row["conversion_at"] else None,
                    "time_to_convert_seconds": row["time_to_convert_seconds"]
                }
                for row in results
            ]
        except Exception as e:
            logger.error("Error analyzing journey path", error=str(e), target_path=target_path)
            raise e

    def get_live_events(self, db: Session, limit: int = 100) -> List[Dict[str, Any]]:
        """Get the most recent live tracking events (excludes heartbeat noise)."""
        try:
            events = db.query(VisitEvent).filter(
                VisitEvent.event_type != 'heartbeat'  # Filter out heartbeat noise
            ).order_by(
                VisitEvent.timestamp.desc()
            ).limit(limit).all()
            
            return [
                {
                    "id": event.id,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                    "event_type": event.event_type,
                    "page_url": event.page_url,
                    "path": event.path,
                    "referrer": event.referrer,
                    "client_id": event.client_id,
                    "session_id": event.session_id,
                    "source": event.source,
                    "medium": event.medium,
                    "campaign": event.campaign,
                    "event_data": event.event_data,
                    "page_domain": event.page_domain,
                    "referrer_domain": event.referrer_domain,
                }
                for event in events
            ]
        except Exception as e:
            logger.error("Error getting live events", error=str(e))
            return []

    def get_live_events_since(self, db: Session, last_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get live tracking events since a given ID (excludes heartbeat noise)."""
        try:
            events = db.query(VisitEvent).filter(
                VisitEvent.id > last_id,
                VisitEvent.event_type != 'heartbeat'  # Filter out heartbeat noise
            ).order_by(
                VisitEvent.timestamp.desc()
            ).limit(limit).all()
            
            return [
                {
                    "id": event.id,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                    "event_type": event.event_type,
                    "page_url": event.page_url,
                    "path": event.path,
                    "referrer": event.referrer,
                    "client_id": event.client_id,
                    "session_id": event.session_id,
                    "source": event.source,
                    "medium": event.medium,
                    "campaign": event.campaign,
                    "event_data": event.event_data,
                    "page_domain": event.page_domain,
                    "referrer_domain": event.referrer_domain,
                }
                for event in events
            ]
        except Exception as e:
            logger.error("Error getting live events since ID", error=str(e), last_id=last_id)
            return []
