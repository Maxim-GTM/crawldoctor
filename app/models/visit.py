"""Visit tracking models for CrawlDoctor."""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, Text, Float,
    JSON, BigInteger, ForeignKey, func
)
from sqlalchemy.orm import relationship
from app.database import Base


class VisitSession(Base):
    """Session tracking for visitor analytics."""
    
    __tablename__ = "visit_sessions"
    
    id = Column(String(64), primary_key=True, index=True)
    ip_address = Column(String(45), nullable=False, index=True)
    user_agent = Column(String(1000))
    
    # Unified user identity (persistent across sessions)
    client_id = Column(String(64), index=True)
    
    # Session tracking
    first_visit = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    last_visit = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    visit_count = Column(Integer, default=0)

    # Journey entry context
    entry_referrer = Column(String(2000))
    entry_referrer_domain = Column(String(200), index=True)
    is_external_entry = Column(Boolean, default=True)
    
    # Geographic information
    country = Column(String(2), index=True)
    country_name = Column(String(100))
    city = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)
    timezone = Column(String(50))
    
    # Network information
    isp = Column(String(200))
    organization = Column(String(200))
    asn = Column(String(50))
    
    # Client-side captured data
    client_side_timezone = Column(String(50))
    client_side_language = Column(String(50))
    client_side_screen_resolution = Column(String(50))
    client_side_viewport_size = Column(String(50))
    client_side_device_memory = Column(String(20))
    client_side_connection_type = Column(String(50))
    
    def __repr__(self):
        return f"<VisitSession(id='{self.id}', crawler='{self.crawler_type}')>"


class Visit(Base):
    """Individual visit records from AI crawlers."""
    
    __tablename__ = "visits"
    
    id = Column(BigInteger, primary_key=True, index=True)
    session_id = Column(String(64), ForeignKey("visit_sessions.id"), index=True)
    
    # Unified user identity (persistent across sessions)
    client_id = Column(String(64), index=True)
    
    # Request information
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    ip_address = Column(String(45), nullable=False, index=True)
    user_agent = Column(String(1000), nullable=False)
    
    # Page information
    page_url = Column(String(2000), index=True)
    referrer = Column(String(2000))
    page_title = Column(String(500))
    page_domain = Column(String(200), index=True)
    
    # Crawler identification
    crawler_type = Column(String(100), index=True)
    crawler_confidence = Column(Float, default=1.0)
    is_bot = Column(Boolean, default=False, index=True)
    
    # Request details
    request_method = Column(String(10), default="GET")
    request_headers = Column(JSON)
    response_status = Column(Integer)
    response_size = Column(Integer)
    response_time_ms = Column(Float)
    
    # Geographic information (cached from session)
    country = Column(String(2), index=True)
    city = Column(String(100))
    
    # Tracking metadata
    tracking_id = Column(String(100), index=True)  # Custom tracking identifier
    campaign = Column(String(100))  # Campaign tracking
    source = Column(String(100))  # Traffic source
    medium = Column(String(100))  # Traffic medium
    
    # Content analysis
    content_type = Column(String(100))
    content_language = Column(String(10))
    content_encoding = Column(String(50))
    
    # Technical details
    protocol = Column(String(10))  # HTTP/HTTPS
    port = Column(Integer)
    path = Column(String(1000))
    query_params = Column(JSON)
    
    # Client-side captured data
    client_side_timezone = Column(String(50))
    client_side_language = Column(String(50))
    client_side_screen_resolution = Column(String(50))
    client_side_viewport_size = Column(String(50))
    client_side_device_memory = Column(String(20))
    client_side_connection_type = Column(String(50))
    
    # Relationships
    session = relationship("VisitSession", backref="visits")
    
    def __repr__(self):
        return f"<Visit(id={self.id}, crawler='{self.crawler_type}', domain='{self.page_domain}')>"


class VisitEvent(Base):
    """Fine-grained events within a visit/session (clicks, scrolls, navigation)."""
    __tablename__ = "visit_events"

    id = Column(BigInteger, primary_key=True, index=True)
    session_id = Column(String(64), ForeignKey("visit_sessions.id"), index=True)
    visit_id = Column(BigInteger, ForeignKey("visits.id"), index=True, nullable=True)
    
    # Unified user identity (persistent across sessions)
    client_id = Column(String(64), index=True)

    # Timing
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    event_type = Column(String(50), index=True)  # click, scroll, nav, visibility, custom

    # Page context
    page_url = Column(String(2000), index=True)
    referrer = Column(String(2000))
    path = Column(String(1000))
    page_domain = Column(String(200), index=True)
    referrer_domain = Column(String(200), index=True)

    # Attribution
    tracking_id = Column(String(100), index=True)
    source = Column(String(100), index=True)
    medium = Column(String(100), index=True)
    campaign = Column(String(100), index=True)

    # MQ idempotency key — set by publisher, prevents duplicate processing on redelivery
    message_id = Column(String(36), unique=True, nullable=True, index=True)

    # Event payload — unversioned JSON. Known shapes:
    #   form_submit: {"form_values": {field: value, ...}, "filled_fields": int, "id": str, "action": str}
    #   Also seen:   {"values": {field: value, ...}} (legacy alias for form_values)
    #   Consumers must handle both "form_values" and "values" keys.
    event_data = Column(JSON)
    
    # Client-side captured data
    client_side_timezone = Column(String(50))
    client_side_language = Column(String(50))
    client_side_screen_resolution = Column(String(50))
    client_side_viewport_size = Column(String(50))
    client_side_device_memory = Column(String(20))
    client_side_connection_type = Column(String(50))

    # Relationships
    session = relationship("VisitSession", backref="events")
    visit = relationship("Visit", backref="events")
