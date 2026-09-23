import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../../lib/api";

/**
 * Nap mot tai nguyen cho mot man quan tri / cai dat — T-3.12.
 *
 * KH tham chieu: §16.3 · tasks.md T-2.19 (luat 3 cua `useQuanTri` cu), T-3.12
 * (B-192, DoD dong 1 va 4).
 *
 * Sau man, moi man mot hai loi goi — mot hook nho chung thay vi sau ban chep
 * cua cung ba `useState` (du lieu, loi, dang tai). Ba luat:
 *
 *   1. **Loi KHONG bi nuot** va KHONG xoa du lieu cu: lam tuoi hong thi man
 *      hinh giu bang dang co va hien loi canh no. Mot bang rong doc y het
 *      "khong co ai", tuc la noi sai.
 *   2. **Chi cau tra loi MOI NHAT duoc ghi.** Hai lan nap chong nhau (doi 7
 *      ngay → 30 ngay → 7 ngay nhanh tay) thi response ve cham cua lan cu
 *      khong duoc de len response cua lan moi.
 *   3. **Mo man MOT lan = MOT request.** `StrictMode` (dev) chay effect hai
 *      lan: mount → go → mount lai tren CUNG mot instance. Khong gop thi moi
 *      man goi moi endpoint hai lan — do dung vao hai phep dem cua DoD T-3.12
 *      ("dem so cau SELECT ⇒ 1", "dem so lan goi `/admin/system`"), va do la
 *      mot con so sai ve san pham chu khong phai ve dev server. Lan nap cua
 *      effect dung lai promise dang bay neu `load` khong doi; `reload()` goi
 *      tuong minh thi LUON goi moi.
 *
 * `load` phai on dinh (boc `useCallback` o ben goi): doi `load` la nap lai.
 */
export interface Resource<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => Promise<void>;
}

export function toApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, "HTTP_ERROR", String(e));
}

export function useResource<T>(load: () => Promise<T>): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);
  const inflight = useRef<{ load: () => Promise<T>; promise: Promise<T> } | null>(null);

  const run = useCallback(
    async (reuse: boolean): Promise<void> => {
      const turn = ++latest.current;
      setLoading(true);
      let promise: Promise<T>;
      if (reuse && inflight.current?.load === load) {
        promise = inflight.current.promise;
      } else {
        promise = load();
        inflight.current = { load, promise };
      }
      try {
        const value = await promise;
        if (turn === latest.current) {
          setData(value);
          setError(null);
        }
      } catch (e) {
        if (turn === latest.current) {
          setError(toApiError(e));
        }
      } finally {
        if (inflight.current?.promise === promise) {
          inflight.current = null;
        }
        if (turn === latest.current) {
          setLoading(false);
        }
      }
    },
    [load],
  );

  const reload = useCallback(() => run(false), [run]);

  useEffect(() => {
    void run(true);
    return () => {
      // Man bi go (hoac StrictMode go thu): lan nap dang bay khong duoc ghi
      // vao state qua luot nay nua — lan mount ke tiep tu nhan lai promise.
      latest.current += 1;
    };
  }, [run]);

  return { data, error, loading, reload };
}
