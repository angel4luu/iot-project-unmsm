FROM python:3.14.8-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/services/ingestion
COPY --from=ghcr.io/astral-sh/uv:0.9.13 /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY migrations ./migrations
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home app \
    && mkdir -p /data \
    && chown app:app /data

ENV PATH="/app/services/ingestion/.venv/bin:$PATH"
USER app:app
CMD ["python", "-m", "energy_ingestion.service"]
