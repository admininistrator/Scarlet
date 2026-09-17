/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  /**
   * Khoa CONG KHAI cua widget Turnstile (T-2.6). docker-compose.yml anh xa no
   * tu `TURNSTILE_SITE_KEY` trong `.env` — khong co dong VITE_ rieng nao trong
   * `.env` de lech. Rong = tat widget, khop voi `TURNSTILE_SECRET` rong o
   * backend.
   */
  readonly VITE_TURNSTILE_SITE_KEY: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
