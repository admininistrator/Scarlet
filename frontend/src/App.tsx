import { useEffect } from "react";
import { AdminScreen } from "./components/admin/AdminScreen";
import { FormDangNhap } from "./components/auth/FormDangNhap";
import { ChatScreen } from "./components/chat/ChatScreen";
import { ThemeToggle } from "./components/ui/ThemeToggle";
import { usePhien } from "./features/auth/usePhien";
import { t } from "./lib/i18n";
import { DUONG_ADMIN, DUONG_DANG_NHAP, DUONG_GOC, dieuHuong, useDuongDan } from "./lib/router";

/**
 * Khung app — ba duong, mot header. T-2.19 them `/admin` va `/dang-nhap`.
 *
 * KH tham chieu: §16.3, §11.2 · tasks.md T-1.14, T-2.19, T-3.1.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  CHUYEN HUONG LA PHEP LICH SU, KHONG PHAI PHAN QUYEN                   ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Cam bay cua T-2.19 viet nguyen van: *"an menu o FE khong phai phan quyen.
 * Kiem o server la bat buoc (T-2.16 da lam; task nay khong duoc dua vao FE)"*.
 *
 * `useEffect` duoi day day nguoi khong phai admin ra khoi `/admin` de ho khong
 * ngoi nhin mot man hinh toan loi 403. No KHONG dong lo nao: ai bo qua duoc
 * no — go URL truoc khi JS chay, sua state trong DevTools, goi `fetch` tu
 * console — deu gap `require_admin` o tang router cua backend. Do la ly do
 * dong DoD thu hai cua T-2.19 doi HAI phep do chu khong mot: mot cho trinh
 * duyet (chuyen huong) va mot cho `curl` (403 khi ep vao URL).
 */
export default function App() {
  const duongDan = useDuongDan();
  const phien = usePhien();

  const laAdmin = phien.nguoiDung?.role === "admin";

  useEffect(() => {
    if (phien.dangTai || duongDan !== DUONG_ADMIN || laAdmin) {
      return;
    }
    // Chua dang nhap thi di dang nhap; dang nhap roi ma khong phai admin thi ve
    // man chat. Hai dich khac nhau cho hai tinh huong khac nhau: day mot nguoi
    // da dang nhap toi form dang nhap se moi ho go lai mat khau cho mot thu ma
    // mat khau khong giai quyet duoc.
    dieuHuong(phien.nguoiDung === null ? DUONG_DANG_NHAP : DUONG_GOC);
  }, [duongDan, laAdmin, phien.dangTai, phien.nguoiDung]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold">
            <button type="button" onClick={() => dieuHuong(DUONG_GOC)}>
              {t("app.title")}
            </button>
          </h1>
          {laAdmin && (
            <button
              type="button"
              onClick={() => dieuHuong(DUONG_ADMIN)}
              className="rounded-sm border border-border px-2 py-1 text-sm hover:bg-accent hover:text-accent-foreground"
            >
              {t("admin.tieuDe")}
            </button>
          )}
        </div>

        <div className="flex items-center gap-3 text-sm">
          {phien.nguoiDung === null ? (
            <button
              type="button"
              onClick={() => dieuHuong(DUONG_DANG_NHAP)}
              className="rounded-md border border-border px-3 py-1.5 hover:bg-accent hover:text-accent-foreground"
            >
              {t("auth.dangNhap")}
            </button>
          ) : (
            <>
              <span className="text-muted">{phien.nguoiDung.email}</span>
              <button
                type="button"
                onClick={() => {
                  void phien.dangXuat().then(() => dieuHuong(DUONG_GOC));
                }}
                className="rounded-md border border-border px-3 py-1.5 hover:bg-accent hover:text-accent-foreground"
              >
                {t("auth.dangXuat")}
              </button>
            </>
          )}
          <ThemeToggle />
        </div>
      </header>

      {/*
        Trong lan `GET /auth/me` dau tien, `/admin` chua biet minh co duoc vao
        hay khong. Hien mot dong "dang tai" thay vi roi thang xuong nhanh cuoi:
        nhanh cuoi la man chat, va no se nhay ra roi bien mat trong mot phan
        giay moi lan mo `/admin` — dung kieu nhap nhay ma nguoi dung se doc
        thanh "bam nham".
      */}
      {phien.dangTai && duongDan === DUONG_ADMIN ? (
        <p className="px-6 py-4 text-sm text-muted">{t("admin.dangTai")}</p>
      ) : duongDan === DUONG_DANG_NHAP ? (
        <FormDangNhap
          loi={phien.loi}
          onGui={async (email, matKhau) => {
            const xong = await phien.dangNhap(email, matKhau);
            if (xong) {
              dieuHuong(DUONG_GOC);
            }
            return xong;
          }}
        />
      ) : duongDan === DUONG_ADMIN && laAdmin ? (
        <AdminScreen />
      ) : (
        <ChatScreen />
      )}
    </div>
  );
}
