"""Main FastAPI application for CrawlDoctor."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send
import structlog
from pathlib import Path
import time

from app.config import settings
from app.database import get_db, init_db, close_db
from sqlalchemy.orm import Session
from app.api import tracking_router, analytics_router, auth_router, admin_router
from app.services.auth import AuthService
from app.services.event_batcher import event_batcher
from app.background import job_runner, job_scheduler


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    # Startup
    logger.info("Starting CrawlDoctor application")
    
    try:
        # Initialize database
        await init_db()
        logger.info("Database initialized")

        # Start MQ pipeline (replaces event batcher) or fall back to in-process batcher
        if settings.rabbitmq_enabled:
            from app.mq import mq_connection
            from app.mq.consumers import core_consumer, enrichment_consumer
            from app.mq.topology import declare_topology
            event_batcher.enabled = False  # consumers write directly; batcher must not swallow events
            await mq_connection.connect()
            channel = await mq_connection.get_consumer_channel()
            await declare_topology(channel)
            await channel.close()
            await core_consumer.start(mq_connection)
            await enrichment_consumer.start(mq_connection)
            logger.info("RabbitMQ pipeline started")
        else:
            await event_batcher.start()

        # Start background job runner and scheduler
        await job_runner.start()
        await job_runner.recover_pending_jobs()
        await job_scheduler.start()
        
        # Create default admin user
        from app.database import SessionLocal
        auth_service = AuthService()
        db = SessionLocal()
        try:
            auth_service.create_default_admin_sync(db)
            logger.info("Default admin user setup completed")
        except Exception as e:
            logger.error("Failed to create default admin user", error=str(e))
        finally:
            db.close()
        
        logger.info("CrawlDoctor startup completed successfully")
        
    except Exception as e:
        logger.error("Failed to start application", error=str(e))
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down CrawlDoctor application")
    
    try:
        await job_scheduler.stop()
    except Exception as e:
        logger.error("Error stopping job scheduler", error=str(e))

    try:
        await job_runner.stop()
    except Exception as e:
        logger.error("Error stopping job runner", error=str(e))

    if settings.rabbitmq_enabled:
        try:
            from app.mq import mq_connection
            from app.mq.consumers import core_consumer, enrichment_consumer
            await core_consumer.stop()
            await enrichment_consumer.stop()
            await mq_connection.close()
        except Exception as e:
            logger.error("Error stopping RabbitMQ pipeline", error=str(e))
    else:
        try:
            await event_batcher.stop()
        except Exception as e:
            logger.error("Error stopping event batcher", error=str(e))

    try:
        await close_db()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error("Error during shutdown", error=str(e))
    
    logger.info("CrawlDoctor shutdown completed")


# Create FastAPI application
app = FastAPI(
    title="CrawlDoctor",
    description="AI Crawler Tracking and Analytics System",
    version=settings.app_version,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan
)


class _SecurityHeadersMiddleware:
    """Pure ASGI security headers middleware."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["X-XSS-Protection"] = "1; mode=block"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                if not settings.debug:
                    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        await self.app(scope, receive, send_wrapper)


class _LogRequestsMiddleware:
    """Pure ASGI request logging middleware."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        request = Request(scope, receive)

        logger.info(
            "Request received",
            method=request.method,
            url=str(request.url),
            client_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", ""),
            path=request.url.path,
        )

        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Process-Time"] = f"{time.time() - start_time:.3f}s"
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            logger.info(
                "Request completed",
                method=request.method,
                url=str(request.url),
                status_code=status_code,
                process_time=f"{time.time() - start_time:.3f}s",
            )
        except Exception as e:
            logger.error(
                "Request failed",
                method=request.method,
                url=str(request.url),
                error=str(e),
                process_time=f"{time.time() - start_time:.3f}s",
            )
            raise


app.add_middleware(_SecurityHeadersMiddleware)
app.add_middleware(_LogRequestsMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time", "X-Rate-Limit-Remaining", "X-Rate-Limit-Reset"]
)


# Trusted host middleware (production security)
if not settings.debug:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"]  # Configure with actual domains in production
    )


# Exception handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 handler."""
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": "The requested resource was not found",
            "path": request.url.path,
            "timestamp": datetime.now().isoformat()
        }
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Custom 500 handler."""
    logger.error(
        "Internal server error",
        path=request.url.path,
        method=request.method,
        error=str(exc)
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred",
            "timestamp": datetime.now().isoformat()
        }
    )


# Include routers
app.include_router(tracking_router)
app.include_router(analytics_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)


# Test pages for iframe tracking (same-origin so tracker works inside iframe)
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@app.get("/test/iframe", response_class=HTMLResponse)
async def test_iframe_parent():
    """Parent page with iframe; iframe src is /test/iframe/form."""
    path = _TEMPLATES_DIR / "test_iframe_parent.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return HTMLResponse(content="<p>Test template not found.</p>", status_code=404)


@app.get("/test/iframe/form", response_class=HTMLResponse)
async def test_iframe_form():
    """Form page loaded inside iframe; includes CrawlDoctor script so events are tracked from iframe URL."""
    path = _TEMPLATES_DIR / "test_iframe_form.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return HTMLResponse(content="<p>Test template not found.</p>", status_code=404)


@app.get("/test/cross-domain", response_class=HTMLResponse)
async def test_cross_domain():
    """Test page for verifying cross-domain session continuity between Maxim and Bifrost."""
    path = Path(__file__).resolve().parent.parent / "tests" / "test_cross_domain.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return HTMLResponse(content="<p>Test page not found.</p>", status_code=404)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with basic information."""
    return {
        "name": "CrawlDoctor",
        "description": "AI Crawler Tracking and Analytics System",
        "version": settings.app_version,
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "tracking": "/track",
            "analytics": f"{settings.api_prefix}/analytics",
            "authentication": f"{settings.api_prefix}/auth",
            "administration": f"{settings.api_prefix}/admin"
        },
        "tracking_methods": ["javascript"],
        "documentation": "/docs" if settings.debug else None
    }


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": settings.app_version,
        "environment": settings.environment,
        "debug": settings.debug
    }


# Metrics endpoint for monitoring
@app.get("/metrics")
async def metrics(db: Session = Depends(get_db)):
    """Basic metrics endpoint."""
    try:
        from app.models.visit import Visit
        from sqlalchemy import func

        now = datetime.now(timezone.utc)
        total_visits = db.query(func.count(Visit.id)).scalar()
        recent_visits = db.query(func.count(Visit.id)).filter(
            Visit.timestamp >= now - timedelta(hours=1)
        ).scalar()

        return {
            "total_visits": total_visits,
            "recent_visits_1h": recent_visits,
            "timestamp": now.isoformat(),
        }
    except Exception as e:
        logger.error("Failed to get metrics", error=str(e))
        return {
            "error": "Metrics unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level="info" if not settings.debug else "debug"
    )
