import { CircleCheck, LogOut, type IconNode } from "lucide";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { StaticIcon } from "../ui/Icon";

/**
 * Man thong bao cua auth — T-S.16, ban T-HD8 (`AuthMessage`).
 *
 * KH tham chieu: §11.1, §11.5, UC-01 · tasks.md T-S.16.
 *
 * Mot khuon cho moi man KHONG phai form: kiem tra hop thu, da doi mat khau,
 * bon trang thai cua `/verify-email`, cho duyet, bi khoa. Thu tu trong ban ve
 * co dinh: icon · tieu de + than · canh bao · dong trang thai · nut chinh ·
 * nut phu · ghi chu — nguoi goi xep `children` theo dung thu tu ay.
 */
export function AuthMessage({
  icon,
  tone = "neutral",
  spinning = false,
  title,
  body,
  children,
}: {
  icon: IconNode;
  tone?: "neutral" | "success";
  /** "Dang xac thuc email…": icon quay, `aria-busy`, khong co nut (5a). */
  spinning?: boolean;
  title: string;
  body?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div aria-busy={spinning || undefined} className="flex flex-col gap-5">
      <span
        aria-hidden="true"
        data-tone={tone}
        className="grid size-12 place-items-center rounded-full bg-surface-hover text-foreground data-[tone=success]:bg-success-subtle data-[tone=success]:text-success-text"
      >
        <StaticIcon icon={icon} size={22} className={spinning ? "motion-spin" : undefined} />
      </span>
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-[-0.01em] text-pretty">{title}</h1>
        {body}
      </div>
      {children}
    </div>
  );
}

/** Mot doan than. `strong` = chu nen dam (email cua nguoi dung). */
export function MessageText({ children, strong = false }: { children: ReactNode; strong?: boolean }) {
  return (
    <p
      className={`text-body leading-6 wrap-anywhere text-pretty ${strong ? "font-semibold text-foreground" : "text-muted"}`}
    >
      {children}
    </p>
  );
}

/** Dong trang thai xanh — "Da gui thu moi" (5e). */
export function MessageStatus({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="motion-enter flex items-center gap-1.5 text-base font-medium text-success-text">
      <StaticIcon icon={CircleCheck} size={16} />
      {children}
    </p>
  );
}

/** Nut chinh dang lien ket — "Dang nhap" sau khi doi mat khau (4d). */
export function PrimaryLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="motion-press flex min-h-touch items-center justify-center rounded-md bg-accent text-body font-semibold text-accent-foreground no-underline hover:bg-accent-hover hover:text-accent-foreground hover:no-underline"
    >
      {children}
    </Link>
  );
}

/** Lien ket phu can trai — "Quay lai dang nhap", "Mo man cho duyet". */
export function SecondaryLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="inline-flex min-h-touch items-center self-start text-base font-medium">
      {children}
    </Link>
  );
}

/** Nut phu "Dang xuat" (6, 7) — vien, icon `log-out`. */
export function LogoutButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="motion-press inline-flex min-h-touch items-center gap-2 self-start rounded-md border border-border-strong bg-transparent px-4 text-base font-medium text-foreground hover:bg-surface-hover"
    >
      <StaticIcon icon={LogOut} size={18} />
      {label}
    </button>
  );
}

/** Ghi chu cuoi — "Khong thay thu? Xem ca muc Thu rac." */
export function MessageNote({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted">{children}</p>;
}
