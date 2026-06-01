# Single-machine Dockerfile for CrawlDoctor (Frontend + Backend)

# Stage 1: Build React frontend
FROM node:20-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    nginx \
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

# Create necessary directories
RUN mkdir -p /app/output /app/logs && \
    chown -R appuser:appgroup /app /var/log/nginx /var/lib/nginx

# Copy startup script and admin reset script
COPY docker-entrypoint-single.sh /app/docker-entrypoint.sh
COPY reset_admin.py /app/reset_admin.py
COPY alembic.ini /app/
COPY alembic/ /app/alembic/
RUN chmod +x /app/docker-entrypoint.sh && chmod +x /app/reset_admin.py

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start application
ENTRYPOINT ["/app/docker-entrypoint.sh"]