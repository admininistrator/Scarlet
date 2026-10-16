# Scarlet — MinIO server + `mc` build tu source (T-9.4a, Q-P9-1).
#
# `minio/minio` va `minio/mc` tren Docker Hub het pull duoc — do 2026-10-15:
# `docker manifest inspect` ca tag lan digest `14cea493…` ⇒ `denied`. May nao
# chua co image trong cache thi khong dung noi stack. Ghim RELEASE, khong
# `latest`: ban server la ban da chay tren EC2 (RUNBOOK-AWS §10), `mc` la ban
# nam trong image cu cua may dev. `backup` (T-9.3) ghim CUNG release `mc`.
#
# Doi ban = sua hai dong ARG, build lai `minio`; data volume giu nguyen.
FROM golang:1.24.8-bookworm AS build
ARG MINIO_RELEASE=RELEASE.2025-10-15T17-29-55Z
ARG MC_RELEASE=RELEASE.2025-08-13T08-35-41Z
ENV CGO_ENABLED=0 GOBIN=/out
RUN go install github.com/minio/minio@${MINIO_RELEASE} \
 && go install github.com/minio/mc@${MC_RELEASE}

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/minio /out/mc /usr/local/bin/
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
