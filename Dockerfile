FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (Astral's Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy workspace root pyproject + lockfile first (layer cache for deps)
COPY pyproject.toml uv.lock ./

# Copy webapp source
COPY webapp/ webapp/
COPY pictures/ pictures/

# Install production dependencies only
RUN cd webapp && uv sync --no-dev --frozen

ENV PYTHONPATH=/app/webapp/src

EXPOSE 8000

WORKDIR /app/webapp

CMD ["uv", "run", "--no-sync", "python", "-m", "src.main"]
