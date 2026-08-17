FROM python:3.13-slim

WORKDIR /app

RUN useradd --system --uid 1000 --create-home appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY alembic ./alembic
COPY docker/entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && chmod 755 /entrypoint.sh \
    && chown -R appuser:appuser /app

ENV PYTHONPATH=/app
USER appuser
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
