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

# Tiktoken (§9.6, T-1.4) TAI bang BPE ~3.6 MB tu openaipublic.blob.core.windows.net
# o lan dem token dau tien. Nap san vao image thay vi de container tai luc dang
# phuc vu: mot luot chat khong duoc phep treo — hay chet — vi blob store cua ben
# thu ba. Phai dat TIKTOKEN_CACHE_DIR, neu khong tiktoken ghi vao thu muc tam va
# cache bien mat theo tung container.
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" \
    && python -c "from app.llm.tokens import warm_cache; print('tiktoken:', warm_cache())" \
    && chmod -R a+rX "$TIKTOKEN_CACHE_DIR"

USER scarlet

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
