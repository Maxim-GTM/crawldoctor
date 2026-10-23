#!/bin/bash
set -e

echo "🚀 Starting CrawlDoctor single-machine deployment..."

# Wait for database to be ready (connects with the full CRAWLDOCTOR_DATABASE_URL, sslmode included)
echo "⏳ Waiting for database connection..."
python3 -m app.db_bootstrap wait

# Database migrations (must complete before the app starts).
#
# What happens on each outcome:
#   - DB at a revision this image knows: `alembic upgrade head`. If that fails, exit 1. Postgres
#     runs each migration in a transaction, so the schema is left as it was, and deploy-app on the
#     host rolls back to the previous image when this container never becomes healthy.
#   - DB at a revision NOT in alembic/versions (e.g. stamped from a migration that was never
#     committed): log an ERROR and start WITHOUT migrating. Exiting would only crash-loop the
#     production tracker; the fix is a manual `alembic stamp` (see "Database migrations" in
#     README.md). Nothing here ever deletes or rewrites alembic_version.
#   - The revision check itself fails (DB or alembic error): exit 1, same as a failed upgrade.
echo "🔧 Checking database migration state..."
set +e
python3 -m app.db_bootstrap check-revision
REVISION_CHECK=$?
set -e
case $REVISION_CHECK in
    0)
        echo "🔧 Running database migrations..."
        if alembic upgrade head; then
            echo "✅ Database migrations completed"
        else
            echo "❌ ERROR: alembic upgrade head failed; not starting the app" >&2
            exit 1
        fi
        ;;
    3)
        echo "❌ ERROR: the database is at an alembic revision this image does not know." >&2
        echo "❌ ERROR: SKIPPING ALL MIGRATIONS and starting anyway. Resolve it by hand with alembic stamp." >&2
        ;;
    *)
        echo "❌ ERROR: could not read the database's alembic revision; not starting the app" >&2
        exit 1
        ;;
esac

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

# Ensure admin user exists (create-only unless CRAWLDOCTOR_ADMIN_PASSWORD_RESET_ON_BOOT=true)
echo "👤 Ensuring admin user exists..."
python3 /app/reset_admin.py

# Configure nginx to listen on $PORT (default 8000)
# Rewritten in place (no sed -i): appuser may write this file but not create files beside it.
LISTEN_PORT=${PORT:-8000}
if [ "$LISTEN_PORT" != "8000" ]; then
    site=$(sed "s/listen 8000;/listen ${LISTEN_PORT};/" /etc/nginx/sites-available/default)
    printf '%s\n' "$site" > /etc/nginx/sites-available/default
fi

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
