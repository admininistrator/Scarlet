import { t } from "../../lib/i18n";

/**
 * Trang tam CO TEN — T-3.1a.
 *
 * KH tham chieu: §16.3 · tasks.md T-3.1a, T-3.1b, T-3.12.
 *
 * "Viec can lam" cua T-3.1a doi dung hinh dang nay: *"Khai cho trong cho 6
 * duong auth cua T-3.1b (route ton tai, component la mot trang tam CO TEN) —
 * de T-3.1b chi phai dien, khong phai dung lai cau hinh router"*.
 *
 * Co TEN la phan quan trong, khong phai phan trang tri: mot trang trong se
 * doc y het trang 404, va khi ay khong ai phan biet duoc "man hinh nay chua
 * duoc dung" voi "duong dan nay go sai" — dung hai ket luan doi lap ma
 * B-187 vua ton mot muc Backlog de tach ra.
 */
export function PlaceholderPage({ title }: { title: string }) {
  return (
    <main className="mx-auto w-full max-w-md px-6 py-16 text-center">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mt-2 text-sm text-muted">{t("trangTam.moTa")}</p>
    </main>
  );
}
