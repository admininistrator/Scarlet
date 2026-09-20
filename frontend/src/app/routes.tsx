import type { RouteObject } from "react-router";

import { AdminScreen } from "../components/admin/AdminScreen";
import { ChatScreen } from "../components/chat/ChatScreen";
import { t } from "../lib/i18n";
import { AdminOnly } from "./AdminOnly";
import { Layout } from "./Layout";
import { LoginRoute } from "./LoginRoute";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { RouteErrorPage } from "./pages/ServerErrorPage";
import { PATHS } from "./paths";

/**
 * Bang route — 11 duong cua T-3.1a.
 *
 * KH tham chieu: §16.3, §23 · tasks.md T-3.1a, B-187 · NQ ban router.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOT BANG, HAI NGUOI DOC                                               ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * File nay chi XUAT mang `routes`, khong tu tao router. `App.tsx` boc no
 * bang `createBrowserRouter`, `routes.test.tsx` boc no bang
 * `createMemoryRouter`. Neu o day co mot `createBrowserRouter` o tam module
 * thi no se chay ca trong jsdom — va bo test se do tren mot bang route KHAC
 * bang route cua san pham, tuc mot bo test xanh khong chung minh dieu gi.
 *
 * ── Route goc KHONG co `path` ──────────────────────────────────────────────
 *
 * `{ element: <Layout/>, children: [...] }` la mot "pathless layout route":
 * no khong tham gia khop duong, chi cho ca cum mot cai vo chung. Nho vay moi
 * route con viet duoc duong TUYET DOI lay thang tu `PATHS`, thay vi mot
 * chuoi tuong doi (`"admin"`) phai ghep voi cha trong dau nguoi doc.
 *
 * ── Hai duong cuoi trong 11 ────────────────────────────────────────────────
 *
 * `path: "*"` bat moi thu khong khop — day la cho B-187 phai vao, thay dung
 * nhanh `else → <ChatScreen/>` cu cua `App.tsx`. Thu tu trong mang khong
 * quyet dinh dieu gi: React Router xep hang theo do CU THE cua mau chu
 * khong theo vi tri, nen `/admin` luon thang `*`.
 *
 * `errorElement` la duong thu 11 (trang 500). Dat o route GOC de mot ngoai
 * le tu bat ky man hinh nao cung roi vao no — xem `pages/ServerErrorPage`.
 *
 * ── Sau cho trong cua T-3.1b, mot cho trong cua T-3.12 ─────────────────────
 *
 * `/dang-ky`, `/verify-email`, `/quen-mat-khau`, `/dat-lai-mat-khau`,
 * `/cho-duyet` la trang tam CO TEN; `/dang-nhap` da co that tu T-2.19. Sau
 * duong ay la sau man hinh auth cua T-3.1b, va task ay chi phai thay
 * `element` — khong phai dung lai cau hinh router. `/cai-dat` cung hinh dang
 * nhung chu no la T-3.12.
 */
export const routes: RouteObject[] = [
  {
    element: <Layout />,
    errorElement: <RouteErrorPage />,
    children: [
      { path: PATHS.home, element: <ChatScreen /> },
      {
        path: PATHS.admin,
        element: (
          <AdminOnly>
            <AdminScreen />
          </AdminOnly>
        ),
      },
      { path: PATHS.settings, element: <PlaceholderPage title={t("trang.caiDat")} /> },
      { path: PATHS.login, element: <LoginRoute /> },
      { path: PATHS.register, element: <PlaceholderPage title={t("trang.dangKy")} /> },
      {
        path: PATHS.forgotPassword,
        element: <PlaceholderPage title={t("trang.quenMatKhau")} />,
      },
      {
        path: PATHS.resetPassword,
        element: <PlaceholderPage title={t("trang.datLaiMatKhau")} />,
      },
      { path: PATHS.verifyEmail, element: <PlaceholderPage title={t("trang.verifyEmail")} /> },
      {
        path: PATHS.pendingApproval,
        element: <PlaceholderPage title={t("trang.choDuyet")} />,
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
