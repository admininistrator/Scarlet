/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// server.host=true de nghe tren 0.0.0.0 trong container (T-0.10);
// nginx proxy vao day qua ten service `web` tren network `internal`.
//
// B-199 — khoi `test` la bo chay test cua tang FE. Truoc no, 12 task cua §7
// (Phase 3) deu gia dinh co mot cho de dat test ma khong cho nao ton tai:
// `make test` chi goi `pytest` cua backend, `make lint` chi goi `ruff`+`mypy`.
//
// `environment: "jsdom"` chu khong "node": phan lon thu dang cho duoc kiem o
// day la component React, va mot moi truong khong co DOM se lam chung do o
// dong `render()` dau tien chu khong o cho co loi.
//
// Cau hinh nam TRONG `vite.config.ts` chu khong mot `vitest.config.ts` rieng:
// hai file se la hai ban `plugins` phai giu khop nhau, va ngay chung lech thi
// test chay bang mot pipeline khac voi pipeline dung de build.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    // T-3.2 — Vite 6 tra 403 "Blocked request" cho moi `Host:` khong nam trong
    // danh sach nay (lop chan DNS-rebinding cua no). Nginx da lach bang
    // `proxy_set_header Host $host` nen duong nguoi dung di khong bao gio cham
    // toi; nhung container `audit` goi THANG `http://web:5173` tren network
    // `internal`, tuc `Host: web`, va no an tron 403.
    //
    // Trieu chung khi thieu dong nay rat de doc nham: lighthouse bao
    // "unable to reliably load the page", con axe cham diem chinh TRANG LOI
    // cua Vite va bao `html-has-lang` / `document-title` — ba loi khong mot
    // cai nao ton tai trong `index.html`.
    allowedHosts: ["web", "localhost"],
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // `src/**` thoi: khong de vitest di lac vao `node_modules` hay `dist`.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    restoreMocks: true,
    // T-3.9: vitest mac dinh thay MOI file CSS bang chuoi rong, ke ca
    // `theme.css?raw`. `HoatAnh.test.tsx` phai doc that khoi
    // `@media (prefers-reduced-motion)` — jsdom khong tinh `@media`, nen day
    // la cach duy nhat de ca am "xoa khoi @media ⇒ test do" co nghia.
    css: { include: [/src\/styles\/theme\.css/] },
  },
});
