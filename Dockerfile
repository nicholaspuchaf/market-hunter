# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.14-slim-bookworm

FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend
RUN npm install --global pnpm@11.23.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/pnpm/store \
    pnpm install --frozen-lockfile --store-dir /pnpm/store
COPY frontend/index.html frontend/vite.config.ts frontend/svelte.config.js frontend/tsconfig.json ./
COPY frontend/src ./src
RUN pnpm check && pnpm build

FROM ${PYTHON_IMAGE} AS backend-build
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MARKET_HUNTER_FRONTEND=/app/frontend \
    MARKET_HUNTER_DB=/data/market-hunter.sqlite3
WORKDIR /app
RUN useradd --uid 1000 --user-group --create-home app \
    && mkdir /data && chown app:app /data
COPY --from=backend-build /opt/venv /opt/venv
COPY backend/app ./app
COPY backend/collector ./collector
COPY --from=frontend-build /build/frontend/dist ./frontend
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/health', timeout=3).close()"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
