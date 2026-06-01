"""Simplified tracking API for logging ALL visits."""
from datetime import datetime
from pathlib import Path
from typing import Optional
import json
from fastapi import APIRouter, Request, Response, Depends, Query, HTTPException
from sqlalchemy.orm import Session
import rjsmin
import structlog

from app.config import settings
from app.database import get_db
from app.services.tracking import TrackingService
from app.utils.rate_limiting import RateLimiter

logger = structlog.get_logger()

router = APIRouter(prefix="/track", tags=["tracking"])
tracking_service = TrackingService()
rate_limiter = RateLimiter()

# Read tracker source once at import time, minify with rjsmin, cache in memory.
# Edit the readable source at app/static/tracker.js — this string is derived automatically.
_TRACKER_SOURCE_PATH = Path(__file__).resolve().parent.parent / "static" / "tracker.js"
_JS_TEMPLATE_MINIFIED = rjsmin.jsmin(_TRACKER_SOURCE_PATH.read_text())

def _get_client_ip(request: Request) -> str:
    """Extract client IP considering reverse proxy headers."""
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # XFF may contain multiple IPs, take the first
            ip = xff.split(",")[0].strip()
            if ip:
                return ip
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip()
        fwd = request.headers.get("forwarded")
        if fwd and "for=" in fwd:
            # e.g., for=1.2.3.4;proto=https;by=...
            try:
                part = [p for p in fwd.split(";") if p.strip().lower().startswith("for=")][0]
                ip = part.split("=", 1)[1].strip().strip('"')
                # Remove optional port
                if ip.startswith("[") and "]" in ip:
                    ip = ip[1:ip.index("]")]
                else:
                    ip = ip.split(":")[0]
                if ip:
                    return ip
            except Exception:
                pass
    except Exception:
        pass
    return request.client.host

@router.get("/js")
async def track_js(
    request: Request,
    tid: Optional[str] = Query(None, description="Tracking ID"),
    page: Optional[str] = Query(None, description="Page identifier")
):
    """JavaScript tracking endpoint with client-side instrumentation and single-fire guard."""
    try:
        client_ip = _get_client_ip(request)
        if not await rate_limiter.is_allowed(client_ip, "js_track"):
            return Response(content="/* Rate limited */", media_type="application/javascript")
        
        referrer = request.headers.get("referer")
        page_url = page or referrer
        
        logger.debug("JavaScript tracker served", tid=tid)
        
        js_content = (
            _JS_TEMPLATE_MINIFIED
            .replace("__TID__", json.dumps(tid or ""))
            .replace("__PAGE_URL__", json.dumps(page_url or ""))
            .replace("__VISIT_ID__", "null")
            .replace("__SECONDARY_ORIGIN__", json.dumps(settings.tracker_mirror_url or ""))
        )
        
        return Response(
            content=js_content,
            media_type="application/javascript",
            headers={
                "Cache-Control": "public, max-age=300",  # Cache for 5 minutes (faster updates)
                "Access-Control-Allow-Origin": "*",
                "X-Content-Version": "2.1"  # Version marker for debugging
            }
        )
        
    except Exception as e:
        logger.error("JavaScript tracking failed", error=str(e))
        return Response(
            content="/* CrawlDoctor tracking error */",
            media_type="application/javascript"
        )


@router.get("/json")
async def track_json(
    tid: Optional[str] = Query(None, description="Tracking ID")
):
    """Lightweight JSON tracking endpoint for legacy/prefetch requests."""
    return Response(
        content="{}",
        media_type="application/json",
        headers={
            "Cache-Control": "public, max-age=300",
            "Access-Control-Allow-Origin": "*"
        }
    )


@router.post("/event")
async def track_event(
    request: Request,
    db: Session = Depends(get_db),
    tid: Optional[str] = Query(None, description="Tracking ID")
):
    """Record granular client-side events (click, scroll, navigation, etc.)."""
    try:
        client_ip = _get_client_ip(request)
        if not await rate_limiter.is_allowed(client_ip, "event_track"):
            return Response(content="Rate limited", status_code=429)

        # Support both JSON and text/plain bodies
        try:
            payload = await request.json()
        except Exception:
            try:
                body = await request.body()
                payload = json.loads(body.decode('utf-8') or '{}')
            except Exception:
                payload = {}
        event_type = payload.get("event_type")
        page_url = payload.get("page_url")
        referrer = payload.get("referrer")
        data = payload.get("data")
        visit_id = payload.get("visit_id")
        client_id = payload.get("cid")
        client_side_data = payload.get("client_side_data")

        if not event_type:
            logger.debug("Dropped event: missing event_type", ip=client_ip)
            return Response(status_code=204)

        user_agent = request.headers.get("user-agent", "")

        if settings.rabbitmq_enabled:
            from app.mq import event_publisher
            mq_payload = {
                "event_type": event_type,
                "page_url": page_url,
                "referrer": referrer,
                "data": data,
                "visit_id": visit_id,
                "tracking_id": tid,
                "client_id": client_id,
                "client_side_data": client_side_data,
                "ip_address": client_ip,
                "user_agent": user_agent,
            }
            try:
                message_id = await event_publisher.publish(mq_payload)
                return {"status": "queued", "message_id": message_id}
            except Exception as e:
                logger.error("MQ publish failed, falling back to direct write", error=str(e))
                # Fall through to direct write below

        result = await tracking_service.track_event(
            db=db,
            ip_address=client_ip,
            user_agent=user_agent,
            event_type=event_type,
            page_url=page_url,
            referrer=referrer,
            data=data,
            visit_id=visit_id,
            tracking_id=tid,
            client_id=client_id,
            client_side_data=client_side_data,
        )

        return {"status": "tracked", "event_id": result.get("event_id"), "queued": result.get("queued")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Event tracking failed", error=str(e))
        return {"status": "error", "message": str(e)}


@router.get("/status")
async def tracking_status():
    """Health check endpoint for tracking service."""
    return {
        "status": "healthy",
        "service": "tracking",
        "timestamp": datetime.now().isoformat()
    }
