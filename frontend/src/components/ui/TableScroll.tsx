import type { ReactNode } from "react";

/**
 * Vo cuon ngang cho moi `<table>` — T-3.10.
 *
 * KH tham chieu: §2.3 (S8) · tasks.md T-3.10 (Cam bay ③).
 *
 * Bang so cua `/admin` rong hon 375 px ngay tu hom nay (bang chi phi co bay
 * cot), va T-3.12 se them ba bang nua. Mot bang tran ra ngoai la ca trang cuon
 * ngang — dung thu DoD `scrollWidth <= innerWidth` bat. Nen bang cuon TRONG vo
 * nay, con trang thi dung yen.
 *
 * Hai chi tiet, ca hai vi ban phim chu khong vi chuot:
 *
 *   - `tabIndex={0}`: mot vung cuon duoc ma khong nhan tieu diem thi nguoi
 *     dung ban phim khong cuon duoc no (luat `scrollable-region-focusable` cua
 *     axe, muc `serious` — tuc dung muc lam `make audit` do).
 *   - `role="region"` + `aria-label`: vung nhan tieu diem phai co ten, khong
 *     thi trinh doc chi doc "vung cuon" ma khong noi la bang nao.
 *
 * `whitespace-nowrap` tren bang: de trinh duyet ep cot xuong dong o tung chu
 * thi bang "vua" 375 px nhung so tien bi bo doi — cuon ngang tot hon doc sai.
 */
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className="max-w-full overflow-x-auto [&>table]:whitespace-nowrap"
    >
      {children}
    </div>
  );
}
