# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    APP_MODE=demo \
    DATABASE_PATH=/var/lib/copilot/copilot.sqlite3 \
    FRONTEND_DIST=/app/frontend/dist \
    PORT=8000
WORKDIR /app
COPY constraints.txt /app/constraints.txt
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -c /app/constraints.txt -r /app/backend/requirements.txt \
    && groupadd --gid 10001 copilot \
    && useradd --uid 10001 --gid copilot --home-dir /app --no-create-home copilot \
    && mkdir -p /var/lib/copilot \
    && chown copilot:copilot /var/lib/copilot
COPY backend/app /app/backend/app
COPY backend/fixtures /app/backend/fixtures
COPY --from=frontend /build/frontend/dist /app/frontend/dist
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/ready',timeout=3)" || exit 1
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
