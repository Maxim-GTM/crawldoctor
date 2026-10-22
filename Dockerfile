# syntax=docker/dockerfile:1
# Single-machine Dockerfile for CrawlDoctor (Frontend + Backend).
# On AWS it is built by GitHub Actions and runs on gtm-apps-1 behind Caddy (see deploy/).

# Stage 1: Build React frontend
FROM node:20.20.2-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11.16-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt

# PGSSLROOTCERT: the Neon URL uses sslmode=verify-full, and libpq otherwise looks for
# ~/.postgresql/root.crt. Neon's certificate chains to a public CA in the Debian bundle.

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    nginx \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --gid 1001 appuser

# Set work directory
WORKDIR /app

# Copy requirements first (for better layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY app/ ./app/

# Copy test pages (cross-domain session test served by the app)
COPY tests/ ./tests/

# Copy migration downgrade script
COPY downgrade_migration.py ./

# Copy built frontend from stage 1
COPY --from=frontend-builder /frontend/build/ ./frontend/

# Copy nginx configuration
COPY nginx.conf /etc/nginx/sites-available/default

# Create necessary directories. nginx runs as appuser too: its pid file moves to /tmp, and the
# entrypoint rewrites the site's listen port, so appuser owns that file.
RUN mkdir -p /app/output /app/logs && \
    sed -i 's|^pid .*|pid /tmp/nginx.pid;|; s|^user .*||' /etc/nginx/nginx.conf && \
    chown -R appuser:appgroup /app /var/log/nginx /var/lib/nginx /etc/nginx/sites-available/default

# Copy startup script and admin reset script
COPY docker-entrypoint-single.sh /app/docker-entrypoint.sh
COPY reset_admin.py /app/reset_admin.py
COPY alembic.ini /app/
COPY alembic/ /app/alembic/
RUN chmod +x /app/docker-entrypoint.sh && chmod +x /app/reset_admin.py

USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start application
ENTRYPOINT ["/app/docker-entrypoint.sh"]