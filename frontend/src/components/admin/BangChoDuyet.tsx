import type { AdminUserRa, HanhDongUser } from "../../lib/api";
import { t } from "../../lib/i18n";

/**
 * Man "Duyet user" cua §16.3 — danh sach `pending_approval`, hai nut.
 *
 * §16.3 doi dung ba thu o day: *"Danh sach pending_approval, nut Duyet/Tu
 * choi, xem email + thoi diem dang ky"*. Khong co cot nao khac, ke ca nhung
 * cot dang co san trong response: bang NAY tra loi mot cau hoi ("cho nguoi
 * nay vao khong"), con bang "Nguoi dung" cua §16.3 la mot man hinh khac va no
 * thuoc ve T-3.12.
 *
 * Hai cot cua bang "Nguoi dung" — *so hoi thoai* va *chi tieu 7 ngay* — chua
 * co duong du lieu; B-176 da chot huong (mot cau JOIN trong `GET
 * /admin/users`) va giao viec hien thuc cho T-3.12.
 */
export function BangChoDuyet({
  users,
  dangBan,
  onDoiTrangThai,
}: {
  users: AdminUserRa[];
  dangBan: boolean;
  onDoiTrangThai: (userId: string, hanhDong: HanhDongUser) => void;
}) {
  return (
    <section className="px-6 py-4">
      <h3 className="mb-3 text-base font-semibold">
        {t("admin.choDuyet")} <span className="text-muted">({users.length})</span>
      </h3>

      {users.length === 0 ? (
        <p className="text-sm text-muted">{t("admin.khongAiChoDuyet")}</p>
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-muted">
              <th className="py-2 pr-4 font-normal">{t("admin.email")}</th>
              <th className="py-2 pr-4 font-normal">{t("admin.dangKyLuc")}</th>
              <th className="py-2 pr-4 font-normal">{t("admin.tier")}</th>
              <th className="py-2 font-normal">{t("admin.hanhDong")}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-border">
                <td className="py-2 pr-4">{u.email}</td>
                <td className="py-2 pr-4 text-muted">{new Date(u.created_at).toLocaleString()}</td>
                <td className="py-2 pr-4 text-muted">{u.tier_name}</td>
                <td className="flex gap-2 py-2">
                  <button
                    type="button"
                    disabled={dangBan}
                    onClick={() => onDoiTrangThai(u.id, "approve")}
                    className="rounded-sm border border-border px-2 py-1 hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
                  >
                    {t("admin.duyet")}
                  </button>
                  <button
                    type="button"
                    disabled={dangBan}
                    onClick={() => onDoiTrangThai(u.id, "reject")}
                    className="rounded-sm border border-border px-2 py-1 text-danger-emphasis hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
                  >
                    {t("admin.tuChoi")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
