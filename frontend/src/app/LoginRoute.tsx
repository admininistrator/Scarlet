import { useNavigate } from "react-router";

import { FormDangNhap } from "../components/auth/FormDangNhap";
import { useSession } from "./Layout";
import { PATHS } from "./paths";

/**
 * Noi `FormDangNhap` (T-2.19) vao bang route — T-3.1a.
 *
 * KH tham chieu: §11.2 · tasks.md T-2.19, T-3.1a, T-3.1b.
 *
 * Mot lop adapter MONG va co y mong: T-3.1b so huu sau man hinh auth va se
 * thay than cua no (dieu huong theo `status` cua §11.1: `pending_verification`
 * → `/verify-email`, `pending_approval` → `/cho-duyet`, ...). Cho toi luc ay,
 * chuyen duy nhat no lam la giu nguyen hanh vi T-2.19: dang nhap xong thi ve
 * man chat.
 */
export function LoginRoute() {
  const session = useSession();
  const navigate = useNavigate();

  return (
    <FormDangNhap
      loi={session.loi}
      onGui={async (email, matKhau) => {
        const xong = await session.dangNhap(email, matKhau);
        if (xong) {
          void navigate(PATHS.home);
        }
        return xong;
      }}
    />
  );
}
