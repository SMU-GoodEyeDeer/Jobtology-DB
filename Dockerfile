FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.18
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY config ./config
RUN uv sync --frozen --no-dev \
    && groupadd --gid 10001 jobtology \
    && useradd --uid 10001 --gid 10001 --no-create-home jobtology \
    && mkdir /data \
    && chown jobtology:jobtology /data
ENV PATH="/app/.venv/bin:$PATH" \
    JOBTOLOGY_RAW_ROOT=/data \
    JOBTOLOGY_SOURCE_RIGHTS_FILE=/app/config/source_rights.yaml \
    JOBTOLOGY_PIPELINE_SCHEDULE=/app/config/pipeline.yaml \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER jobtology
# No HTTP listener or published port. Use the same image for cron's one-shot update command.
CMD ["jobtology", "pipeline", "worker"]
