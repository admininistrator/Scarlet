# Scarlet — image cua service `audit` (T-3.2, NQ-77).
#
# Vi sao mot image RIENG chu khong them `chromium` vao `web`: `web` chay suot
# ngay va nam o `profile: core`; moi lan doi `package.json` cua no la mot lan
# rebuild keo lai ~400 MB. Image nay o `profile: dev`, chi song trong lan
# `docker compose run --rm audit` cua `make audit`. Cung khuon `mailpit` /
# `adminer` da dung tu T-0.4.
#
# ── Vi sao `chromium` + `chromium-driver` cua Debian, khong phai hai nguon ──
#
# `lighthouse` lai mot Chrome that qua DevTools Protocol; `@axe-core/cli` lai
# mot Chrome that qua WebDriver, tuc no can THEM mot `chromedriver` dung dung
# phien ban voi trinh duyet. Hai goi nay cua Debian di cung mot ban phat hanh
# nen chung luon khop nhau — con tai Chrome tu google.com roi ghep voi
# chromedriver tu mot cho khac la tu tao ra mot lop phien ban phai tu giu
# dong bo o moi lan `docker build`.
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      chromium-driver \
      ca-certificates \
      fonts-liberation \
      fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# `lighthouse` tim trinh duyet qua CHROME_PATH; `chromedriver` tim qua PATH va
# chi biet bon cai ten `google-chrome*` / `chromium*`, nen hai symlink duoi day
# khong phai trang tri.
ENV CHROME_PATH=/usr/bin/chromium
RUN ln -sf /usr/bin/chromium /usr/local/bin/google-chrome \
 && ln -sf /usr/bin/chromium /usr/local/bin/chrome

# Ghim theo SO MAJOR, cung quy uoc voi `node:22-alpine` / `postgres:17-alpine`
# cua docker-compose.yml.
RUN npm install -g lighthouse@12 @axe-core/cli@4 && npm cache clean --force

WORKDIR /scarlet

# T-5.6 (S12) — `scripts/test_artifact_origin.mjs` lai Chromium bang
# `puppeteer-core`. Truoc day goi nay chi co vi `lighthouse@12` keo theo (bac
# cau, nam trong node_modules cua lighthouse — nang lighthouse la mat). Ghim
# DUNG ban dang chay voi Chromium cua image (do 2026-10-07), cai cuc bo o
# /scarlet de `import "puppeteer-core"` tu `scripts/` tim thay.
RUN npm install --no-save --no-package-lock puppeteer-core@24.43.1 && npm cache clean --force

# T-8.4 (NQ-149 ⑦) — DoD "Firefox khong hien nut voice" (ADR-13, §24.3 P8) can
# MOT Firefox that: `scripts/test_voice.mjs` lai no qua `puppeteer-core`
# `browser: "firefox"` (WebDriver BiDi, khong can geckodriver). `firefox-esr`
# cua Debian bookworm (do 2026-10-13: 153.4.0esr, ~+318 MB). Lop RIENG sau
# lop Chromium: doi Firefox khong keo lai Chromium.
RUN apt-get update && apt-get install -y --no-install-recommends firefox-esr \
 && rm -rf /var/lib/apt/lists/*
ENV FIREFOX_PATH=/usr/bin/firefox-esr
