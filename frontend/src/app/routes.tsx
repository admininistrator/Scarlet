import type { ReactNode } from "react";
import { Navigate, type RouteObject } from "react-router";

import { AdminScreen } from "../components/admin/AdminScreen";
import { ForgotPasswordForm } from "../components/auth/ForgotPasswordForm";
import { PendingApprovalScreen } from "../components/auth/PendingApprovalScreen";
import { RegisterForm } from "../components/auth/RegisterForm";
import { ResetPasswordForm } from "../components/auth/ResetPasswordForm";
import { StatusGate } from "../components/auth/StatusGate";
import { VerifyEmailScreen } from "../components/auth/VerifyEmailScreen";
import { ChatScreen } from "../components/chat/ChatScreen";
import { AccountPanel } from "../components/settings/AccountPanel";
import { AppearancePanel } from "../components/settings/AppearancePanel";
import { ByokPanel } from "../components/settings/ByokPanel";
import { ModelPanel } from "../components/settings/ModelPanel";
import {
  SettingsIndex,
  SettingsLayout,
  type SettingsTabPath,
} from "../components/settings/SettingsLayout";
import { UsagePanel } from "../components/settings/UsagePanel";
import { AdminOnly } from "./AdminOnly";
import { Layout } from "./Layout";
import { LoginRoute } from "./LoginRoute";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RouteErrorPage } from "./pages/ServerErrorPage";
import { PATHS } from "./paths";
import { SignedInOnly } from "./SignedInOnly";

/**
 * T-S.11 — nam tab cua Cai dat, MOI tab mot duong dan (§24.2b·S10). Viet
 * tuong minh tung duong chu khong mot `/cai-dat/:tab`: duong la hang cua
 * `PATHS`, va mot slug go sai roi vao `*` (404) chu khong vao mot tab rong.
 */
const SETTINGS_ROUTES: readonly (readonly [SettingsTabPath, ReactNode])[] = [
  [PATHS.settingsAccount, <AccountPanel />],
  [PATHS.settingsAppearance, <AppearancePanel />],
  [PATHS.settingsModel, <ModelPanel />],
  [PATHS.settingsByok, <ByokPanel />],
  [PATHS.settingsUsage, <UsagePanel />],
];

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
 * ── Sau cho trong CO TEN cua T-3.1a nay deu da co man hinh ───────────────
 *
 * T-3.1a khai san sau cho trong cho `/dang-ky`, `/verify-email`,
 * `/quen-mat-khau`, `/dat-lai-mat-khau`, `/cho-duyet`, `/cai-dat` de task sau
 * *"chi phai dien, khong phai dung lai cau hinh router"*. T-3.1b dien nam cho
 * dau, T-3.12 dien `/cai-dat` — `PlaceholderPage` het nguoi dung va bi xoa.
 * `/cai-dat` boc `SignedInOnly` (chi hoi "da dang nhap chua", xem B-216);
 * T-S.11 tach no thanh nam tab, moi tab cung boc `SignedInOnly`.
 *
 * ── `StatusGate` boc man chat, `AdminOnly` boc man quan tri ────────────────
 *
 * Hai cua vao, hai cau hoi khac nhau: `AdminOnly` hoi *"anh co phai admin
 * khong"* (§16.3), `StatusGate` hoi *"tai khoan cua anh dung duoc chua"*
 * (§11.1). Chung KHONG long vao nhau o `/admin`, va do la chu y — mot admin
 * thi theo dinh nghia da `active`, nen boc them mot lop nua chi them mot
 * duong de sai ma khong chan them ai.
 */
export const routes: RouteObject[] = [
  {
    element: <Layout />,
    errorElement: <RouteErrorPage />,
    children: [
      {
        path: PATHS.home,
        element: (
          <StatusGate>
            <ChatScreen />
          </StatusGate>
        ),
      },
      {
        path: PATHS.admin,
        element: (
          <AdminOnly>
            <AdminScreen />
          </AdminOnly>
        ),
      },
      {
        path: PATHS.settings,
        element: (
          <SignedInOnly>
            <SettingsIndex />
          </SignedInOnly>
        ),
      },
      ...SETTINGS_ROUTES.map(([path, panel]) => ({
        path,
        element: (
          <SignedInOnly>
            <SettingsLayout tab={path}>{panel}</SettingsLayout>
          </SignedInOnly>
        ),
      })),
      { path: PATHS.settingsApiKeys, element: <Navigate to={PATHS.settingsByok} replace /> },
      { path: PATHS.login, element: <LoginRoute /> },
      { path: PATHS.register, element: <RegisterForm /> },
      { path: PATHS.forgotPassword, element: <ForgotPasswordForm /> },
      { path: PATHS.resetPassword, element: <ResetPasswordForm /> },
      { path: PATHS.verifyEmail, element: <VerifyEmailScreen /> },
      { path: PATHS.pendingApproval, element: <PendingApprovalScreen /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
