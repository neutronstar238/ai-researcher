#!/bin/sh
set -e

echo "[entrypoint] running migrations..."
python -m alembic upgrade head

if [ "$SEED_DEMO" = "1" ]; then
  echo "[entrypoint] seeding demo data..."
  python -m app.seed --profile demo || true
fi

echo "[entrypoint] starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
