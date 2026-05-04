"""Configuration settings for the CrawlDoctor application."""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application configuration settings."""
    
    # Application
    app_name: str = Field(default="CrawlDoctor", description="Application name")
    app_version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="production", description="Environment")
    
    # API Configuration
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    api_prefix: str = Field(default="/api/v1", description="API prefix")
    
    # Database
    database_url: str = Field(
        default="postgresql://user:password@localhost:5432/crawldoctor",
        description="Database URL"
    )
    database_pool_size: int = Field(default=30, description="Database pool size")
    database_max_overflow: int = Field(default=20, description="Database max overflow")
    database_statement_timeout: int = Field(default=30000, description="Statement timeout in milliseconds (30 seconds)")
    database_pool_timeout: int = Field(default=60, description="Connection pool timeout in seconds")
    
    # Redis (optional - can use memory:// for in-memory caching)
    redis_url: str = Field(
        default="memory://localhost",
        description="Redis URL or memory:// for in-memory cache"
    )
    redis_ttl: int = Field(default=3600, description="Redis TTL in seconds")
    
    # Security
    secret_key: str = Field(
        default="your-secret-key-change-this-in-production",
        description="Secret key for JWT tokens"
    )
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(
        default=30,
        description="Access token expiration in minutes"
    )
    admin_username: str = Field(default="admin", description="Admin username")
    admin_password: str = Field(default="admin123", description="Admin password")
    admin_email: str = Field(default="admin@crawldoctor.com", description="Admin email")
    
    # Rate Limiting
    rate_limit_requests: int = Field(default=1000, description="Rate limit requests per minute")
    rate_limit_window: int = Field(default=60, description="Rate limit window in seconds")
    
    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "https://yourdomain.com"],
        description="CORS allowed origins"
    )
    
    # GeoIP
    geoip_database_path: Optional[str] = Field(
        default=None,
        description="Path to GeoIP2 database file"
    )
    
    # Tracking Configuration
    pixel_cache_ttl: int = Field(default=86400, description="Pixel cache TTL in seconds")
    max_referrer_length: int = Field(default=2000, description="Max referrer URL length")
    max_user_agent_length: int = Field(default=500, description="Max user agent length")
    max_page_url_length: int = Field(default=2000, description="Max page URL length")

    # Event batching (high volume)
    event_batch_enabled: bool = Field(default=True, description="Enable event batch inserts")
    event_batch_size: int = Field(default=200, description="Batch size for event inserts")
    event_batch_max_delay_ms: int = Field(default=250, description="Max delay before flushing batch")
    event_batch_max_queue: int = Field(default=5000, description="Max pending events in memory queue")

    # Postgres partitioning
    event_partition_days_ahead: int = Field(default=2, description="Create event partitions ahead of time")
    event_partition_days_back: int = Field(default=1, description="Create event partitions for recent past days")
    
    # Analytics
    analytics_batch_size: int = Field(default=1000, description="Analytics batch processing size")
    analytics_export_batch_size: int = Field(default=2000, description="Export batch size for CSV generation")
    analytics_retention_days: int = Field(default=365, description="Data retention in days")
    analytics_export_timeout: int = Field(default=600, description="Export timeout in seconds")
    summary_backfill_interval_minutes: int = Field(default=5, description="Background sweep interval (minutes)")
    summary_backfill_days: int = Field(default=30, description="Watermark fallback lookback window (days)")
    
    # Monitoring
    enable_metrics: bool = Field(default=True, description="Enable Prometheus metrics")
    metrics_port: int = Field(default=8001, description="Metrics server port")

    # API Keys for external service access
    export_api_keys: list[str] = Field(
        default=[],
        description="List of API keys for external service access to exports"
    )
    export_api_enabled: bool = Field(default=True, description="Enable external API access to exports")

    # IP Enrichment (ipapi.co — no API key required)
    ip_enrichment_enabled: bool = Field(default=True, description="Enable IP enrichment")
    ip_enrichment_batch_size: int = Field(default=25, description="IPs per enrichment run (keep low on free plan)")
    ip_enrichment_ttl_days: int = Field(default=30, description="Days before re-enriching an IP")
    ip_enrichment_max_rps: float = Field(default=1.0, description="Max API requests per second")
    ip_enrichment_max_attempts: int = Field(default=3, description="Max enrichment attempts before marking failed")
    ip_enrichment_interval_minutes: int = Field(default=60, description="Incremental enrichment job interval (minutes)")
    
    class Config:
        env_file = ".env"
        env_prefix = "CRAWLDOCTOR_"


# Global settings instance
settings = Settings()
