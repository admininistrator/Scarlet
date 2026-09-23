import { useId, type ReactNode } from "react";

import { t } from "../../lib/i18n";

/**
 * Bang so cuon ngang TRONG khung — T-3.10, hinh dang cuoi theo T-HD7 (T-3.12).
 *
 * KH tham chieu: §2.3 (S8), §16.3 · tasks.md T-3.10 (Cam bay ③), T-3.12.
 *
 * Ban T-HD7 chon *"khung cuon + cot dau dinh + bong mep phai, khong doi sang
 * card"*: man quan tri de so sanh so theo cot, card pha mat cot va dau thap
 * phan khong con thang hang giua cac nguoi dung. Nen bang cuon TRONG khung
 * nay, con trang thi dung yen (DoD cua T-3.10: khong phan tu nao vuot
 * `0..innerWidth` ngoai vung CO Y cuon ngang).
 *
 * Bon chi tiet, ca bon den tu ban ve hoac tu axe:
 *
 *   - `scroll-frame` (theme.css): bong mep phai bao "con cot" bang HAI lop
 *     nen — lop bong dung yen o mep khung, lop mau nen truot theo noi dung va
 *     che bong khi da cuon toi cuoi. CSS thuan, khong lang nghe `scroll`.
 *   - `tabIndex={0}` + `role="region"` + `aria-label`: vung cuon duoc phai
 *     nhan tieu diem thi nguoi dung ban phim moi cuon duoc bang mui ten (luat
 *     `scrollable-region-focusable` cua axe, muc `serious`), va vung nhan tieu
 *     diem phai co ten.
 *   - `<caption className="sr-only">`: trinh doc noi bang nao, khong hien lai
 *     tieu de da co ngay tren bang.
 *   - Mot dong goi y duoi bang, CHI hien duoi 768 px (`md:sr-only`) — tren
 *     man rong bang thuong vua, va dong chu ay thanh nhieu.
 *
 * `min-w-max` tren bang: de trinh duyet ep cot xuong dong o tung chu thi bang
 * "vua" 375 px nhung so tien bi be doi — cuon ngang tot hon doc sai. Moi cha
 * flex cua khung phai co `min-w-0`, thieu mot cai la trang cuon theo.
 *
 * `relative` tren khung — do duoc o T-3.12, 375 px: nhan `sr-only` cua cot
 * "Thao tac" (cot CUOI, x ≈ 1088) la `position:absolute`, khung khong dinh vi
 * nen no dinh vi theo khung ngoai cung va keo `scrollWidth` cua tai lieu len
 * 1089 trong luc moi phan tu nhin thay deu nam gon trong 375 px. `relative`
 * lam khung thanh khoi chua cua no, va `overflow` cua khung cat no nhu moi o
 * khac.
 */
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  const hintId = useId();
  return (
    <section className="flex min-w-0 flex-col gap-2">
      <div
        role="region"
        aria-label={label}
        aria-describedby={hintId}
        tabIndex={0}
        className="scroll-frame relative rounded-lg border border-border"
      >
        <table className="w-full min-w-max border-collapse text-sm">
          <caption className="sr-only">{label}</caption>
          {children}
        </table>
      </div>
      <p id={hintId} className="text-xs text-muted md:sr-only">
        {t("admin.scrollHint")}
      </p>
    </section>
  );
}
