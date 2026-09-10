FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 scarlet

COPY --from=builder /install /usr/local
COPY --chown=scarlet:scarlet app /app/app
COPY --chown=scarlet:scarlet alembic /app/alembic
COPY --chown=scarlet:scarlet alembic.ini /app/alembic.ini

WORKDIR /app
USER scarlet

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
