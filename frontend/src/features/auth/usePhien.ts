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
import { ApiError, MA_LOI, api, type HoSoRa, type NguoiDungRa } from "../../lib/api";

export interface Phien {
  /** `null` = chua dang nhap (hoac phien da het). */
  nguoiDung: NguoiDungRa | null;
  /**
   * Cau tra loi DAY DU cua `GET /auth/me` — `quota`, `message_max_chars`,
   * `default_model` (§18.1, B-213).
   *
   * Tach khoi `nguoiDung` chu khong mo rong no, vi `/auth/login` KHONG tra
   * hai truong dau: chung dat hai luot doc Redis (`HoSoRa` cua backend giai
   * thich vi sao), va mot cai ten kieu `NguoiDungRa` hua ba truong ma chi hai
   * duong trong ba tra ve la mot cai bay im lang.
   *
   * `null` khi chua hoi xong, khi chua dang nhap, hoac khi lan hoi do hong.
   * Ben doc phai co duong lui: mot `message_max_chars` khong biet la "khong
   * dem duoc", khong phai "khong co tran" — tran that o `422` cua server.
   */
  hoSo: HoSoRa | null;
  /**
   * T-3.11 — `Date.now()` luc cau tra loi `/auth/me` dang nam trong `hoSo`
   * VE TOI trinh duyet. `retry_after` la so giay TINH TU LUC DO, nen doi no
   * thanh mot moc gio can dung moc nay chu khong `Date.now()` luc render.
   *
   * Mot truong rieng chu khong suy tu danh tinh object `hoSo`: `datModelMacDinh`
   * cung thay `hoSo` bang mot object moi ma khong doc lai quota nao.
   */
  profileReadAt: number | null;
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
  /**
   * T-3.6 — ghi `users.default_model` (`PUT /settings`) va cap nhat `hoSo`
   * tai cho. UC-05 dong 4: *"user doi duoc va duoc nho theo user"*.
   *
   * O DAY chu khong trong `useChat`, vi day la mot truong cua `/auth/me` va
   * `Layout` la nguoi duy nhat hoi cau hoi ay (xem docstring `Layout`). Giu
   * mot ban sao thu hai trong man chat nghia la sau khi doi model, hai cho
   * tren cung mot trang se noi hai chuyen khac nhau cho toi lan F5.
   *
   * Nem lai loi cho ben goi: `400 MODEL_UNKNOWN` la mot ket cuc co that
   * (catalog sua nong — Cam bay ③ cua T-3.0) va man hinh phai noi duoc.
   */
  datModelMacDinh: (modelId: string | null) => Promise<void>;
  /**
   * T-3.11 — hoi lai `GET /auth/me` de lam tuoi thanh quota.
   *
   * Goi SAU moi luot sinh (`done`/`error`) va sau mot `429 QUOTA_EXCEEDED`,
   * khong theo mot bo dem thoi gian: quota chi doi khi `usage_events` co dong
   * moi (B-209). Loi o day giu nguyen `hoSo` cu — mot lan lam tuoi hong khong
   * phai la "da dang xuat", va dinh tuyen van la viec cua lan hoi luc mount.
   */
  refreshProfile: () => Promise<void>;
}

export function usePhien(): Phien {
  const [nguoiDung, setNguoiDung] = useState<NguoiDungRa | null>(null);
  const [hoSo, setHoSo] = useState<HoSoRa | null>(null);
  const [profileReadAt, setProfileReadAt] = useState<number | null>(null);
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
          setHoSo(ra);
          setProfileReadAt(Date.now());
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
          setHoSo(null);
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
        /*
          Hoi them `GET /auth/me` sau khi dang nhap — B-213.

          `Layout` goi `usePhien()` MOT lan luc mount, va dieu huong sau dang
          nhap la dieu huong phia client: khong co lan mount thu hai nao de
          `/auth/me` tu chay lai. Khong co dong nay thi ca mot phien bat dau
          bang man dang nhap se khong bao gio biet `message_max_chars` —
          nguoi dung go bao nhieu cung khong thay bo dem, roi nhan `422`.

          Loi o day KHONG lam hong lan dang nhap: phien da that su mo (cookie
          da duoc dat), chi la phan "biet them" chua ve. `hoSo` o lai `null`
          va ben doc di duong lui cua no.
        */
        void api
          .toiLaAi()
          .then((hoSoMoi) => {
            setHoSo(hoSoMoi);
            setProfileReadAt(Date.now());
          })
          .catch(() => setHoSo(null));
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
      setHoSo(null);
      setBiKhoa(false);
    }
  }, []);

  const datModelMacDinh = useCallback(async (modelId: string | null): Promise<void> => {
    const ra = await api.capNhatCaiDat(modelId);
    /*
      Doc lai tu RESPONSE chu khong tu `modelId` vua gui: server la noi
      quyet dinh, va no tra `CaiDatRa` dung de ben goi khong phai suy ra
      (xem docstring `CaiDatRa` cua backend).

      Ca hai cho cung mang truong nay: `NguoiDungRa.default_model` la mot
      cot cua hang `users` nen ca `/login`, `/refresh` lan `/me` deu tra —
      cap nhat mot cho roi de cho kia lech la dung cai bay B-213 noi toi.
    */
    setHoSo((cu) => (cu === null ? cu : { ...cu, default_model: ra.default_model }));
    setNguoiDung((cu) => (cu === null ? cu : { ...cu, default_model: ra.default_model }));
  }, []);

  const refreshProfile = useCallback(async (): Promise<void> => {
    try {
      const ra = await api.toiLaAi();
      setHoSo(ra);
      setProfileReadAt(Date.now());
    } catch {
      // Giu `hoSo` cu — xem docstring `Phien.refreshProfile`.
    }
  }, []);

  return {
    nguoiDung,
    hoSo,
    profileReadAt,
    dangTai,
    biKhoa,
    loi,
    dangNhap,
    dangXuat,
    datModelMacDinh,
    refreshProfile,
  };
}
