# syntax=docker/dockerfile:1.7

# ---- builder -------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      curl \
      git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

# ---- runtime -------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    SUPERBRAIN_LAKE_PATH="/data/lake"

# curl_cffi ships a vendored libcurl-impersonate; only libc runtime + TLS
# CA bundle are required at runtime. libffi / libssl land via python-slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      tini \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1000 superbrain \
    && useradd --system --uid 1000 --gid superbrain --create-home superbrain \
    && mkdir -p /data/lake \
    && chown -R superbrain:superbrain /data

WORKDIR /app

COPY --from=builder --chown=superbrain:superbrain /app /app

USER superbrain

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "superbrain.scheduler"]
