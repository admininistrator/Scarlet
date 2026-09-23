import type { ReactNode } from "react";
import { Navigate } from "react-router";

import { AccountDisabledScreen } from "../components/auth/AccountDisabledScreen";
import { t } from "../lib/i18n";
import { useSession } from "./Layout";
import { PATHS } from "./paths";

/**
 * Cua vao `/cai-dat` — "da dang nhap" la du (T-3.12, B-216).
 *
 * KH tham chieu: §11.1, §18.4 · tasks.md T-3.1a (`AdminOnly`, `StatusGate`),
 * T-3.12, B-216.
 *
 * Cau hoi THU BA canh hai cua san co: `AdminOnly` hoi *"co phai admin"*,
 * `StatusGate` hoi *"tai khoan dung duoc de chat chua"*. Trang Cai dat chi hoi
 * *"anh la ai"*: backend mo `/settings` cho cot "Xem UI" cua §11.1, gom ca
 * `pending_approval` — nen cua nay KHONG day ai ve `/cho-duyet`. Nguoi dung
 * chot giu B-216 mo (2026-09-23): `StatusGate` cua man chat khong doi.
 *
 * Giong hai cua kia, day la phep lich su chu khong phai phan quyen — lop chan
 * that la `require_app_access` o backend.
 */
export function SignedInOnly({ children }: { children: ReactNode }) {
  const session = useSession();

  if (session.loading) {
    return <p className="px-6 py-4 text-sm text-muted">{t("admin.dangTai")}</p>;
  }
  if (session.locked) {
    return <AccountDisabledScreen />;
  }
  if (session.user === null) {
    return <Navigate to={PATHS.login} replace />;
  }
  return <>{children}</>;
}
