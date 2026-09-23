/**
 * Danh muc model cua FE — T-3.6.
 *
 * KH tham chieu: §9.3, §18.3, UC-05, RR-5 · tasks.md T-3.6 (Viec can lam
 * dong 6, Cam bay ② va ③), B-192.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MO PICKER KHONG GOI API — DAY LA CAU TRA LOI CHO "VIEC CAN LAM" ⑥     ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `GET /models` duoc goi o DUNG ba thoi diem, khong hon:
 *
 *   1. **Luc mount** — mot lan cho ca phien lam viec.
 *   2. **Khi mang ve** (`online`) — cung ly le B-115 da dung cho `useChat`:
 *      mo trang trong luc mat mang khong duoc phep ket vinh vien.
 *   3. **Khi nguoi dung bam nut lam moi** trong picker — hanh dong RO RANG
 *      cua ho, dung theo ban T-HD4.
 *
 * KHONG goi khi mo dropdown. B-192 do gia cua thoi quen ay o `/admin/system`:
 * rieng chang 9Router mat 854 / 806 / 941 ms ba lan lien tiep, va picker mo
 * nhieu hon man He thong rat nhieu lan. T-3.6 do lai trong chinh phien nay:
 * mot luot do that la ~757 ms, con doc tu bo nho cua backend la ~3 ms.
 *
 * Backend con mot lop nho rieng (`core/provider_health.py`, TTL 30 s) nen hai
 * lop chong nhau — co y: lop o day chan so LAN GOI, lop kia chan so LUOT DO.
 * Hai tab cung bam lam moi thi van chi mot lan ai do that su di hoi 9Router.
 *
 * ── `loadedAt` la thoi diem FE DOC, khong phai thoi diem backend DO ─────────
 *
 * Ban T-HD4 doi mot moc gio o dau danh sach ("Trang thai kiem luc 14:32").
 * Con so o day la luc `GET /models` **tra ve**, va no co the moi hon luc do
 * that toi 30 giay (TTL cua backend). Chenh lech ay khong duoc giau: no la
 * ly do `refresh()` ton tai va la ly do mot lan bam lam moi co the khong doi
 * gi ca. Dua them mot truong `checked_at` qua API se xoa duoc chenh lech,
 * nhung do la mot truong thu ba them vao §18.3 — vung cam (A10), nen chua
 * lam. Xem Backlog.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api, type ModelOut } from "../../lib/api";

export interface ModelCatalog {
  /** Thu tu giu nguyen thu tu `order` cua catalog (§9.2) — khong sap lai. */
  models: ModelOut[];
  /** Luc `GET /models` tra ve lan gan nhat. `null` = chua lan nao xong. */
  loadedAt: Date | null;
  /** Lan doc dau tien chua xong. */
  loading: boolean;
  /** Mot lan lam moi TUONG MINH dang chay — nut quay, danh sach van bam duoc. */
  refreshing: boolean;
  /** Loi cua lan doc gan nhat, hoac `null`. */
  error: string | null;
  refresh: () => Promise<void>;
}

export function useModels(): ModelCatalog {
  const [models, setModels] = useState<ModelOut[]>([]);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /*
    Component co the thao giua luc `GET /models` con bay (nguoi dung dieu
    huong sang `/admin`). Ghi state sau do la mot canh bao cua React va —
    te hon — la mot `dangLamMoi` ket o `true` neu ho quay lai.
  */
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async (explicit: boolean): Promise<void> => {
    if (explicit) {
      setRefreshing(true);
    }
    try {
      const output = await api.listModels();
      if (!mountedRef.current) {
        return;
      }
      setModels(output);
      setLoadedAt(new Date());
      setError(null);
    } catch (e: unknown) {
      if (!mountedRef.current) {
        return;
      }
      /*
        `/models` khong doi danh tinh (router nay dung ngoai moi danh sach
        phan quyen — §11.1 cho `pending_approval` chon model duoc), nen mot
        that bai o day la ha tang chu khong phai "chua dang nhap".

        Danh sach CU o lai tren man hinh: mot lan lam moi hong khong duoc
        xoa nhung gi dang dung duoc. Do la cung mot luat ma ban T-HD4 dat
        cho luc dang lam moi — "danh sach khong bi che, khong skeleton".
      */
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mountedRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  const refresh = useCallback(() => load(true), [load]);

  useEffect(() => {
    void load(false);

    function handleOnline(): void {
      void load(false);
    }

    window.addEventListener("online", handleOnline);
    return () => {
      window.removeEventListener("online", handleOnline);
    };
  }, [load]);

  return { models, loadedAt, loading, refreshing, error, refresh };
}
