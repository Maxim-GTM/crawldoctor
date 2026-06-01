#!/bin/bash
set -e

echo "🚀 Starting CrawlDoctor single-machine deployment..."

# Function to handle migration errors
handle_migration_error() {
    echo "⚠️  Migration error detected, attempting to fix..."
    
    # Reset alembic_version table
    python3 -c "
import psycopg2
from app.config import settings
import urllib.parse as urlparse

try:
    url = urlparse.urlparse(settings.database_url)
    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    cursor = conn.cursor()
    cursor.execute('DELETE FROM alembic_version;')
    conn.commit()
    print('✅ Cleared migration state')
    cursor.close()
    conn.close()
except Exception as e:
    print(f'Note: {e}')
" || true
}

# Wait for database to be ready
echo "⏳ Waiting for database connection..."
python3 -c "
import time
import psycopg2
from app.config import settings

max_attempts = 30
attempt = 0

while attempt < max_attempts:
    try:
        # Parse database URL
        import urllib.parse as urlparse
        url = urlparse.urlparse(settings.database_url)
        
        conn = psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port
        )
        conn.close()
        print('✅ Database is ready!')
        break
    except psycopg2.OperationalError:
        attempt += 1
        print(f'⏳ Database not ready, waiting... (attempt {attempt}/{max_attempts})')
        time.sleep(2)
else:
    print('❌ Could not connect to database after 30 attempts')
    exit(1)
"

# Run database migrations with Alembic (must complete before app starts)
echo "🔧 Running database migrations..."
set +e
alembic upgrade head 2>&1 | tee /tmp/migration.log
MIGRATION_EXIT=$?
set -e
if [ $MIGRATION_EXIT -eq 0 ]; then
    echo "✅ Database migrations completed"
else
    if grep -q "Can't locate revision" /tmp/migration.log; then
        echo "🔧 Fixing orphaned migration state..."
        handle_migration_error
        alembic stamp 73f8498762a0 || true
        alembic upgrade head || echo "⚠️  Migration skipped, continuing..."
    else
        echo "⚠️  Migration had issues, continuing with app startup..."
    fi
fi

# Initialize database (create tables if needed)
python3 -c "
from app.database import init_db
import asyncio
try:
    asyncio.run(init_db())
    print('✅ Database initialized')
except Exception as e:
    print(f'⚠️  Database initialization warning: {e}')
    # Don't exit - migrations might have already created tables
"

# Create/reset default admin user
echo "👤 Setting up default admin user..."
python3 /app/reset_admin.py

# Configure nginx to listen on $PORT (Railway injects this; default 8000)
LISTEN_PORT=${PORT:-8000}
sed -i "s/listen 8000;/listen ${LISTEN_PORT};/" /etc/nginx/sites-available/default

echo "🐍 Starting FastAPI backend on port 8001..."
# Start FastAPI backend on port 8001 in background with appropriate timeouts
# Using 2 workers for better concurrency on 4-CPU machine
uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 2 --timeout-keep-alive 30 &
BACKEND_PID=$!

# Wait a bit for backend to start
sleep 3

echo "🌐 Starting nginx..."
# Test nginx configuration first
nginx -t
if [ $? -ne 0 ]; then
    echo "❌ Nginx configuration error"
    exit 1
fi

# Start nginx in background
nginx -g 'daemon off;' &
NGINX_PID=$!

# Wait a bit for nginx to start
sleep 2

echo "✅ CrawlDoctor is running!"
echo "📊 Frontend: http://localhost:8000"
echo "🔧 Backend API: http://localhost:8000/api/"
echo "📖 API Docs: http://localhost:8000/docs"
echo "🔍 Health Check: http://localhost:8000/health"

# Function to cleanup processes
cleanup() {
    echo "🛑 Shutting down services..."
    kill $NGINX_PID 2>/dev/null
    kill $BACKEND_PID 2>/dev/null
    exit 0
}

# Set trap for cleanup
trap cleanup SIGTERM SIGINT

# Wait for backend or nginx to exit
wait -n $NGINX_PID $BACKEND_PID
EXIT_CODE=$?

# Cleanup and exit
cleanup
exit $EXIT_CODE
