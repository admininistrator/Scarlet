/**
 * Router TOI THIEU cua T-2.19 — ba duong, khong mot phu thuoc nao.
 *
 * KH tham chieu: §16.3, §23 · tasks.md T-2.19, T-3.1.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO KHONG CAI `react-router`                                       ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * T-3.1 ("Khung app: router, layout shell, error boundary, trang 404/500")
 * SO HUU lua chon router. Cai mot thu vien dinh tuyen o T-2.19 la quyet ho
 * T-3.1 mot quyet dinh kien truc bang mot dong `package.json`, va quyet no o
 * dung cho khong ai doc lai — cho mot man hinh ma chinh task viet "chua can
 * dep". Nen o day la ba ham va mot `useSyncExternalStore`: du cho `/admin`
 * hien va an, khong du de ai tuong day la router cua san pham.
 *
 * Khi T-3.1 toi, xoa ca file nay; `duongDan()` va `dieuHuong()` la toan bo be
 * mat can thay the.
 */

import { useSyncExternalStore } from "react";

/** Man quan tri cua §16.3. */
export const DUONG_ADMIN = "/admin";
/** Form dang nhap toi thieu cua T-2.19. */
export const DUONG_DANG_NHAP = "/dang-nhap";
/** Man chat tho cua T-1.14. */
export const DUONG_GOC = "/";

/**
 * Cac ben dang nghe `useDuongDan`.
 *
 * `history.pushState` KHONG ban `popstate` — do la hanh vi cua chinh trinh
 * duyet, khong phai mot thieu sot o day — nen mot lan `dieuHuong()` phai tu
 * danh thuc React. Quen cho nay thi URL doi ma man hinh dung im, tuc dung
 * trieu chung ma nguoi doc se di tim trong component thay vi trong router.
 */
const nguoiNghe = new Set<() => void>();

function dangKy(goiLai: () => void): () => void {
  nguoiNghe.add(goiLai);
  window.addEventListener("popstate", goiLai);
  return () => {
    nguoiNghe.delete(goiLai);
    window.removeEventListener("popstate", goiLai);
  };
}

function docDuongDan(): string {
  return window.location.pathname;
}

/** Duong dan hien tai, cap nhat theo ca `popstate` lan `dieuHuong()`. */
export function useDuongDan(): string {
  return useSyncExternalStore(dangKy, docDuongDan, () => DUONG_GOC);
}

/**
 * Doi duong dan ma khong tai lai trang.
 *
 * Di thang ra neu dich TRUNG duong dan hien tai: `dieuHuong()` duoc goi tu
 * trong `useEffect` cua App (chuyen huong khi khong du quyen), va mot
 * `pushState` vo dieu kien o do vua chat day lich su trinh duyet bang nhung
 * ban sao giong het nhau, vua tu ban mot lan render nua.
 */
export function dieuHuong(duong: string): void {
  if (docDuongDan() === duong) {
    return;
  }
  window.history.pushState(null, "", duong);
  for (const goiLai of nguoiNghe) {
    goiLai();
  }
}
