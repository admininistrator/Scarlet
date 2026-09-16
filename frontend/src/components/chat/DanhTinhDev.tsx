import { useState } from "react";
import { t } from "../../lib/i18n";

/**
 * O nhap `user_id` tam cua Phase 1 — NQ-24 (header) / NQ-33 (cookie).
 *
 * KHONG phai man hinh dang nhap va khong dinh gia lam mot. Auth that la T-2.3;
 * o nay ton tai vi `get_current_user_id` doi mot danh tinh, ma `EventSource`
 * khong dat duoc header — nen FE dat cookie `scarlet_dev_user`.
 *
 * De o vi tri de thay chu khong giau trong mot man hinh cai dat: mot cho tam
 * ma trong giong do that la mot cho tam se song sot.
 */
export function DanhTinhDev({
  danhTinh,
  onDat,
}: {
  danhTinh: string | null;
  onDat: (userId: string) => void;
}) {
  const [nhap, setNhap] = useState("");

  return (
    <form
      className="flex flex-wrap items-center gap-2 border-b border-border px-6 py-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (nhap.trim() !== "") {
          onDat(nhap);
          setNhap("");
        }
      }}
    >
      <span className="text-muted">{t("chat.danhTinhNhan")}:</span>
      <code className="text-foreground">{danhTinh ?? t("chat.danhTinhTrong")}</code>
      <input
        value={nhap}
        onChange={(e) => setNhap(e.target.value)}
        placeholder={t("chat.danhTinhONhap")}
        className="min-w-[22rem] rounded-sm border border-border bg-background px-2 py-1 text-foreground"
      />
      <button
        type="submit"
        className="rounded-sm border border-border px-2 py-1 text-foreground hover:bg-accent hover:text-accent-foreground"
      >
        {t("chat.danhTinhDat")}
      </button>
      <span className="text-muted">{t("chat.danhTinhGiaiThich")}</span>
    </form>
  );
}
