"""Summary models for pre-computed journey and lead data."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, JSON, Text, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base


class JourneyFormFill(Base):
    """One row per real form submission; preserves multiple form fills per user."""
    __tablename__ = "journey_form_fills"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    client_id = Column(String(64), nullable=False, index=True)
    visit_event_id = Column(BigInteger, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    page_url = Column(String(2000), nullable=True)
    path = Column(String(1000), nullable=True)
    form_values = Column(JSONB, nullable=True)
    filled_fields = Column(Integer, nullable=True)
    form_id = Column(String(255), nullable=True)
    form_action = Column(String(2000), nullable=True)
    form_type = Column(String(50), nullable=True, index=True)  # app/services/lead_classification.py

class LeadSummary(Base):
    """Pre-computed lead data for fast retrieval."""
    __tablename__ = "lead_summaries"
    
    client_id = Column(String(64), primary_key=True, index=True)
    email = Column(String(255), index=True)
    name = Column(String(255), index=True)
    
    # Capture Info
    captured_at = Column(DateTime(timezone=True), index=True)
    captured_page = Column(Text)
    captured_path = Column(Text)
    
    # Combined Data
    form_data_shared = Column(Text) # Combined string of all shared info
    captured_data = Column(Text)    # Pipe-separated key=val pairs
    
    # Attribution (from first touch)
    source = Column(String(100), index=True)
    medium = Column(String(100), index=True)
    campaign = Column(String(100), index=True)
    first_referrer = Column(String(2000))
    first_referrer_domain = Column(String(200), index=True)

    # Classification: the most valuable type among the form fills, and all of them, comma-separated
    lead_type = Column(String(50), index=True)
    form_types = Column(String(500))

    # Timestamps
    first_seen = Column(DateTime(timezone=True), index=True)
    last_seen = Column(DateTime(timezone=True), index=True)

    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

class JourneySummary(Base):
    """Pre-computed journey data for fast retrieval."""
    __tablename__ = "journey_summaries"
    
    client_id = Column(String(64), primary_key=True, index=True)
    
    # Timing
    first_seen = Column(DateTime(timezone=True), index=True)
    last_seen = Column(DateTime(timezone=True), index=True)
    visit_count = Column(Integer, default=0)
    
    # Journey Path
    entry_page = Column(String(2000))
    exit_page = Column(String(2000))
    path_sequence = Column(Text) # Arrow separated paths
    
    # Lead Info (first form fill, for list display)
    email = Column(String(255), index=True)
    name = Column(String(255), index=True)
    has_captured_data = Column(Integer, default=0)  # 1 if has lead data
    form_fill_count = Column(Integer, default=0)  # number of real form submissions
    
    # Attribution
    source = Column(String(100), index=True)
    medium = Column(String(100), index=True)
    campaign = Column(String(100), index=True)
    
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
