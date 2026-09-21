import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { PATHS } from "../../app/paths";
import { ApiError, MA_LOI, api } from "../../lib/api";
import { t } from "../../lib/i18n";
import { authErrorText } from "./authErrors";

/**
 * Man `/dat-lai-mat-khau?token=` — §11.5, NQ-44. T-3.1b.
 *
 * KH tham chieu: §11.3, §11.5, §11.6 · tasks.md T-2.5, T-3.1b · NQ-44.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  XONG ROI VAN PHAI DANG NHAP LAI, VA DO LA CHU Y                       ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `POST /auth/reset-password` **khong** dang nhap ai ca (NQ-44, B-130) va no
 * con xoa hai cookie phien dang co, vi doi mat khau la thu hoi MOI phien
 * (§11.3). Nen man hinh nay khong duoc tu dieu huong ve `/` nhu mot lan dang
 * nhap thanh cong: no noi ra rang moi phien cu da bi thu hoi, roi moi nguoi
 * dung dang nhap lai. Mot lan chuyen thang ve man chat o day se cho ra mot
 * man chat `401` o moi loi goi — dung trieu chung ma NQ-44 tranh.
 *
 * ── `TOKEN_INVALID` khong phai mot loi form ────────────────────────────────
 *
 * Ba kieu token hong (khong ton tai / da dung / het han) deu ra mot cau tra
 * loi o backend (`_LOI_TOKEN_RESET`), va ca ba deu co cung duong di tiep: xin
 * mot lien ket moi. Nen no duoc ve thanh mot man hinh co LOI THOAT, khong
 * phai mot dong do duoi o mat khau — go lai mat khau khong sua duoc mot lien
 * ket het han, va de nguoi dung go them lan nua la de ho tu tim ra dieu do.
 */
export function ResetPasswordForm() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");

  const [password, setPassword] = useState("");
  const [dangGui, setDangGui] = useState(false);
  const [loi, setLoi] = useState<string | null>(null);
  const [tokenHong, setTokenHong] = useState(false);
  const [xong, setXong] = useState(false);

  if (token === null || tokenHong) {
    return (
      <main className="mx-auto w-full max-w-sm px-6 py-12">
        <h2 className="text-lg font-semibold">{t("datLai.tieuDe")}</h2>
        <p role="alert" className="mt-2 text-sm text-danger-emphasis">
          {token === null ? t("datLai.thieuToken") : t("datLai.tokenHong")}
        </p>
        <Link
          to={PATHS.forgotPassword}
          className="mt-6 inline-block rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
        >
          {t("datLai.xinLienKetMoi")}
        </Link>
      </main>
    );
  }

  if (xong) {
    return (
      <main className="mx-auto w-full max-w-sm px-6 py-12">
        <h2 className="text-lg font-semibold">{t("datLai.xong.tieuDe")}</h2>
        <p className="mt-2 text-sm text-muted">{t("datLai.xong.moTa")}</p>
        <Link
          to={PATHS.login}
          className="mt-6 inline-block rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
        >
          {t("auth.dangNhap")}
        </Link>
      </main>
    );
  }

  async function gui() {
    setLoi(null);
    setDangGui(true);
    try {
      await api.datLaiMatKhau(token as string, password);
      setXong(true);
    } catch (e) {
      // Token hong -> doi ca man hinh; mat khau qua ngan/yeu -> mot dong do
      // canh o nhap, vi do la thu go lai duoc.
      if (e instanceof ApiError && e.code === MA_LOI.TOKEN_HONG) {
        setTokenHong(true);
      } else {
        setLoi(authErrorText(e));
      }
    } finally {
      setDangGui(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-sm px-6 py-12">
      <h2 className="mb-6 text-lg font-semibold">{t("datLai.tieuDe")}</h2>

      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void gui();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">{t("datLai.matKhauMoi")}</span>
          <input
            type="password"
            required
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-sm border border-border bg-background px-2 py-1.5 text-foreground"
          />
        </label>
        {/*
          Goi y nam NGOAI `<label>`, khong trong: moi chu trong the `label`
          deu chay vao ten truy cap duoc cua o nhap, nen mot dong goi y o
          trong bien nhan cua o thanh "Mat khau Dung mot mat khau dai, ..." —
          va moi `getByLabelText("Mật khẩu")` (test, lan trinh doc man hinh)
          khong con tim thay no.
        */}
        <span className="-mt-2 text-xs text-muted">{t("auth.matKhauGoiY")}</span>

        {loi !== null && (
          <p role="alert" className="text-sm text-danger-emphasis">
            {loi}
          </p>
        )}

        <button
          type="submit"
          disabled={dangGui}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
        >
          {dangGui ? t("auth.dangXuLy") : t("datLai.dat")}
        </button>
      </form>
    </main>
  );
}
