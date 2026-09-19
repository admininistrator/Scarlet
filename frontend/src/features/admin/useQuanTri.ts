/**
 * Day noi giua `api.ts` va man `/admin` — T-2.19, §16.3.
 *
 * KH tham chieu: §16.3, §18.5, §11.1, §10.5, §9.5, C16 · tasks.md T-2.16,
 * T-2.19, B-176, B-178.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BA LUAT                                                               ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * **1. Sau moi nut bam doi trang thai, DOC LAI danh sach tu server.**
 * `POST /admin/users/{id}/approve` tra ve dung hang vua doi, nen cat no ra
 * khoi mang o FE la rat cam do. Nhung bang "cho duyet" duoc LOC theo
 * `status=pending_approval` — mot hang vua roi khoi tap do phai bien mat, va
 * mot hang khac co the vua roi VAO no (nguoi thu hai bam verify email trong
 * luc admin dang nhin). FE tu sua mang chi dung cho nua truoc cua cau chuyen.
 *
 * **2. `nguon` mac dinh la `system`, khong phai "moi nguon"** — B-178. Con so
 * lon nhat tren man "Chi phi" phai la con so S13 dem doi chieu voi hoa don
 * provider duoc; tien BYOK la tien cua nguoi khac (§10.5) va cong no vao do
 * la lam hoa don phinh len dung bang phan minh khong tra.
 *
 * **3. Loi cua `/admin/*` KHONG duoc nuot.** `401`/`403` o day co nghia la
 * server tu choi — va do la ca diem cua §16.3 (*"moi endpoint kiem lai quyen
 * phia server"*). Hien no ra nguyen van thay vi hien mot bang rong, vi mot
 * bang rong doc y het "khong co ai cho duyet".
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  api,
  type AdminUserRa,
  type ChiPhiRa,
  type HanhDongUser,
  type NapCatalogRa,
  type NguonKhoa,
} from "../../lib/api";

/** Mac dinh cua man "Chi phi" — xem luat 2. */
export const NGUON_MAC_DINH: NguonKhoa = "system";

export interface QuanTri {
  choDuyet: AdminUserRa[];
  chiPhi: ChiPhiRa | null;
  nguon: NguonKhoa | null;
  dangTai: boolean;
  dangBan: boolean;
  loi: ApiError | null;
  ketQuaNapCatalog: NapCatalogRa | null;
  doiNguon: (nguon: NguonKhoa | null) => void;
  doiTrangThai: (userId: string, hanhDong: HanhDongUser) => Promise<void>;
  napLaiCatalog: () => Promise<void>;
  lamTuoi: () => Promise<void>;
}

export function useQuanTri(): QuanTri {
  const [choDuyet, setChoDuyet] = useState<AdminUserRa[]>([]);
  const [chiPhi, setChiPhi] = useState<ChiPhiRa | null>(null);
  const [nguon, setNguon] = useState<NguonKhoa | null>(NGUON_MAC_DINH);
  const [dangTai, setDangTai] = useState(true);
  const [dangBan, setDangBan] = useState(false);
  const [loi, setLoi] = useState<ApiError | null>(null);
  const [ketQuaNapCatalog, setKetQuaNapCatalog] = useState<NapCatalogRa | null>(null);

  const bat = useCallback((e: unknown): void => {
    setLoi(e instanceof ApiError ? e : new ApiError(0, "HTTP_ERROR", String(e)));
  }, []);

  const docChoDuyet = useCallback(async (): Promise<void> => {
    setChoDuyet((await api.quanTriDanhSachUser("pending_approval")).users);
  }, []);

  const docChiPhi = useCallback(async (nguonDoc: NguonKhoa | null): Promise<void> => {
    setChiPhi(await api.quanTriChiPhi(nguonDoc));
  }, []);

  // Hai loi goi song song: chung khong phu thuoc nhau, va man hinh chi day du
  // khi ca hai ve. `Promise.all` chu khong `await` noi tiep — noi tiep nghia
  // la bang chi phi doi bang cho duyet xong moi bat dau.
  const lamTuoi = useCallback(async (): Promise<void> => {
    setLoi(null);
    try {
      await Promise.all([docChoDuyet(), docChiPhi(nguon)]);
    } catch (e) {
      bat(e);
    }
  }, [bat, docChoDuyet, docChiPhi, nguon]);

  useEffect(() => {
    let conGan = true;
    void (async () => {
      setLoi(null);
      try {
        await Promise.all([docChoDuyet(), docChiPhi(nguon)]);
      } catch (e) {
        if (conGan) {
          bat(e);
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
  }, [bat, docChoDuyet, docChiPhi, nguon]);

  const doiTrangThai = useCallback(
    async (userId: string, hanhDong: HanhDongUser): Promise<void> => {
      setDangBan(true);
      setLoi(null);
      try {
        await api.quanTriDoiTrangThai(userId, hanhDong);
        // Luat 1 — doc lai ca danh sach, khong tu cat hang vua doi.
        await docChoDuyet();
      } catch (e) {
        bat(e);
      } finally {
        setDangBan(false);
      }
    },
    [bat, docChoDuyet],
  );

  const napLaiCatalog = useCallback(async (): Promise<void> => {
    setDangBan(true);
    setLoi(null);
    try {
      setKetQuaNapCatalog(await api.quanTriNapCatalog());
    } catch (e) {
      bat(e);
    } finally {
      setDangBan(false);
    }
  }, [bat]);

  return {
    choDuyet,
    chiPhi,
    nguon,
    dangTai,
    dangBan,
    loi,
    ketQuaNapCatalog,
    doiNguon: setNguon,
    doiTrangThai,
    napLaiCatalog,
    lamTuoi,
  };
}
