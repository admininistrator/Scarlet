import { useRouteError } from "react-router";

import { t } from "../../lib/i18n";

/**
 * Trang 500 — T-3.1a.
 *
 * KH tham chieu: §16.3 · tasks.md T-3.1a.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOT TRANG, HAI NGUOI BAT                                              ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * React va React Router so huu hai phan khac nhau cua cay, nen mot ngoai le
 * luc render co the roi vao mot trong hai chu khong bao gio ca hai:
 *
 *  - Ngoai le NEM TU MOT ROUTE di len `errorElement` cua route cha gan nhat.
 *    Trong che do data router, route goc LUON co mot error boundary — neu ta
 *    khong dat `errorElement` thi React Router dung trang mac dinh cua no
 *    ("Unhandled Thrown Error" + stack tho). Do la ly do `RouteErrorPage`
 *    ton tai: khong phai de bat them, ma de trang mac dinh ay khong bao gio
 *    duoc hien.
 *  - Ngoai le nem NGOAI cay route — chinh `RouterProvider`, hay bat cu thu
 *    gi `App.tsx` dat canh no — khong ai trong so do bat. Do la viec cua
 *    `ErrorBoundary` (class component, boc toan app trong `App.tsx`).
 *
 * Hai nguoi bat, nhung MOT trang: ca hai deu render `ServerErrorPage`. Hai
 * ban sao cua cung mot man hinh loi la hai cho de lech nhau, va cho lech se
 * lo dien dung luc khong ai con binh tinh doc ky.
 *
 * ── Vi sao hien nguyen van thong bao loi ────────────────────────────────
 *
 * Scarlet la app self-host cho 15–20 nguoi quen biet, khong phai trang cong
 * khai: mot dong `TypeError: ... is not a function` o day la thu nguoi dung
 * chep vao tin nhan bao loi. Giau no di chi de lai "co gi do khong on", tuc
 * dung triet chung ma B-187 vua chung minh la dat: mot man hinh khong noi gi
 * doc ra thanh mot man hinh khong hong.
 */
function messageOf(error: unknown): string | null {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string" && error !== "") {
    return error;
  }
  return null;
}

export function ServerErrorPage({ error }: { error: unknown }) {
  const detail = messageOf(error);

  return (
    <main className="mx-auto w-full max-w-md px-6 py-16 text-center">
      <p className="text-5xl font-semibold text-muted">500</p>
      <h2 className="mt-4 text-lg font-semibold">{t("loi.500.tieuDe")}</h2>
      <p className="mt-2 text-sm text-muted">{t("loi.500.moTa")}</p>

      {detail !== null && (
        <pre className="mt-4 overflow-x-auto rounded-sm border border-border px-3 py-2 text-left text-xs text-danger-text">
          {detail}
        </pre>
      )}

      <button
        type="button"
        onClick={() => window.location.reload()}
        className="motion-press mt-6 min-h-touch rounded-md border border-border px-3 text-sm hover:bg-accent hover:text-accent-foreground"
      >
        {t("loi.500.taiLai")}
      </button>
    </main>
  );
}

/** Ban dung lam `errorElement` cua bang route — xem docstring dau file. */
export function RouteErrorPage() {
  return <ServerErrorPage error={useRouteError()} />;
}
