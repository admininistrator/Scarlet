import { RouterProvider, createBrowserRouter } from "react-router";

import { ErrorBoundary } from "./app/ErrorBoundary";
import { routes } from "./app/routes";

/**
 * Goc cua app — T-3.1a.
 *
 * KH tham chieu: §16.3, §23 · tasks.md T-3.1a, T-1.14, T-2.19, B-187.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  FILE NAY TUNG LA CA BON THU MOT LUC                                   ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Truoc T-3.1a, `App.tsx` vua la router (mot chuoi ternary bon tang chon man
 * hinh), vua la layout shell (header), vua la cho giu phien, vua la noi
 * chuyen huong `/admin`. Bon viec trong mot file la bon ly do de sua no, va
 * nhanh cuoi cua chuoi ternary ay — `else → <ChatScreen/>` — la B-187: moi
 * duong la roi ve man chat, khong co 404.
 *
 * Nay no lam dung mot viec: dung router len va cang mot luoi an toan quanh
 * no. Bang route o `app/routes.tsx`, header o `app/Layout.tsx`, phien o
 * `usePhien` goi tu `Layout`.
 *
 * ── `createBrowserRouter` o tam module ────────────────────────────────────
 *
 * Mot router, dung mot lan, khong dung lai theo tung lan render. Dat no
 * trong than `App()` se sinh mot router MOI moi lan React render lai goc —
 * va moi lan nhu vay la mot lan mat sach lich su dieu huong.
 *
 * ── `ErrorBoundary` boc NGOAI `RouterProvider` ────────────────────────────
 *
 * Khong phai de bat loi cua cac man hinh — nhung loi ay bi `errorElement`
 * cua bang route bat truoc. No o day de bat phan con lai: chinh
 * `RouterProvider`, va bat cu thu gi duoc dat canh no sau nay. Xem
 * `app/pages/ServerErrorPage.tsx` de biet ranh gioi giua hai nguoi bat.
 */
const router = createBrowserRouter(routes);

export default function App() {
  return (
    <ErrorBoundary>
      <RouterProvider router={router} />
    </ErrorBoundary>
  );
}
