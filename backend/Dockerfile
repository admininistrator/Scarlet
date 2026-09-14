FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

# B-70: cai DUNG dependency, KHONG cai chinh goi `app`.
#
# Truoc day buoc nay la `pip install .` (sau khi `COPY app ./app`), nen image co
# HAI ban `app/`: mot o site-packages, mot o /app/app do `COPY` ben duoi. Hai ban
# KHONG tuong duong: `catalog.py`/`context.py` dinh vi `config/` bang
# `Path(__file__).parents[3]` — tu /app/app/... ra /config (dung), tu
# site-packages ra /usr/local/lib/python3.12/config (sai). Va ban SAI dung TRUOC
# trong duong tim cua tien trinh `worker`: console script dat
# sys.path[0]=/usr/local/bin, con arq/cli.py them cwd bang `sys.path.append`
# (append, khong phai insert(0)), nen site-packages thang. Do duoc trong
# container: FileNotFoundError /usr/local/lib/python3.12/config/model_catalog.json
#
# Danh sach dependency doc tu chinh `pyproject.toml` de khong sinh nguon su that
# thu hai: them mot package la sua MOT cho, khong phai hai.
# `chr(10)` chu khong phai "\n": trong Dockerfile, dau `\` la ky tu noi dong.
RUN python -c "import tomllib, pathlib; deps = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']; pathlib.Path('requirements.txt').write_text(chr(10).join(deps) + chr(10))" \
    && cat requirements.txt \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

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

# Nua con lai cua B-70. Bo `pip install .` lam `app` chi con MOT ban, nhung ban
# do chi tim thay duoc khi cwd la /app — tien trinh nao doi thu muc lam viec se
# `ModuleNotFoundError`. PYTHONPATH dung TRUOC site-packages va khong phu thuoc
# cwd, nen tu day `import app` luon ra dung mot file, tu bat cu dau.
ENV PYTHONPATH=/app

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
