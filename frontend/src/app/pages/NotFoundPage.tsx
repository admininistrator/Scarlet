import { Link } from "react-router";

import { t } from "../../lib/i18n";
import { PATHS } from "../paths";

/**
 * Trang 404 — T-3.1a, dong B-187.
 *
 * KH tham chieu: §16.3 · tasks.md T-3.1a, B-187.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  DAY LA CHO MA `else → <ChatScreen/>` DA DUNG                          ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * B-187 ghi nguyen van: *"Ghi lai de T-3.1 KHONG chi thay `useDuongDan()`
 * roi de nguyen nhanh cuoi cua `App.tsx` — cai nhanh `else → <ChatScreen/>`
 * ay chinh la cho 404 phai vao"*. Truoc task nay, `/abcxyz` hien y het `/`:
 * mot duong go sai doc ra thanh "app chay binh thuong", va khong mot phep do
 * nao o tang HTTP bat duoc no (Cam bay ①: `curl` tra `200` + `index.html`
 * cho MOI duong, vi Vite tra trang goc con Nginx `location /` proxy thang).
 *
 * `<Link>` chu khong `<a href>`: DoD doi bam Back tra ve dung trang truoc ma
 * KHONG nap lai ca app. Mot the `<a>` thuong la mot lan tai trang day du —
 * man hinh se dung, nhung `usePhien` phai hoi lai `GET /auth/me` va moi
 * state trong bo nho bien mat.
 */
export function NotFoundPage() {
  return (
    <main className="mx-auto w-full max-w-md px-6 py-16 text-center">
      <p className="text-5xl font-semibold text-muted">404</p>
      <h2 className="mt-4 text-lg font-semibold">{t("loi.404.tieuDe")}</h2>
      <p className="mt-2 text-sm text-muted">{t("loi.404.moTa")}</p>
      <Link
        to={PATHS.home}
        className="mt-6 inline-block rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
      >
        {t("loi.404.veTrangChu")}
      </Link>
    </main>
  );
}
