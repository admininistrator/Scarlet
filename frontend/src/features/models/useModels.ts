/**
 * Danh muc model cua FE — T-3.6, T-S.4.
 *
 * KH tham chieu: §9.3, §18.3, §24.2b·S5, UC-05, RR-5 · tasks.md T-3.6 (Viec
 * can lam dong 6, Cam bay ② va ③), T-S.4 · B-192 · NQ-113.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MO PICKER CHI GOI API KHI DU LIEU DA CU — NOI CO DIEU KIEN (NQ-113)   ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `GET /models` duoc goi o DUNG bon thoi diem, khong hon:
 *
 *   1. **Luc mount** — mot lan cho ca phien lam viec.
 *   2. **Khi mang ve** (`online`) — cung ly le B-115 da dung cho `useChat`:
 *      mo trang trong luc mat mang khong duoc phep ket vinh vien.
 *   3. **Khi nguoi dung bam nut lam moi** trong picker — hanh dong RO RANG
 *      cua ho, dung theo ban T-HD4.
 *   4. **Khi mo picker ma `checked_at` da cu hon `stale_after_s`** (T-S.4) —
 *      hoi lai NGAM: khong quay nut, danh sach cu van bam duoc trong luc cho.
 *
 * Cam bay ② cua T-3.6 ("dung goi `GET /models` moi lan mo dropdown") duoc
 * noi, khong bo: B-192 do mot luot do 9Router ~850 ms, nhung tu T-S.4 backend
 * KHONG BAO GIO do trong request — no doc luot do nen gan nhat (~3 ms). Lan
 * goi thu 4 chi xay ra khi du lieu dang cam da cu hon mot nhip do nen, tuc
 * khi backend da co (hoac sap co) cau tra loi moi hon.
 *
 * ── `checkedAt` la thoi diem backend DO, khong phai luc FE DOC ─────────────
 *
 * Ban T-HD4 doi mot moc gio o dau danh sach ("Trang thai kiem luc 14:32").
 * T-3.6 chi co luc `GET /models` tra ve, co the moi hon luc do that toi mot
 * nhip; T-S.4 them `checked_at` (S14) nen moc gio nay la gio do that.
 * `checked_at` giong nhau o moi phan tu (mot luot do cho ca danh sach), va
 * `null` khi backend vua khoi dong ma luot do dau chua xong.
 *
 * `stale_after_s` di cung response chu khong la mot hang so o day: nhip do la
 * mot bien `.env` cua backend (A3) — FE chep con so ay la hai nguon su that.
 * So `checked_at` voi dong ho cua trinh duyet: lech gio vai giay chi doi mot
 * lan hoi som hoac muon, va lan hoi ay chi doc bo nho cua backend.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api, type ModelOut } from "../../lib/api";

export interface ModelCatalog {
  /** Thu tu giu nguyen thu tu `order` cua catalog (§9.2) — khong sap lai. */
  models: ModelOut[];
  /** Luc backend DO luot trang thai dang hien. `null` = chua biet. */
  checkedAt: Date | null;
  /** Lan doc dau tien chua xong. */
  loading: boolean;
  /** Mot lan lam moi TUONG MINH dang chay — nut quay, danh sach van bam duoc. */
  refreshing: boolean;
  /** Loi cua lan doc gan nhat, hoac `null`. */
  error: string | null;
  refresh: () => Promise<void>;
  /** Goi khi mo picker: hoi lai NGAM neu `checkedAt` da cu (T-S.4). */
  refreshIfStale: () => void;
}

/** `checked_at` cua response — giong nhau o moi phan tu, xem docstring module. */
function checkedAtOf(models: ModelOut[]): Date | null {
  const raw = models[0]?.checked_at ?? null;
  return raw === null ? null : new Date(raw);
}

export function useModels(): ModelCatalog {
  const [models, setModels] = useState<ModelOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /*
    Component co the thao giua luc `GET /models` con bay (nguoi dung dieu
    huong sang `/admin`). Ghi state sau do la mot canh bao cua React va —
    te hon — la mot `refreshing` ket o `true` neu ho quay lai.
  */
  const mountedRef = useRef(true);
  /*
    Mo/dong picker lien tuc trong luc mot lan hoi con bay khong duoc sinh
    them lan hoi: moi lan mo chi hoi khi KHONG co lan nao dang bay.
  */
  const inFlightRef = useRef(false);
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
    inFlightRef.current = true;
    try {
      const output = await api.listModels();
      if (!mountedRef.current) {
        return;
      }
      setModels(output);
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
      inFlightRef.current = false;
      if (mountedRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  const refresh = useCallback(() => load(true), [load]);

  const refreshIfStale = useCallback((): void => {
    if (inFlightRef.current) {
      return;
    }
    /*
      Chua co moc nao (`checked_at: null`, hoac lan doc dau hong nen danh
      sach rong) cung la cu: lan mo picker la luc nguoi dung can danh sach,
      va lan hoi nay re.
    */
    const at = checkedAtOf(models);
    const staleAfterS = models[0]?.stale_after_s;
    const stale =
      at === null || staleAfterS === undefined || Date.now() - at.getTime() > staleAfterS * 1000;
    if (stale) {
      void load(false);
    }
  }, [models, load]);

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

  return {
    models,
    checkedAt: checkedAtOf(models),
    loading,
    refreshing,
    error,
    refresh,
    refreshIfStale,
  };
}
