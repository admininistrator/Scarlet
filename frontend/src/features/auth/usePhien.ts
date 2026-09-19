/**
 * Phien dang nhap cua FE — nua client cua §11.2 (NQ-36).
 *
 * KH tham chieu: §11.2, §11.1, §16.3 · tasks.md T-2.3, T-2.7, T-2.19 · NQ-36.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHONG CO "TRANG THAI DANG NHAP" NAO DUOC LUU O FE                     ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Access token nam trong cookie `scarlet_session` voi co `HttpOnly` (NQ-36),
 * tuc JS cua trang khong doc duoc no — co chu y. Hau qua: FE khong co cach
 * nao TU BIET minh dang la ai; no phai HOI, va cau hoi do la `GET /auth/me`.
 *
 * Vi vay khong co `localStorage.setItem("user", ...)` o day va khong duoc
 * them. Mot ban sao danh tinh trong `localStorage` se song sot qua ca luc
 * cookie het han va luc admin bam Suspend (§11.3) — tuc man hinh van hien ten
 * mot nguoi da bi khoa, trong khi moi loi goi API deu 401. Nguon su that o
 * phia server, va gia phai tra la mot lan `GET /auth/me` luc mo trang.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type NguoiDungRa } from "../../lib/api";

export interface Phien {
  /** `null` = chua dang nhap (hoac phien da het). */
  nguoiDung: NguoiDungRa | null;
  /** Lan hoi `GET /auth/me` dau tien con dang chay hay khong. */
  dangTai: boolean;
  /** Loi cua lan `dangNhap()` gan nhat; `null` khi chua thu hoac da thanh cong. */
  loi: ApiError | null;
  dangNhap: (email: string, matKhau: string) => Promise<boolean>;
  dangXuat: () => Promise<void>;
}

export function usePhien(): Phien {
  const [nguoiDung, setNguoiDung] = useState<NguoiDungRa | null>(null);
  const [dangTai, setDangTai] = useState(true);
  const [loi, setLoi] = useState<ApiError | null>(null);

  useEffect(() => {
    let conGan = true;
    void (async () => {
      try {
        const ra = await api.toiLaAi();
        if (conGan) {
          setNguoiDung(ra);
        }
      } catch {
        // 401 (chua dang nhap) va 403 (tai khoan bi khoa, §11.1) deu dan toi
        // cung mot man hinh: khong co phien. Phan biet chung o day se them
        // mot nhanh ma khong doi duoc gi nguoi dung lam tiep duoc.
        if (conGan) {
          setNguoiDung(null);
        }
      } finally {
        if (conGan) {
          setDangTai(false);
        }
      }
    })();
    return () => {
      conGan = false;
    };
  }, []);

  const dangNhap = useCallback(async (email: string, matKhau: string): Promise<boolean> => {
    setLoi(null);
    try {
      setNguoiDung(await api.dangNhap(email, matKhau));
      return true;
    } catch (e) {
      setLoi(e instanceof ApiError ? e : new ApiError(0, "HTTP_ERROR", String(e)));
      return false;
    }
  }, []);

  const dangXuat = useCallback(async (): Promise<void> => {
    try {
      await api.dangXuat();
    } finally {
      // Xoa danh tinh o FE DU cho loi goi that bai: `POST /auth/logout` co y
      // khong doi xac thuc (NQ-42) va khong co ket cuc thu hai de bao, nen mot
      // loi o day gan nhu chac chan la mang chu khong phai "chua dang xuat".
      // Giu man hinh o trang thai "van dang dang nhap" chi lam nguoi dung
      // tuong minh chua thoat.
      setNguoiDung(null);
    }
  }, []);

  return { nguoiDung, dangTai, loi, dangNhap, dangXuat };
}
