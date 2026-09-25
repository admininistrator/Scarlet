import type { ApiError } from "../../lib/api";
import { t } from "../../lib/i18n";

/**
 * Loi cua mot lan `PUT /settings` thanh chu cho nguoi dung — Tai khoan va Model.
 *
 * `400 MODEL_UNKNOWN` o tab Tai khoan KHONG phai loi cua ten: body gui lai
 * `default_model` doc tu `/auth/me`, ma backend kiem model luc GHI (Cam bay ③
 * cua T-3.0). Admin vua tat model mac dinh cua nguoi nay thi moi lan luu ho so
 * deu `400` toi khi ho chon model khac — cau bao noi dung dieu ay.
 */
export function saveErrorText(error: ApiError): string {
  return error.code === "MODEL_UNKNOWN"
    ? t("settings.model.unknown")
    : `${t("settings.error")}: ${error.code}`;
}
