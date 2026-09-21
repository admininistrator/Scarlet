import { useState } from "react";
import { Link } from "react-router";

import { PATHS } from "../../app/paths";
import { api } from "../../lib/api";
import { t } from "../../lib/i18n";
import { Turnstile } from "./Turnstile";
import { authErrorText } from "./authErrors";
import { useTurnstile } from "./useTurnstile";

/**
 * Man `/dang-ky` — UC-01, §11.6. T-3.1b, dong B-185.
 *
 * KH tham chieu: §11.1, §11.5, §11.6, UC-01 · tasks.md T-2.6, T-3.1b, B-185.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  DAY LA CHO DAU TIEN `Turnstile.tsx` DUOC MOUNT                        ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * T-2.6 dung widget tu Phase 2 va docstring cua no ghi thang: *"CHUA CO MAN
 * HINH NAO DUNG NO, VA DO LA DUNG PHAM VI"*. B-185 la muc Backlog giu cho
 * ngay hom nay. He qua do duoc: truoc man hinh nay, cach duy nhat chay het
 * UC-01 tren stack that la tam doi `TURNSTILE_SECRET` sang khoa test "luon
 * dat" cua Cloudflare roi dang ky bang `curl`.
 *
 * ── MOT CAU TRA LOI CHO CA HAI NHANH (UC-01 dong 1) ───────────────────────
 *
 * Email da ton tai va email moi cho ra man hinh GIONG HET nhau, va no giong
 * het **vi khong co gi de khac**: backend tra dung mot `_PHAN_HOI_DANG_KY`
 * cho ca hai (§11.5), nen o day khong co mot nhanh nao doc `message` ra de re
 * duong. Man hinh thanh cong duoi day duoc ve tu `vi.json`, khong tu response
 * — mot ngay nao do ai do doi cau chu cua backend cung khong lam lo ra email
 * nao da dang ky.
 *
 * ── `reset()` SAU MOI LOI ─────────────────────────────────────────────────
 *
 * Cloudflare tieu token ngay lan `siteverify` dau tien. Sau mot `422` vi mat
 * khau qua yeu, lan gui thu hai chac chan `400 TURNSTILE_FAILED` neu khong
 * xin token moi — xem `useTurnstile`.
 */
export function RegisterForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [dangGui, setDangGui] = useState(false);
  const [loi, setLoi] = useState<string | null>(null);
  const [xong, setXong] = useState(false);
  const turnstile = useTurnstile();

  if (xong) {
    return (
      <main className="mx-auto w-full max-w-sm px-6 py-12">
        <h2 className="text-lg font-semibold">{t("dangKy.daGui.tieuDe")}</h2>
        <p className="mt-2 text-sm text-muted">{t("dangKy.daGui.moTa")}</p>
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
    if (turnstile.thieuToken) {
      setLoi(t("auth.turnstileChua"));
      return;
    }
    setLoi(null);
    setDangGui(true);
    try {
      await api.dangKy(email, password, turnstile.token);
      setXong(true);
    } catch (e) {
      setLoi(authErrorText(e));
      turnstile.reset();
    } finally {
      setDangGui(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-sm px-6 py-12">
      <h2 className="mb-6 text-lg font-semibold">{t("auth.dangKy")}</h2>

      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void gui();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">{t("auth.email")}</span>
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-sm border border-border bg-background px-2 py-1.5 text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">{t("auth.matKhau")}</span>
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

        <Turnstile onToken={turnstile.onToken} ref={turnstile.ref} className="my-1" />

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
          {dangGui ? t("auth.dangXuLy") : t("auth.dangKy")}
        </button>
      </form>

      <Link to={PATHS.login} className="mt-6 inline-block text-sm text-muted underline">
        {t("auth.daCoTaiKhoan")}
      </Link>
    </main>
  );
}
