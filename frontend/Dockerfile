# T-9.4a — ba stage, `target` GHI TUONG MINH o ca hai noi dung no:
#   dev    Vite dev server (HMR) — docker-compose.override.yml `target: dev`.
#          Nguon that o bind-mount, khong phai COPY.
#   build  `pnpm build` — `VITE_*` qua build args: Vite DONG chung vao bundle
#          luc build (doi TURNSTILE_SITE_KEY / ARTIFACTS_BASE_URL = build lai).
#   prod   nginx tinh phuc vu `dist/` cung cong noi bo 5173 — docker-compose.prod.yml.
# Stage CUOI la mac dinh khi khong `target`: quen `target: dev` o override la
# may dev lang le chay ban prod (Cam bay ② T-9.4a).
FROM node:22-alpine AS dev

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

EXPOSE 5173

CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173"]

FROM dev AS build
ARG VITE_API_BASE_URL
ARG VITE_TURNSTILE_SITE_KEY
ARG VITE_ARTIFACTS_BASE_URL
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 5173
