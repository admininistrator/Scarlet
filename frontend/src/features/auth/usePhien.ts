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
import { ApiError, MA_LOI, api, type NguoiDungRa } from "../../lib/api";

export interface Phien {
  /** `null` = chua dang nhap (hoac phien da het). */
  nguoiDung: NguoiDungRa | null;
  /** Lan hoi `GET /auth/me` dau tien con dang chay hay khong. */
  dangTai: boolean;
  /**
   * `GET /auth/me` tra `403 ACCOUNT_DISABLED` — tai khoan `rejected` hoac
   * `suspended` (§11.1). **Khac** `nguoiDung === null`, xem chu thich trong
   * `useEffect` ben duoi.
   */
  biKhoa: boolean;
  /** Loi cua lan `dangNhap()` gan nhat; `null` khi chua thu hoac da thanh cong. */
  loi: ApiError | null;
  /** Tra `NguoiDungRa` khi thanh cong — caller can `status` de dinh tuyen (§11.1). */
  dangNhap: (email: string, matKhau: string) => Promise<NguoiDungRa | null>;
  dangXuat: () => Promise<void>;
}

export function usePhien(): Phien {
  const [nguoiDung, setNguoiDung] = useState<NguoiDungRa | null>(null);
  const [dangTai, setDangTai] = useState(true);
  const [biKhoa, setBiKhoa] = useState(false);
  const [loi, setLoi] = useState<ApiError | null>(null);

  useEffect(() => {
    let conGan = true;
    void (async () => {
      try {
        const ra = await api.toiLaAi();
        if (conGan) {
          setNguoiDung(ra);
          setBiKhoa(false);
        }
      } catch (e) {
        // T-2.19 gop 401 va 403 vao mot ket cuc vi luc do chung dan toi cung
        // mot man hinh. T-3.1b tach chung ra, va ly do la mot dong cua "Viec
        // can lam": *"`suspended` -> man giai thich. **Khong** roi ve man
        // chat"*. Ke tu day hai ma loi ay dan toi hai man hinh khac nhau, nen
        // gop chung lai chinh la danh mat thong tin duy nhat phan biet duoc.
        //
        // `nguoiDung` VAN la `null` o ca hai ca: khong co phien dung duoc.
        // `biKhoa` la mot truong RIENG chu khong mot gia tri thu ba cua
        // `nguoiDung`, de moi cho dang doc `nguoiDung === null` giu nguyen
        // nghia cu.
        if (conGan) {
          setNguoiDung(null);
          setBiKhoa(e instanceof ApiError && e.code === MA_LOI.TAI_KHOAN_BI_KHOA);
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

  const dangNhap = useCallback(
    async (email: string, matKhau: string): Promise<NguoiDungRa | null> => {
      setLoi(null);
      try {
        const ra = await api.dangNhap(email, matKhau);
        setNguoiDung(ra);
        setBiKhoa(false);
        // Tra `ra` chu khong `true`: caller phai dinh tuyen theo `status`
        // (§11.1) NGAY trong cung mot nhip, va `nguoiDung` cua state thi chua
        // cap nhat o thoi diem promise nay resolve.
        return ra;
      } catch (e) {
        setLoi(e instanceof ApiError ? e : new ApiError(0, "HTTP_ERROR", String(e)));
        return null;
      }
    },
    [],
  );

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
      setBiKhoa(false);
    }
  }, []);

  return { nguoiDung, dangTai, biKhoa, loi, dangNhap, dangXuat };
}
