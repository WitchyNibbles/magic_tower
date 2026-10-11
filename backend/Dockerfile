FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser
EXPOSE 8000
# The application writes no DDL of its own, so the schema is brought to head before
# the first request. The baseline revision tolerates a workboard-data volume that
# predates Alembic, so an untouched existing volume needs no manual stamp; one whose
# baseline columns were altered by hand fails here instead of serving mis-stamped.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
