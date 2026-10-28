"""Simplified analytics API for visitor insights."""
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import structlog
import csv
import io
import json
import asyncio
import re
from pydantic import BaseModel, Field

from app.database import get_db, SessionLocal
from app.config import settings
from app.services.analytics import AnalyticsService
from app.services.reports import ReportsService
from app.utils.auth import get_current_user, verify_export_api_key
from app.models.user import User

logger = structlog.get_logger()

router = APIRouter(prefix="/analytics", tags=["analytics"])
analytics_service = AnalyticsService()
reports_service = ReportsService()


def _day_range(start_date: Optional[str], end_date: Optional[str]):
    """YYYY-MM-DD query params as UTC datetimes covering whole days (None when not given)."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
    except ValueError:
        raise HTTPException(status_code=422, detail="Dates must be YYYY-MM-DD")
    return start_dt, end_dt


@router.get("/summary")
async def get_visitor_summary(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get visitor summary by category."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        return analytics_service.get_visitor_summary(db, days=days, start_date=start_dt, end_date=end_dt)
    except Exception as e:
        logger.error("Failed to get visitor summary", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get analytics")


@router.get("/funnels")
async def get_funnel_summary(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get funnel summaries for key conversion paths."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        config = analytics_service.get_funnel_config(db, current_user.id)
        return analytics_service.get_funnel_summary(db, start_date=start_dt, end_date=end_dt, config=config)
    except Exception as e:
        logger.error("Failed to get funnel summary", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get funnel summary")


class FunnelStepConfig(BaseModel):
    label: str
    type: str = Field("page", pattern="^(page|event)$")
    path: str
    event_type: Optional[str] = "form_submit"


class FunnelDefinition(BaseModel):
    key: str
    label: str
    steps: List[FunnelStepConfig]


class FunnelConfigPayload(BaseModel):
    funnels: List[FunnelDefinition]


@router.get("/funnels/config")
async def get_funnel_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get funnel configuration for the current user."""
    try:
        return analytics_service.get_funnel_config(db, current_user.id)
    except Exception as e:
        logger.error("Failed to get funnel config", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get funnel config")


@router.put("/funnels/config")
async def update_funnel_config(
    payload: FunnelConfigPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update funnel configuration for the current user."""
    try:
        return analytics_service.save_funnel_config(db, current_user.id, payload.dict())
    except Exception as e:
        logger.error("Failed to update funnel config", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to update funnel config")


@router.get("/funnels/{funnel_key}/timing")
async def get_funnel_timing(
    funnel_key: str,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    max_rows: int = Query(5000, ge=100, le=50000, description="Max samples for timing stats"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get time-to-convert metrics for a funnel."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        config = analytics_service.get_funnel_config(db, current_user.id)
        data = analytics_service.get_funnel_time_metrics(
            db,
            funnel_key=funnel_key,
            config=config,
            start_date=start_dt,
            end_date=end_dt,
            max_rows=max_rows,
        )
        if data.get("error") == "not_found":
            raise HTTPException(status_code=404, detail="Funnel not found")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get funnel timing", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get funnel timing")


@router.get("/funnels/{funnel_key}/dropoffs")
async def get_funnel_dropoffs(
    funnel_key: str,
    step: int = Query(0, ge=0, description="Step index to compute drop-offs after"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get users who dropped off after a given funnel step."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        config = analytics_service.get_funnel_config(db, current_user.id)
        data = analytics_service.get_funnel_dropoffs(
            db,
            funnel_key=funnel_key,
            step_index=step,
            config=config,
            start_date=start_dt,
            end_date=end_dt,
            limit=limit,
            offset=offset,
        )
        if data.get("error") == "not_found":
            raise HTTPException(status_code=404, detail="Funnel not found")
        if data.get("error") == "invalid_step":
            raise HTTPException(status_code=400, detail="Invalid step index")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get funnel dropoffs", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get funnel dropoffs")


@router.get("/funnels/{funnel_key}/stage-users")
async def get_funnel_stage_users(
    funnel_key: str,
    step: int = Query(0, ge=0, description="Step index to list users who reached"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get users who reached a funnel stage with journey details."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        config = analytics_service.get_funnel_config(db, current_user.id)
        data = analytics_service.get_funnel_stage_users(
            db,
            funnel_key=funnel_key,
            step_index=step,
            config=config,
            start_date=start_dt,
            end_date=end_dt,
            limit=limit,
            offset=offset,
        )
        if data.get("error") == "not_found":
            raise HTTPException(status_code=404, detail="Funnel not found")
        if data.get("error") == "invalid_step":
            raise HTTPException(status_code=400, detail="Invalid step index")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get funnel stage users", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get funnel stage users")


@router.get("/pages")
async def get_page_analytics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get page analytics."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        return analytics_service.get_page_analytics(db, days=days, start_date=start_dt, end_date=end_dt)
    except Exception as e:
        logger.error("Failed to get page analytics", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get page analytics")


@router.get("/recent")
async def get_recent_activity(
    limit: int = Query(50, ge=1, le=200, description="Number of recent visits to return"),
    offset: int = Query(0, ge=0, description="Number of visits to skip"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    visitor: Optional[str] = Query(None, max_length=100, description="human, bot, or one crawler_type (e.g. GoogleBot)"),
    path: Optional[str] = Query(None, max_length=500, description="Page path contains"),
    source: Optional[str] = Query(None, max_length=100, description="Source (utm_source or referrer host) contains"),
    country: Optional[str] = Query(None, min_length=2, max_length=2, description="Two-letter country code"),
    domain: Optional[str] = Query(None, max_length=200, description="Exact page domain"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get recent visitor activity with pagination."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        return analytics_service.get_recent_activity(
            db, limit=limit, offset=offset, start_date=start_dt, end_date=end_dt,
            visitor=visitor, path=path, source=source, country=country, domain=domain,
        )
    except Exception as e:
        logger.error("Failed to get recent activity", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get recent activity")


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=200, description="Number of sessions to return"),
    offset: int = Query(0, ge=0, description="Number of sessions to skip"),
    start_date: Optional[str] = Query(None, description="Last active on or after (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Last active on or before (YYYY-MM-DD)"),
    visitor: Optional[str] = Query(None, pattern="^(human|bot)$", description="human or bot"),
    country: Optional[str] = Query(None, min_length=2, max_length=2, description="Two-letter country code"),
    referrer: Optional[str] = Query(None, max_length=200, description="Entry referrer domain contains, or 'direct'"),
    has_client_id: Optional[bool] = Query(None, description="Only sessions with (true) or without (false) a client ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List sessions with summary information."""
    start_dt, end_dt = _day_range(start_date, end_date)
    try:
        return analytics_service.list_sessions(
            db, limit=limit, offset=offset, start_date=start_dt, end_date=end_dt,
            visitor=visitor, country=country, referrer=referrer, has_client_id=has_client_id,
        )
    except Exception as e:
        logger.error("Failed to list sessions", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to list sessions")


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a session detail including visits and events timeline."""
    try:
        data = analytics_service.get_session_detail(db, session_id)
        if data.get("error") == "not_found":
            raise HTTPException(status_code=404, detail="Session not found")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get session detail", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get session detail")


@router.get("/categories")
async def get_visitor_categories(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get detailed visitor categorization."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        return analytics_service.get_visitor_categories(db, days=days, start_date=start_dt, end_date=end_dt)
    except Exception as e:
        logger.error("Failed to get visitor categories", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get visitor categories")


@router.get("/users")
async def list_unified_users(
    limit: int = Query(50, ge=1, le=200, description="Number of users to return"),
    offset: int = Query(0, ge=0, description="Number of users to skip"),
    start_date: Optional[str] = Query(None, description="Active on or after (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Active on or before (YYYY-MM-DD)"),
    q: Optional[str] = Query(None, max_length=255, description="Client ID (or its start), email or name"),
    converted: bool = Query(False, description="Only people who submitted a form"),
    source: Optional[str] = Query(None, max_length=100, description="Any visit's source in the range contains"),
    visitor: Optional[str] = Query(None, pattern="^(human|bot)$", description="human or bot"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List unique users by client_id with their activity summary."""
    start_dt, end_dt = _day_range(start_date, end_date)
    try:
        return analytics_service.list_unified_users(
            db, limit=limit, offset=offset, start_date=start_dt, end_date=end_dt,
            q=q, converted=converted, source=source, visitor=visitor,
        )
    except Exception as e:
        logger.error("Failed to list unified users", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to list unified users")


@router.get("/users/{client_id}")
async def get_unified_user_activity(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all activity (sessions, visits, events) for a unified user by client_id."""
    try:
        data = analytics_service.get_unified_user_activity(db, client_id)
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get unified user activity", error=str(e), client_id=client_id)
        raise HTTPException(status_code=500, detail="Failed to get user activity")


@router.get("/journeys")
async def list_journeys(
    target_path: Optional[str] = Query(None, description="Target path(s) to filter journeys. Supports exact match and subpaths (e.g., /demo matches /demo and /demo/*). Use comma-separated values for multiple paths (ALL must be present in journey)."),
    with_captured_only: bool = Query(False, description="Only include journeys with captured data"),
    start_date: Optional[str] = Query(None, description="Start date for date range filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date for date range filter (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200, description="Number of journeys to return"),
    offset: int = Query(0, ge=0, description="Number of journeys to skip"),
    source: Optional[str] = Query(None, max_length=100, description="First-touch source (case-insensitive; 'direct' for none)"),
    campaign: Optional[str] = Query(None, max_length=100, description="First-touch campaign (case-insensitive; 'none' for none)"),
    sort: Optional[str] = Query(None, pattern="^(last_seen|first_seen|visit_count|form_fill_count)$", description="Sort column"),
    order: Optional[str] = Query(None, pattern="^(asc|desc)$", description="Sort direction (default desc)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List journey summaries grouped by client_id with optional filters."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        if not start_dt and not end_dt:
            start_dt = datetime.now(timezone.utc) - timedelta(days=30)
        return analytics_service.list_journey_summaries(
            db,
            target_path=target_path,
            with_captured_only=with_captured_only,
            start_date=start_dt,
            end_date=end_dt,
            limit=limit,
            offset=offset,
            source=source,
            campaign=campaign,
            sort=sort,
            order=order,
        )
    except Exception as e:
        logger.error("Failed to list journeys", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to list journeys")


@router.get("/journeys/export")
@router.get("/journeys/export.csv")
async def export_journeys_csv(
    target_path: Optional[str] = Query(None, description="Target path(s) to filter journeys. Supports exact match and subpaths (e.g., /demo matches /demo and /demo/*). Use comma-separated values for multiple paths (ALL must be present in journey)."),
    with_captured_only: bool = Query(False, description="Only include journeys with captured data"),
    start_date: Optional[str] = Query(None, description="Start date for date range filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date for date range filter (YYYY-MM-DD)"),
    source: Optional[str] = Query(None, max_length=100, description="First-touch source (case-insensitive; 'direct' for none)"),
    campaign: Optional[str] = Query(None, max_length=100, description="First-touch campaign (case-insensitive; 'none' for none)"),
    sort: Optional[str] = Query(None, pattern="^(last_seen|first_seen|visit_count|form_fill_count)$", description="Sort column"),
    order: Optional[str] = Query(None, pattern="^(asc|desc)$", description="Sort direction (default desc)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export journeys as CSV with optional filters."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        
        def generate_csv():
            output = io.StringIO()
            writer = None
            first_row = True
            try:
                for row in analytics_service.export_journey_summaries(
                    db,
                    target_path=target_path,
                    with_captured_only=with_captured_only,
                    start_date=start_dt,
                    end_date=end_dt,
                    source=source,
                    campaign=campaign,
                    sort=sort,
                    order=order,
                ):
                    if first_row:
                        fieldnames = row.keys()
                        writer = csv.DictWriter(output, fieldnames=fieldnames)
                        writer.writeheader()
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                        first_row = False
                    if writer:
                        writer.writerow(row)
                        if output.tell() > 8192:
                            yield output.getvalue()
                            output.truncate(0)
                            output.seek(0)
                if output.tell() > 0:
                    yield output.getvalue()
            finally:
                output.close()

        filename = f"crawldoctor_journeys_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error("Failed to export journeys CSV", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to export journeys")


@router.get("/leads")
async def list_leads(
    captured_path: Optional[str] = Query(None, description="Filter by captured form path (e.g., /demo)"),
    q: Optional[str] = Query(None, max_length=255, description="Name, email or form text (e.g. company) contains"),
    source: Optional[str] = Query(None, description="Filter by UTM source"),
    medium: Optional[str] = Query(None, description="Filter by UTM medium"),
    campaign: Optional[str] = Query(None, description="Filter by UTM campaign"),
    start_date: Optional[str] = Query(None, description="Start date for date range filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date for date range filter (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200, description="Number of leads to return"),
    offset: int = Query(0, ge=0, description="Number of leads to skip"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List captured leads with summary details."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        if not start_dt and not end_dt:
            start_dt = datetime.now(timezone.utc) - timedelta(days=30)
        return analytics_service.list_leads(
            db,
            q=q,
            captured_path=captured_path,
            source=source,
            medium=medium,
            campaign=campaign,
            start_date=start_dt,
            end_date=end_dt,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error("Failed to list leads", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to list leads")


@router.get("/leads/export")
@router.get("/leads/export.csv")
async def export_leads_csv(
    captured_path: Optional[str] = Query(None, description="Filter by captured form path (e.g., /demo)"),
    q: Optional[str] = Query(None, max_length=255, description="Name, email or form text (e.g. company) contains"),
    source: Optional[str] = Query(None, description="Filter by UTM source"),
    medium: Optional[str] = Query(None, description="Filter by UTM medium"),
    campaign: Optional[str] = Query(None, description="Filter by UTM campaign"),
    start_date: Optional[str] = Query(None, description="Start date for date range filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date for date range filter (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export captured leads as CSV with optional filters."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_date else None
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc) if end_date else None
        
        def generate_csv():
            output = io.StringIO()
            writer = None
            first_row = True
            try:
                for row in analytics_service.export_leads(
                    db,
                    q=q,
                    captured_path=captured_path,
                    source=source,
                    medium=medium,
                    campaign=campaign,
                    start_date=start_dt,
                    end_date=end_dt,
                ):
                    if first_row:
                        fieldnames = row.keys()
                        writer = csv.DictWriter(output, fieldnames=fieldnames)
                        writer.writeheader()
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                        first_row = False
                    if writer:
                        writer.writerow(row)
                        if output.tell() > 8192:
                            yield output.getvalue()
                            output.truncate(0)
                            output.seek(0)
                if output.tell() > 0:
                    yield output.getvalue()
            finally:
                output.close()

        filename = f"crawldoctor_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error("Failed to export leads CSV", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to export leads")


@router.get("/leads/{client_id}")
async def get_lead_detail(
    client_id: str,
    limit: int = Query(200, ge=1, le=1000, description="Number of timeline items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed lead info including journey timeline."""
    try:
        data = analytics_service.get_lead_detail(db, client_id, limit=limit, offset=offset)
        if data.get("error"):
            raise HTTPException(status_code=404, detail=data["error"])
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get lead detail", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get lead detail")


@router.get("/journeys/analyze")
async def analyze_journey_path(
    target_path: str = Query(..., description="Target path regex or string to analyze (e.g., /schedule)"),
    days: int = Query(30, ge=1, le=90, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze journeys for a specific target path using dynamic SQL."""
    try:
        return analytics_service.analyze_journey_path(db, target_path=target_path, days=days)
    except Exception as e:
        logger.error("Failed to analyze journey path", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to analyze journey path")


@router.get("/journeys/{client_id}")
async def get_user_journey(
    client_id: str,
    limit: int = Query(200, ge=1, le=1000, description="Number of timeline items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a unified journey timeline for a client_id."""
    try:
        return analytics_service.get_journey_timeline(db, client_id, limit=limit, offset=offset)
    except Exception as e:
        logger.error("Failed to get journey timeline", error=str(e), client_id=client_id)
        raise HTTPException(status_code=500, detail="Failed to get journey timeline")


@router.get("/flows")
async def get_page_flows(
    days: int = Query(7, ge=1, le=90, description="Number of days to analyze"),
    limit: int = Query(100, ge=1, le=500, description="Number of flows to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get page-to-page flow summary."""
    try:
        return analytics_service.get_page_flow_summary(db, days=days, limit=limit)
    except Exception as e:
        logger.error("Failed to get page flows", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get page flows")


FACET_FIELDS = "|".join(re.escape(f) for f in ReportsService.FACETS)


@router.get("/facets")
async def get_facet(
    field: str = Query(..., pattern=f"^({FACET_FIELDS})$", description="dataset.column, e.g. visits.source or leads.captured_path"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD); defaults to 30 days ago"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    humans_only: bool = Query(False, description="visits.* only: leave out bots"),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The most common values of a column in the range, for filter suggestions."""
    start_dt, end_dt = _day_range(start_date, end_date)
    try:
        return reports_service.facet(db, field, start_dt, end_dt, humans_only=humans_only, limit=limit)
    except Exception as e:
        logger.error("Failed to get facet", field=field, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get filter values")


@router.get("/timeseries")
async def get_timeseries(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD); defaults to 30 days ago"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Page views per UTC day and crawler label ("Human" for people)."""
    start_dt, end_dt = _day_range(start_date, end_date)
    try:
        return reports_service.timeseries(db, start_dt, end_dt)
    except Exception as e:
        logger.error("Failed to get timeseries", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get daily trend")


@router.get("/top-pages")
async def get_top_pages(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD); defaults to 30 days ago"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    humans_only: bool = Query(True, description="Leave out bots and crawlers"),
    domain: Optional[str] = Query(None, max_length=200, description="Exact page domain"),
    path: Optional[str] = Query(None, max_length=500, description="Path contains"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Page views and unique visitors per page (domain + path)."""
    start_dt, end_dt = _day_range(start_date, end_date)
    try:
        return reports_service.top_pages(db, start_dt, end_dt, humans_only=humans_only, domain=domain, path=path, limit=limit)
    except Exception as e:
        logger.error("Failed to get top pages", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get top pages")


@router.get("/channels")
async def get_channels(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD); defaults to 30 days ago"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Human traffic and leads grouped into Search, AI assistants, Social, Referral, Paid, Direct and Internal."""
    start_dt, end_dt = _day_range(start_date, end_date)
    try:
        return reports_service.channels(db, start_dt, end_dt)
    except Exception as e:
        logger.error("Failed to get channels", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get channels")


@router.get("/ai-referrals")
async def get_ai_referrals(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD); defaults to 30 days ago"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Visits, landing pages and leads referred by AI assistants (ChatGPT, Perplexity, Claude, Gemini, Copilot…)."""
    start_dt, end_dt = _day_range(start_date, end_date)
    try:
        return reports_service.ai_referrals(db, start_dt, end_dt)
    except Exception as e:
        logger.error("Failed to get AI referrals", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get AI referrals")


@router.get("/companies")
async def get_companies(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD); defaults to 30 days ago"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Companies behind human visits (IP enrichment, without ISPs, hosts, VPNs and proxies), with coverage."""
    start_dt, end_dt = _day_range(start_date, end_date)
    try:
        return reports_service.companies(db, start_dt, end_dt, limit=limit)
    except Exception as e:
        logger.error("Failed to get companies", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get companies")


@router.get("/tracking-health")
async def get_tracking_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Last page view per tracked site and tracking ID, with live / quiet / stale status."""
    try:
        return reports_service.tracking_health(db)
    except Exception as e:
        logger.error("Failed to get tracking health", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get tracking health")


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=2000, description="Email, name, client ID, session ID or URL"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Find the visitor, session or page a pasted value points at."""
    try:
        return reports_service.search(db, q)
    except Exception as e:
        logger.error("Search failed", error=str(e))
        raise HTTPException(status_code=500, detail="Search failed")


@router.get("/export/csv")
async def export_visits_csv(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export visits as CSV with optional date filtering. Optimized for large datasets with retry logic."""
    try:
        # Parse dates if provided
        start_datetime = None
        end_datetime = None
        if start_date:
            start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            end_datetime = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        
        logger.info("Starting CSV export", start_date=start_date, end_date=end_date, user=current_user.username)
        
        # Create CSV generator that streams data with error handling
        def generate_csv():
            output = io.StringIO()
            writer = None
            first_row = True
            row_count = 0
            
            try:
                for visit_data in analytics_service.get_all_visits_for_export(db, start_date=start_datetime, end_date=end_datetime):
                    if first_row:
                        # Write header on first row
                        fieldnames = visit_data.keys()
                        writer = csv.DictWriter(output, fieldnames=fieldnames)
                        writer.writeheader()
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                        first_row = False
                    
                    # Write data row
                    writer.writerow(visit_data)
                    row_count += 1
                    
                    # Yield and clear buffer periodically for memory efficiency
                    if output.tell() > 8192:  # 8KB chunks for better streaming
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                
                # Yield remaining data
                if output.tell() > 0:
                    yield output.getvalue()
                
                logger.info(f"CSV export completed successfully", rows=row_count)
            except Exception as e:
                logger.error("Error during CSV generation", error=str(e), rows_processed=row_count)
                # Write error message to CSV
                if writer:
                    error_row = {key: "" for key in writer.fieldnames}
                    error_row[list(writer.fieldnames)[0]] = f"Export interrupted after {row_count} rows: {str(e)}"
                    writer.writerow(error_row)
                    yield output.getvalue()
            finally:
                output.close()
        
        # Generate filename with date range
        date_suffix = f"{start_date or 'all'}_{end_date or 'all'}"
        filename = f"crawldoctor_visits_{date_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Export-Info": f"start={start_date or 'all'};end={end_date or 'all'}"
            }
        )
    except Exception as e:
        logger.error("Failed to export CSV", error=str(e), start_date=start_date, end_date=end_date)
        raise HTTPException(
            status_code=500, 
            detail=f"Export failed: {str(e)}. For very large datasets, try a shorter date range."
        )


@router.get("/export/events.csv")
async def export_events_csv(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export events as CSV with optional date filtering. Optimized for large datasets with retry logic."""
    try:
        # Parse dates if provided
        start_datetime = None
        end_datetime = None
        if start_date:
            start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            end_datetime = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        
        logger.info("Starting events CSV export", start_date=start_date, end_date=end_date, user=current_user.username)
        
        # Create CSV generator that streams data with error handling
        def generate_csv():
            output = io.StringIO()
            writer = None
            first_row = True
            row_count = 0
            
            try:
                for event_data in analytics_service.get_all_events_for_export(db, start_date=start_datetime, end_date=end_datetime):
                    if first_row:
                        # Write header on first row
                        fieldnames = event_data.keys()
                        writer = csv.DictWriter(output, fieldnames=fieldnames)
                        writer.writeheader()
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                        first_row = False
                    
                    # Write data row
                    writer.writerow(event_data)
                    row_count += 1
                    
                    # Yield and clear buffer periodically for memory efficiency
                    if output.tell() > 8192:  # 8KB chunks for better streaming
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                
                # Yield remaining data
                if output.tell() > 0:
                    yield output.getvalue()
                
                logger.info(f"Events CSV export completed successfully", rows=row_count)
            except Exception as e:
                logger.error("Error during events CSV generation", error=str(e), rows_processed=row_count)
                # Write error message to CSV
                if writer:
                    error_row = {key: "" for key in writer.fieldnames}
                    error_row[list(writer.fieldnames)[0]] = f"Export interrupted after {row_count} rows: {str(e)}"
                    writer.writerow(error_row)
                    yield output.getvalue()
            finally:
                output.close()
        
        # Generate filename with date range
        date_suffix = f"{start_date or 'all'}_{end_date or 'all'}"
        filename = f"crawldoctor_events_{date_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Export-Info": f"start={start_date or 'all'};end={end_date or 'all'}"
            }
        )
    except Exception as e:
        logger.error("Failed to export events CSV", error=str(e), start_date=start_date, end_date=end_date)
        raise HTTPException(
            status_code=500, 
            detail=f"Export failed: {str(e)}. For very large datasets, try a shorter date range."
        )


@router.delete("/visits/all")
async def delete_all_visits(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete all visit data. Requires admin privileges."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    try:
        result = analytics_service.delete_all_visits(db)
        if result["success"]:
            logger.info("All visits deleted", user=current_user.username, **result)
            return result
        else:
            logger.error("Failed to delete visits", error=result.get("error"))
            raise HTTPException(status_code=500, detail=result["message"])
    except Exception as e:
        logger.error("Failed to delete visits", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to delete data")


@router.post("/visits/backfill-locations")
async def backfill_visit_locations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Backfill missing location data in visits from sessions. Requires admin privileges."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    try:
        result = analytics_service.backfill_visit_locations(db)
        if result["success"]:
            logger.info("Visit locations backfilled", user=current_user.username, **result)
            return result
        else:
            logger.error("Failed to backfill locations", error=result.get("error"))
            raise HTTPException(status_code=500, detail=result["message"])
    except Exception as e:
        logger.error("Failed to backfill locations", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to backfill location data")


@router.post("/events/backfill-locations")
async def backfill_event_locations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Backfill missing location data in events from visits and sessions. Requires admin privileges."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    try:
        result = analytics_service.backfill_event_locations(db)
        if result["success"]:
            logger.info("Event locations backfilled", user=current_user.username, **result)
            return result
        else:
            logger.error("Failed to backfill event locations", error=result.get("error"))
            raise HTTPException(status_code=500, detail=result["message"])
    except Exception as e:
        logger.error("Failed to backfill event locations", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to backfill event location data")


@router.post("/sessions/backfill-locations")
async def backfill_session_locations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Backfill missing location data in sessions from their visits. Requires admin privileges."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    try:
        result = analytics_service.backfill_session_locations(db)
        if result["success"]:
            logger.info("Session locations backfilled", user=current_user.username, **result)
            return result
        else:
            logger.error("Failed to backfill session locations", error=result.get("error"))
            raise HTTPException(status_code=500, detail=result["message"])
    except Exception as e:
        logger.error("Failed to backfill session locations", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to backfill session location data")


@router.post("/backfill-all-locations")
async def backfill_all_locations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Backfill missing location data in sessions, visits, and events. Requires admin privileges."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin privileges required")

    try:
        results = {}

        # Backfill sessions first (as they may be used by visits and events)
        session_result = analytics_service.backfill_session_locations(db)
        results["sessions"] = session_result

        # Backfill visits next (they may be used by events)
        visit_result = analytics_service.backfill_visit_locations(db)
        results["visits"] = visit_result

        # Backfill events last (they use sessions and visits for fallback)
        event_result = analytics_service.backfill_event_locations(db)
        results["events"] = event_result

        total_updated = (
            results["sessions"].get("updated_sessions", 0) +
            results["visits"].get("updated_visits", 0) +
            results["events"].get("updated_events", 0)
        )

        logger.info("All locations backfilled", user=current_user.username, total_updated=total_updated, **results)

        return {
            "success": True,
            "total_updated": total_updated,
            "results": results,
            "message": f"Successfully backfilled location data for {total_updated} total records"
        }
    except Exception as e:
        logger.error("Failed to backfill all locations", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to backfill location data")


# External API endpoints for programmatic access with static keys
# These endpoints are designed for external services to fetch CSV data

@router.get("/exports/visits")
async def api_export_visits(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_export_api_key)
):
    """
    Export visits as CSV for external services.

    This endpoint requires a valid export API key in the X-Export-API-Key header.
    Designed for programmatic access by external services.

    Query Parameters:
    - start_date: Start date in YYYY-MM-DD format (optional)
    - end_date: End date in YYYY-MM-DD format (optional)

    Returns:
    - CSV file with visit data
    """
    try:
        # Parse dates if provided
        start_datetime = None
        end_datetime = None
        if start_date:
            start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            end_datetime = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

        logger.info("External API visits export started", start_date=start_date, end_date=end_date)

        # Create CSV generator that streams data with error handling
        def generate_csv():
            output = io.StringIO()
            writer = None
            first_row = True
            row_count = 0

            try:
                for visit_data in analytics_service.get_all_visits_for_export(db, start_date=start_datetime, end_date=end_datetime):
                    if first_row:
                        # Write header on first row
                        fieldnames = visit_data.keys()
                        writer = csv.DictWriter(output, fieldnames=fieldnames)
                        writer.writeheader()
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                        first_row = False

                    # Write data row
                    writer.writerow(visit_data)
                    row_count += 1

                    # Yield and clear buffer periodically for memory efficiency
                    if output.tell() > 8192:  # 8KB chunks for better streaming
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)

                # Yield remaining data
                if output.tell() > 0:
                    yield output.getvalue()

                logger.info("External API visits export completed", rows=row_count, start_date=start_date, end_date=end_date)
            except Exception as e:
                logger.error("Error during external API visits CSV generation", error=str(e), rows_processed=row_count)
                # Write error message to CSV
                if writer:
                    error_row = {key: "" for key in writer.fieldnames}
                    error_row[list(writer.fieldnames)[0]] = f"Export interrupted after {row_count} rows: {str(e)}"
                    writer.writerow(error_row)
                    yield output.getvalue()
            finally:
                output.close()

        # Generate filename with date range and timestamp
        date_suffix = f"{start_date or 'all'}_{end_date or 'all'}"
        filename = f"crawldoctor_visits_{date_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Export-Source": "external-api",
                "X-Export-Date-Range": f"{start_date or 'all'}-{end_date or 'all'}"
            }
        )
    except Exception as e:
        logger.error("External API visits export failed", error=str(e), start_date=start_date, end_date=end_date)
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}. For very large datasets, try a shorter date range."
        )


@router.get("/exports/events")
async def api_export_events(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_export_api_key)
):
    """
    Export events as CSV for external services.

    This endpoint requires a valid export API key in the X-Export-API-Key header.
    Designed for programmatic access by external services.

    Query Parameters:
    - start_date: Start date in YYYY-MM-DD format (optional)
    - end_date: End date in YYYY-MM-DD format (optional)

    Returns:
    - CSV file with event data
    """
    try:
        # Parse dates if provided
        start_datetime = None
        end_datetime = None
        if start_date:
            start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            end_datetime = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

        logger.info("External API events export started", start_date=start_date, end_date=end_date)

        # Create CSV generator that streams data with error handling
        def generate_csv():
            output = io.StringIO()
            writer = None
            first_row = True
            row_count = 0

            try:
                for event_data in analytics_service.get_all_events_for_export(db, start_date=start_datetime, end_date=end_datetime):
                    if first_row:
                        # Write header on first row
                        fieldnames = event_data.keys()
                        writer = csv.DictWriter(output, fieldnames=fieldnames)
                        writer.writeheader()
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                        first_row = False

                    # Write data row
                    writer.writerow(event_data)
                    row_count += 1

                    # Yield and clear buffer periodically for memory efficiency
                    if output.tell() > 8192:  # 8KB chunks for better streaming
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)

                # Yield remaining data
                if output.tell() > 0:
                    yield output.getvalue()

                logger.info("External API events export completed", rows=row_count, start_date=start_date, end_date=end_date)
            except Exception as e:
                logger.error("Error during external API events CSV generation", error=str(e), rows_processed=row_count)
                # Write error message to CSV
                if writer:
                    error_row = {key: "" for key in writer.fieldnames}
                    error_row[list(writer.fieldnames)[0]] = f"Export interrupted after {row_count} rows: {str(e)}"
                    writer.writerow(error_row)
                    yield output.getvalue()
            finally:
                output.close()

        # Generate filename with date range and timestamp
        date_suffix = f"{start_date or 'all'}_{end_date or 'all'}"
        filename = f"crawldoctor_events_{date_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Export-Source": "external-api",
                "X-Export-Date-Range": f"{start_date or 'all'}-{end_date or 'all'}"
            }
        )
    except Exception as e:
        logger.error("External API events export failed", error=str(e), start_date=start_date, end_date=end_date)
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}. For very large datasets, try a shorter date range."
        )


@router.get("/exports/visits/{date}")
async def api_export_visits_single_date(
    date: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_export_api_key)
):
    """
    Export visits for a specific date.

    This endpoint requires a valid export API key in the X-Export-API-Key header.

    Path Parameters:
    - date: Date in YYYY-MM-DD format

    Returns:
    - CSV file with visit data for the specified date
    """
    try:
        # Parse the date
        target_date = datetime.strptime(date, "%Y-%m-%d")
        start_datetime = target_date.replace(hour=0, minute=0, second=0)
        end_datetime = target_date.replace(hour=23, minute=59, second=59)

        logger.info("External API single date visits export", date=date)

        # Create CSV generator that streams data with error handling
        def generate_csv():
            output = io.StringIO()
            writer = None
            first_row = True
            row_count = 0

            try:
                for visit_data in analytics_service.get_all_visits_for_export(db, start_date=start_datetime, end_date=end_datetime):
                    if first_row:
                        # Write header on first row
                        fieldnames = visit_data.keys()
                        writer = csv.DictWriter(output, fieldnames=fieldnames)
                        writer.writeheader()
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                        first_row = False

                    # Write data row
                    writer.writerow(visit_data)
                    row_count += 1

                    # Yield and clear buffer periodically for memory efficiency
                    if output.tell() > 8192:
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)

                # Yield remaining data
                if output.tell() > 0:
                    yield output.getvalue()

                logger.info("External API single date visits export completed", date=date, rows=row_count)
            except Exception as e:
                logger.error("Error during single date visits CSV generation", error=str(e), rows_processed=row_count)
                if writer:
                    error_row = {key: "" for key in writer.fieldnames}
                    error_row[list(writer.fieldnames)[0]] = f"Export interrupted after {row_count} rows: {str(e)}"
                    writer.writerow(error_row)
                    yield output.getvalue()
            finally:
                output.close()

        filename = f"crawldoctor_visits_{date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Export-Source": "external-api",
                "X-Export-Date": date
            }
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    except Exception as e:
        logger.error("External API single date visits export failed", error=str(e), date=date)
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.get("/exports/events/{date}")
async def api_export_events_single_date(
    date: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_export_api_key)
):
    """
    Export events for a specific date.

    This endpoint requires a valid export API key in the X-Export-API-Key header.

    Path Parameters:
    - date: Date in YYYY-MM-DD format

    Returns:
    - CSV file with event data for the specified date
    """
    try:
        # Parse the date
        target_date = datetime.strptime(date, "%Y-%m-%d")
        start_datetime = target_date.replace(hour=0, minute=0, second=0)
        end_datetime = target_date.replace(hour=23, minute=59, second=59)

        logger.info("External API single date events export", date=date)

        # Create CSV generator that streams data with error handling
        def generate_csv():
            output = io.StringIO()
            writer = None
            first_row = True
            row_count = 0

            try:
                for event_data in analytics_service.get_all_events_for_export(db, start_date=start_datetime, end_date=end_datetime):
                    if first_row:
                        # Write header on first row
                        fieldnames = event_data.keys()
                        writer = csv.DictWriter(output, fieldnames=fieldnames)
                        writer.writeheader()
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)
                        first_row = False

                    # Write data row
                    writer.writerow(event_data)
                    row_count += 1

                    # Yield and clear buffer periodically for memory efficiency
                    if output.tell() > 8192:
                        yield output.getvalue()
                        output.truncate(0)
                        output.seek(0)

                # Yield remaining data
                if output.tell() > 0:
                    yield output.getvalue()

                logger.info("External API single date events export completed", date=date, rows=row_count)
            except Exception as e:
                logger.error("Error during single date events CSV generation", error=str(e), rows_processed=row_count)
                if writer:
                    error_row = {key: "" for key in writer.fieldnames}
                    error_row[list(writer.fieldnames)[0]] = f"Export interrupted after {row_count} rows: {str(e)}"
                    writer.writerow(error_row)
                    yield output.getvalue()
            finally:
                output.close()

        filename = f"crawldoctor_events_{date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            generate_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Export-Source": "external-api",
                "X-Export-Date": date
            }
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    except Exception as e:
        logger.error("External API single date events export failed", error=str(e), date=date)
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.get("/exports/status")
async def api_export_status(
    _: bool = Depends(verify_export_api_key)
):
    """
    Get export API status and configuration.

    This endpoint requires a valid export API key in the X-Export-API-Key header.

    Returns:
    - API status and available endpoints
    """
    return {
        "status": "active",
        "service": "CrawlDoctor Export API",
        "version": settings.app_version,
        "endpoints": {
            "visits_range": "/api/v1/analytics/exports/visits?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD",
            "events_range": "/api/v1/analytics/exports/events?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD",
            "visits_date": "/api/v1/analytics/exports/visits/YYYY-MM-DD",
            "events_date": "/api/v1/analytics/exports/events/YYYY-MM-DD",
            "status": "/api/v1/analytics/exports/status"
        },
        "authentication": "X-Export-API-Key header required",
        "rate_limits": "Based on API key configuration",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/live-events")
async def get_live_events(
    limit: int = Query(100, ge=1, le=500, description="Number of recent events to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get the most recent live tracking events."""
    try:
        events = analytics_service.get_live_events(db, limit=limit)
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.error("Failed to get live events", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get live events")


@router.get("/live-stream")
async def live_event_stream(
    current_user: User = Depends(get_current_user)
):
    """
    Server-Sent Events stream for real-time tracking events.
    Streams new events as they arrive in the database.
    
    IMPORTANT: We create a new DB session for each poll to avoid holding
    connections open for extended periods, which would exhaust the pool.
    """
    async def event_generator():
        last_id = 0
        
        # Send initial batch with its own session
        db = SessionLocal()
        try:
            initial_events = analytics_service.get_live_events(db, limit=10)
            if initial_events:
                last_id = max(e.get('id', 0) for e in initial_events)
                for event in initial_events:
                    yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.error("Error getting initial events", error=str(e))
        finally:
            db.close()
        
        # Poll for new events - create new session for each poll
        while True:
            try:
                await asyncio.sleep(2)  # Poll every 2 seconds
                
                # Create a new session for this poll
                db = SessionLocal()
                try:
                    # Get events newer than last_id
                    new_events = analytics_service.get_live_events_since(db, last_id, limit=50)
                    
                    if new_events:
                        last_id = max(e.get('id', last_id) for e in new_events)
                        for event in new_events:
                            yield f"data: {json.dumps(event)}\n\n"
                finally:
                    # Always close the session after each poll
                    db.close()
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in live stream", error=str(e))
                await asyncio.sleep(5)  # Wait longer on error
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
