# Build context is the REPO ROOT (see docker-compose.yml's `context: ../..`)
# -- curodav.pyproject.toml declares webapp/ as a uv workspace member, and
# uv.lock lives at the root, so both have to be present for `uv sync
# --frozen` to resolve the workspace at all.
FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer first (cache-friendly): only pyproject.toml/uv.lock, no
# app source yet, so editing src/ doesn't bust this layer's cache.
COPY pyproject.toml uv.lock /app/
COPY webapp/pyproject.toml /app/webapp/pyproject.toml
RUN cd webapp && uv sync --frozen --no-dev --no-install-project

COPY webapp/src /app/webapp/src
RUN cd webapp && uv sync --frozen --no-dev

# Default banner/avatar photos (src/main.py's _seed_default_media reads
# these from ../../assets relative to webapp/src, i.e. /app/assets here).
COPY assets /app/assets

WORKDIR /app/webapp
ENV CC_DB_PATH=/data/cache.sqlite
VOLUME ["/data"]
EXPOSE 8000

CMD ["uv", "run", "python", "-m", "src.main"]
