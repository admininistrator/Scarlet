import type { IconNode } from "lucide";
import { Spring } from "morphicons";
import { MorphIcon } from "morphicons/react";
import { useEffect, useRef } from "react";
import {
  ACCOUNT_MENU_NUDGE_PX,
  SPRINGS,
  useReducedMotion,
  type SpringRole,
} from "../../lib/motion";

/**
 * Icon bien hinh — T-S.9, NQ-117.
 *
 * KH tham chieu: §24.2b·S10 · tasks.md T-S.9, T-3.9 · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOI `MorphIcon` DI QUA DAY — KHONG MOT CHO NAO IMPORT `morphicons`    ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Tu ban 1.4.2, `morphicons` mac dinh BO QUA cai dat giam chuyen dong cua he
 * dieu hanh (`reducedMotion="never"`) — trai T-3.9. Wrapper nay khoa
 * `reducedMotion="user"`: nguoi dung xin giam thi icon doi tuc thi, khong
 * mot khung hinh trung gian nao. Prop ay KHONG mo ra cho noi goi, de khong ai
 * vo tinh tat no. Cac task sau co dong DoD
 * `grep "from \"morphicons" frontend/src | grep -v components/ui/Icon.tsx` → rong.
 *
 * `icon` la DU LIEU cua goi `lucide` (`import { Menu } from "lucide"`), khong
 * phai component cua `lucide-react` — `morphicons` chi nhan du lieu.
 *
 * `spring` la VAI TRO chu khong phai con so: thong so song o `lib/motion.ts`
 * (ban T-HD5-v2). Bat buoc, vi thieu no thi thu vien roi ve lo xo mac dinh
 * cua chinh no — mot bo so khong ai trong ban ve chon.
 *
 * Khong `label` ⇒ `aria-hidden` (icon trang tri canh chu, hoac trong mot nut
 * da co `aria-label`); co `label` ⇒ `role="img"` + `<title>`.
 */

type IconProps = {
  icon: IconNode;
  spring: SpringRole;
  size?: number;
  strokeWidth?: number;
  className?: string;
  label?: string;
};

export function Icon({ icon, spring, size, strokeWidth, className, label }: IconProps) {
  return (
    <MorphIcon
      icon={icon}
      spring={SPRINGS[spring]}
      reducedMotion="user"
      size={size}
      strokeWidth={strokeWidth}
      className={className}
      label={label}
    />
  );
}

/**
 * Icon KHONG BAO GIO doi hinh — T-S.10 (nut cho, dong han muc, khay tep).
 *
 * Van la `MorphIcon` (S10: moi icon di qua `morphicons` + du lieu `lucide`),
 * nhung khong nhan `spring`: `icon` o day la mot hang so, nen khong co lo xo
 * nao chay de ma chon. Icon nao doi hinh theo trang thai thi dung `Icon` o
 * tren — va khi ay bat buoc khai vai tro lo xo.
 */
export function StaticIcon({ icon, size, strokeWidth, className, label }: Omit<IconProps, "spring">) {
  return (
    <MorphIcon
      icon={icon}
      reducedMotion="user"
      size={size}
      strokeWidth={strokeWidth}
      className={className}
      label={label}
    />
  );
}

/** Buoc dau tien cua lo xo khi chua co moc thoi gian truoc — mot khung 60 Hz. */
const FIRST_STEP_S = 1 / 60;
/** Tab vua quay lai sau khi bi an: khong de lo xo nhay mot buoc dai hon the nay. */
const MAX_STEP_S = 1 / 15;

/**
 * Icon NHICH khi muc menu cua no dang duoc chon — T-S.12, menu tai khoan.
 *
 * KH tham chieu: §24.2b·S10 · ban T-HD5-v2 muc 6 · NQ-117, NQ-128 a.
 *
 * Ban ve: *"Re chuot tren tung muc: icon nhich 3 px theo lo xo gentle"* —
 * icon GIU HINH (khong co icon dich nao de bien hinh), nhich
 * `ACCOUNT_MENU_NUDGE_PX` sang phai theo lo xo `accountMenuItemHover`, roi
 * muc thi ve cho cu. Lo xo la `Spring` cua chinh `morphicons` — cung bo may,
 * cung `{ stiffness, damping }` voi icon bien hinh — nen no song o file nay,
 * noi DUY NHAT import `morphicons`.
 *
 * "Dang duoc chon" = muc `role="menuitem"` gan nhat dang giu tieu diem. Menu
 * cua Radix dat tieu diem vao muc khi re chuot (`pointermove`) lan khi di
 * bang mui ten, va tra tieu diem ve khung menu khi chuot roi muc — nen nghe
 * `focus`/`blur` cua muc la nghe ca chuot lan ban phim (khung demo cua ban ve
 * cung nhich khi focus). Khong ai phai truyen trang thai xuong: muc thuong va
 * muc cho (`ComingSoon`) dung chung icon nay.
 *
 * Giam chuyen dong ⇒ KHONG nhich, khong xin mot khung hinh nao.
 *
 * Doi huong giua chung (re qua lai nhanh) giu van toc: `Spring` chuan hoa `x`
 * tu 0 toi 1 tren tung doan, nen van toc doi ra px/s cua doan cu roi chia cho
 * do dai doan moi — icon khong khung lai giua duong.
 */
export function NudgeIcon({
  icon,
  size,
  className,
}: {
  icon: IconNode;
  size?: number;
  className?: string;
}) {
  const hostRef = useRef<HTMLSpanElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    const host = hostRef.current;
    const item = host?.closest<HTMLElement>('[role="menuitem"]') ?? null;
    if (host === null || item === null || reduced) {
      return undefined;
    }
    const spring = new Spring();
    spring.config(SPRINGS.accountMenuItemHover.stiffness, SPRINGS.accountMenuItemHover.damping);
    let from = 0;
    let to = 0;
    let offset = 0;
    let frame = 0;
    let last: number | null = null;

    const paint = () => {
      host.style.transform = offset === 0 ? "" : `translateX(${offset}px)`;
    };
    const tick = (now: number) => {
      const dt =
        last === null ? FIRST_STEP_S : Math.min(Math.max((now - last) / 1000, 0), MAX_STEP_S);
      last = now;
      const settled = spring.step(dt);
      offset = settled ? to : from + (to - from) * spring.x;
      paint();
      frame = settled ? 0 : requestAnimationFrame(tick);
    };
    const moveTo = (target: number) => {
      if (target === to) {
        return;
      }
      const velocity = spring.v * (to - from);
      from = offset;
      to = target;
      if (to === from) {
        return;
      }
      spring.v = velocity / (to - from);
      spring.start();
      if (frame === 0) {
        last = null;
        frame = requestAnimationFrame(tick);
      }
    };
    const onFocus = () => moveTo(ACCOUNT_MENU_NUDGE_PX);
    const onBlur = () => moveTo(0);

    item.addEventListener("focus", onFocus);
    item.addEventListener("blur", onBlur);
    // Muc da giu tieu diem truoc khi effect nay chay (menu vua mo bang ban phim).
    if (document.activeElement === item) {
      onFocus();
    }
    return () => {
      item.removeEventListener("focus", onFocus);
      item.removeEventListener("blur", onBlur);
      if (frame !== 0) {
        cancelAnimationFrame(frame);
      }
      host.style.transform = "";
    };
  }, [reduced]);

  return (
    <span ref={hostRef} className="inline-flex shrink-0">
      <StaticIcon icon={icon} size={size} className={className} />
    </span>
  );
}
