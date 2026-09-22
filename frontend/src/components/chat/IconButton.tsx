/**
 * Nut vuong 44 x 44 mang mot ky tu — ban T-HD3, dung o hai cho.
 *
 * Hai cho do la `BranchNav` (`‹ n/m ›`, T-1.14/T-3.8) va hang nut duoi cau
 * tra loi (`NutDuoiCauTraLoi`, T-3.7). Ban thiet ke ve chung bang **mot**
 * component, va o day cung vay: 44 px la con so cua danh sach kiem T-HD3
 * ("moi nut trong artboard 375 px do duoc ≥ 44 px"), nen mot ban chep thu hai
 * la mot cho de no tut xuong 40 mà khong ai thay.
 *
 * `pressed` la trang thai BAT/TAT cua Thich va Khong thich. No di ra DOM bang
 * `aria-pressed`, tuc screen reader doc duoc "da bam" — mau nen khong noi
 * duoc dieu do. `undefined` (khong phai `false`) o nhung nut khong co trang
 * thai bat/tat, de React bo han thuoc tinh thay vi khai `aria-pressed="false"`
 * cho mot mui ten dieu huong.
 */
export function IconButton({
  label,
  glyph,
  onClick,
  pressed,
  disabled,
  title,
}: {
  label: string;
  glyph: string;
  onClick: () => void;
  pressed?: boolean;
  disabled?: boolean;
  /** Chu hien khi ro chuot, khi no can noi nhieu hon `label`. */
  title?: string;
}) {
  return (
    <button
      type="button"
      // `() => onClick()` chu khong `onClick={onClick}`: React truyen
      // `MouseEvent` lam tham so dau, nen mot handler khai `() => void` van
      // NHAN mot doi so luc chay — va `onThuLai(messageId, modelId?)` o ben
      // goi se doc ca su kien ay thanh `modelId`. Mot lop bao ve mot dong.
      onClick={() => onClick()}
      disabled={disabled}
      aria-label={label}
      title={title ?? label}
      aria-pressed={pressed}
      className={
        pressed === true
          ? "grid size-touch place-items-center rounded-md border border-accent bg-accent-subtle text-accent-text motion-control"
          : "grid size-touch place-items-center rounded-md border border-transparent text-muted hover:bg-surface-hover disabled:text-disabled-foreground motion-control"
      }
    >
      <span aria-hidden="true" className="text-lg">
        {glyph}
      </span>
    </button>
  );
}
