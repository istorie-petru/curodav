# Command Center Web (curodav) -- single-image runtime for both the app and
# the optional Radicale companion container.
#
# Build context is the repo root (the compose file sets context: ../..).
# The same image runs the app by default and Radicale when the compose
# service overrides `command`. radicale is only a dev-group dependency of
# the app, so it is installed separately after the pinned `uv sync`.

FROM python:3.12-slim

# uv -- the app's dependency manager (resolution pinned by uv.lock).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependency manifests first so source changes don't re-resolve/reinstall.
COPY pyproject.toml uv.lock ./
COPY webapp/pyproject.toml webapp/pyproject.toml

# The venv lands in /app/.venv. Sync from the webapp member (the same
# invocation run.sh uses) so its runtime deps are installed; --no-dev keeps
# pytest & friends out of the image. --no-install-project: the app is not a
# pip package, it is run via PYTHONPATH=src below.
RUN cd webapp && uv sync --frozen --no-dev --no-install-project

# Radicale for the optional sync container. Pinned to the same floor as the
# dev group in webapp/pyproject.toml.
RUN uv pip install --python /app/.venv/bin/python "radicale>=3.3"

# Now the source (bounded by the repo-root .dockerignore).
COPY webapp/ webapp/

# Run as an unprivileged user. Its home is the data volume mount point, so
# the app's default CC_DB_PATH (~/.command_center_web/cache.sqlite) already
# lands inside the volume with no configuration. The Radicale collections
# dir is pre-created with matching ownership so a named volume initialized
# from it starts writable by the same uid.
RUN useradd --create-home --home-dir /var/lib/curodav --uid 1000 curodav \
 && mkdir -p /var/lib/curodav/.command_center_web \
           /var/lib/radicale/collections \
 && chown -R curodav:curodav /var/lib/curodav /var/lib/radicale

WORKDIR /app/webapp
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/webapp/src

EXPOSE 8000 5232

USER curodav

# Default command: the app. The Radicale service overrides this via compose.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]