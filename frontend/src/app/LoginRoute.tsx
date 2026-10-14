import { useNavigate, useSearchParams } from "react-router";

import { LoginForm } from "../components/auth/LoginForm";
import { pathForStatus } from "../components/auth/statusRoute";
import { useSession } from "./Layout";
import { PATHS } from "./paths";

/**
 * Noi `LoginForm` (T-2.19) vao bang route — T-3.1a, dinh tuyen o T-3.1b.
 *
 * KH tham chieu: §11.1, §11.2 · tasks.md T-2.19, T-3.1a, T-3.1b.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  DANG NHAP XONG KHONG CON CO NGHIA LA "VE MAN CHAT"                    ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * §11.1 cho ca `pending_email` lan `pending_approval` dang nhap duoc — ho can
 * thay giao dien de verify / de biet minh dang cho. Nhung dua ho thang toi man
 * chat la dua ho toi mot o nhap se tra `403` o lan bam Gui dau tien, va man
 * hinh khong noi truoc mot chu nao. `pathForStatus` tra loi "nguoi nay thuoc
 * ve dau", va `StatusGate` doc dung bang ay — mot bang, hai nguoi hoi.
 *
 * `LoginForm` giu nguyen chu ky `Promise<boolean>`: no khong can biet ket
 * qua dieu huong, no chi can biet "co nen dong o nhap lai khong".
 *
 * `taiKhoanBiKhoa` (`rejected`/`suspended`) KHONG di qua day: `POST
 * /auth/login` tra `403 ACCOUNT_DISABLED` truoc khi co `NguoiDungRa` nao, nen
 * `LoginForm` hien cau giai thich ngay tai cho — dung man giai thich cua
 * "Viec can lam", chi la no o canh o nhap chu khong o mot dia chi khac.
 */
/**
 * T-8.3 — `?next=` chi nhan duong TUONG DOI cung origin: bat dau `/`, khong
 * `//` (protocol-relative), khong `\` (trinh duyet doi thanh `/`), khong ky tu
 * dieu khien (trinh duyet bo tab/xuong dong ⇒ `/<tab>/evil` thanh `//evil`).
 * Sai ⇒ `null` (bo qua) — open redirect la lo cua chinh trang dang nhap.
 */
export function safeNext(next: string | null): string | null {
  if (next === null || !next.startsWith("/") || next.startsWith("//")) {
    return null;
  }
  return [...next].some((c) => c === "\\" || c < " ") ? null : next;
}

export function LoginRoute() {
  const session = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));

  return (
    <LoginForm
      error={session.error}
      onSend={async (email, password) => {
        const user = await session.login(email, password);
        if (user === null) {
          return false;
        }
        // `next` thang `pathForStatus`: tai khoan `pending_*` quay ve trang
        // share va doc cau `403` o do (T-8.3), khong vong lap dang nhap.
        void navigate(next ?? pathForStatus(user.status) ?? PATHS.home);
        return true;
      }}
    />
  );
}
