import { useNavigate } from "react-router";

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
export function LoginRoute() {
  const session = useSession();
  const navigate = useNavigate();

  return (
    <LoginForm
      error={session.error}
      onSend={async (email, password) => {
        const user = await session.login(email, password);
        if (user === null) {
          return false;
        }
        void navigate(pathForStatus(user.status) ?? PATHS.home);
        return true;
      }}
    />
  );
}
