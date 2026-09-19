import { useQuanTri } from "../../features/admin/useQuanTri";
import { t } from "../../lib/i18n";
import { BangChiPhi } from "./BangChiPhi";
import { BangChoDuyet } from "./BangChoDuyet";

/**
 * Man `/admin` TOI THIEU cua T-2.19 — ba trong sau man hinh cua §16.3.
 *
 * KH tham chieu: §16.3, §18.5 · tasks.md T-2.19, B-177 · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  AN MAN NAY DI KHONG PHAI LA PHAN QUYEN                                ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Cam bay viet nguyen van trong T-2.19: *"an menu o FE KHONG phai phan quyen.
 * Kiem o server la bat buoc"*. `App.tsx` day nguoi khong phai admin ra khoi
 * duong `/admin`, nhung do la mot phep lich su voi nguoi dung, khong phai mot
 * lop bao ve: ai go thang URL, sua state trong DevTools, hay goi `fetch` tu
 * console deu vao duoc component nay — va deu nhan `403 ADMIN_REQUIRED` tu
 * `require_admin` o tang router cua backend (T-2.16).
 *
 * Vi vay component nay KHONG kiem quyen lan nua va cung khong duoc phep coi
 * "minh dang duoc render" la "minh co quyen". No goi API nhu moi man khac va
 * hien nguyen van loi neu server tu choi.
 *
 * ── Ba man hinh CON THIEU so voi §16.3 ──────────────────────────────────────
 *
 * "Nguoi dung" (doi tier, ghi de han muc, suspend), "He thong", "Audit log".
 * Ba cai dau khong nam trong "Viec can lam" cua T-2.19 va thuoc ve T-3.12; hai
 * cai sau con thieu ca ENDPOINT — `GET /admin/system` va `GET /admin/audit-logs`
 * chua ai viet, do la B-177, nay giao cho T-2.20.
 */
export function AdminScreen() {
  const qt = useQuanTri();

  return (
    <main className="flex flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-6 py-3 text-sm">
        <h2 className="text-base font-semibold">{t("admin.tieuDe")}</h2>
        <button
          type="button"
          disabled={qt.dangBan}
          onClick={() => void qt.lamTuoi()}
          className="rounded-sm border border-border px-2 py-1 hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
        >
          {t("admin.lamTuoi")}
        </button>
        <button
          type="button"
          disabled={qt.dangBan}
          onClick={() => void qt.napLaiCatalog()}
          className="rounded-sm border border-border px-2 py-1 hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
        >
          {t("admin.napCatalog")}
        </button>
        {qt.ketQuaNapCatalog !== null && (
          <span className="text-muted">
            {qt.ketQuaNapCatalog.models} {t("admin.model")} · v{qt.ketQuaNapCatalog.version}
          </span>
        )}
      </div>

      {qt.loi !== null && (
        <p role="alert" className="border-b border-border px-6 py-3 text-sm text-danger">
          {qt.loi.code} — {qt.loi.message}
        </p>
      )}

      {qt.dangTai ? (
        <p className="px-6 py-4 text-sm text-muted">{t("admin.dangTai")}</p>
      ) : (
        <>
          <BangChoDuyet
            users={qt.choDuyet}
            dangBan={qt.dangBan}
            onDoiTrangThai={(id, hanhDong) => void qt.doiTrangThai(id, hanhDong)}
          />
          {qt.chiPhi !== null && (
            <BangChiPhi chiPhi={qt.chiPhi} nguon={qt.nguon} onDoiNguon={qt.doiNguon} />
          )}
        </>
      )}
    </main>
  );
}
