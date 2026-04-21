# syntax=docker/dockerfile:1.7
# Fly.io deploy image for the Superbrain API (FastAPI + DuckDB).
#
# Build context is the repo root:
#   docker build -f deploy/api/Dockerfile -t superbrain-api .
# or, for Fly, the repo-root `fly deploy` with `dockerfile = "deploy/api/Dockerfile"`.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    SUPERBRAIN_LAKE_PATH=/data/lake

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
    ca-certificates curl libstdc++6 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.29 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-install-project \
 && uv sync --frozen --no-dev

RUN groupadd --system superbrain \
 && useradd --system --home /app --shell /usr/sbin/nologin --gid superbrain superbrain \
 && mkdir -p /data/lake \
 && chown -R superbrain:superbrain /app /opt/venv /data

USER superbrain

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["uvicorn", "superbrain.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
