# Dev-only: chay Vite dev server (HMR). Chua co stage build production —
# viec do thuoc phase sau khi FE co gi de build. Nguon that o bind-mount
# (docker-compose.override.yml), khong phai COPY o day.
FROM node:22-alpine

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

EXPOSE 5173

CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173"]
