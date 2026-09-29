import { CircleAlert, Eye, EyeOff, LoaderCircle, type IconNode } from "lucide";
import { useState } from "react";
import type { ReactNode, Ref } from "react";

import { t } from "../../lib/i18n";
import { StaticIcon } from "../ui/Icon";
import { Turnstile, turnstileEnabled } from "./Turnstile";
import type { TurnstileForm } from "./useTurnstile";

/**
 * Nhung manh dung chung cua cac form auth — T-S.16, ban T-HD8 (`Field.tsx`,
 * `SubmitButton.tsx`, `TurnstileSlot.tsx` "rut gon").
 *
 * KH tham chieu: §11.6, UC-01 · tasks.md T-S.16 Cam bay ①② · NQ-131.
 *
 * ── Khong co `minLength`, va KHONG co con so mat khau nao ────────────────
 *
 * Ban ve: *"Goi y chi noi 'mat khau dai'. Do dai toi thieu do may chu kiem
 * [...] O khong co minLength: neu co, trinh duyet se tu hien con so trong bong
 * bong loi."* (cung ly do B-215 con mo). `required` va `type="email"` thi GIU:
 * bong bong cua chung khong mang con so nao, va bo chung la bo mot lop kiem ma
 * T-3.1b dang co — task nay chi trinh bay, khong doi luong.
 */

/** Tieu de form + dong dan (man Quen mat khau). */
export function AuthTitle({ title, lead }: { title: string; lead?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h1 className="text-2xl font-semibold tracking-[-0.01em]">{title}</h1>
      {lead !== undefined && <p className="text-base text-muted text-pretty">{lead}</p>}
    </div>
  );
}

type FieldProps = {
  id: string;
  label: string;
  type: "email" | "password";
  autoComplete: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  hint?: string;
  /** Loi THAY dung cho goi y — khong day nhung thu ben duoi (ban ve 2c). */
  error?: string | null;
  readOnly?: boolean;
  inputRef?: Ref<HTMLInputElement>;
  /** Lien ket ngay duoi o — "Quen mat khau?" cua man Dang nhap. */
  after?: ReactNode;
};

export function AuthField({
  id,
  label,
  type,
  autoComplete,
  value,
  onChange,
  onBlur,
  hint,
  error,
  readOnly,
  inputRef,
  after,
}: FieldProps) {
  const [shown, setShown] = useState(false);
  const descId = `${id}-desc`;
  const isPassword = type === "password";
  const hasError = error !== undefined && error !== null;
  const desc = hasError ? error : hint;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          ref={inputRef}
          type={isPassword && shown ? "text" : type}
          required
          autoComplete={autoComplete}
          value={value}
          readOnly={readOnly}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          aria-invalid={hasError ? true : undefined}
          aria-describedby={desc !== undefined ? descId : undefined}
          className={`motion-control h-touch w-full rounded-md border border-border-strong bg-surface-panel pl-3 text-input text-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring aria-invalid:border-danger aria-invalid:ring-1 aria-invalid:ring-danger ${isPassword ? "pr-12" : "pr-3"}`}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShown((v) => !v)}
            aria-pressed={shown}
            aria-controls={id}
            aria-label={t("auth.hienMatKhau")}
            className="motion-icon absolute inset-y-0 right-0 grid w-touch place-items-center rounded-md text-muted hover:text-foreground"
          >
            <StaticIcon icon={shown ? EyeOff : Eye} size={20} />
          </button>
        )}
      </div>
      {/*
        `role="alert"` chi o LOI: ban ve dat loi thay cho goi y ma khong mot
        vung thong bao nao, nen trinh doc man hinh se im lang sau lan bam Gui.
        Goi y thi khong — no dung yen tu luc mo man.
      */}
      {desc !== undefined && (
        <p
          id={descId}
          role={hasError ? "alert" : undefined}
          className={`text-sm text-pretty ${hasError ? "text-danger-text" : "text-muted"}`}
        >
          {desc}
        </p>
      )}
      {after}
    </div>
  );
}

/**
 * Nut chinh cua form. KHONG gan `.control-disabled`: dang gui phai doc duoc
 * "Dang xu ly…", khong mo di (ban ve, the "Dang gui"). Con tro `not-allowed`
 * den tu luat `:disabled` cua theme.
 */
export function SubmitButton({ busy, label }: { busy: boolean; label: string }) {
  return (
    <>
      <button
        type="submit"
        disabled={busy}
        className="motion-press flex min-h-touch w-full items-center justify-center gap-2 rounded-md bg-accent px-5 text-body font-semibold text-accent-foreground enabled:hover:bg-accent-hover"
      >
        {busy && <StaticIcon icon={LoaderCircle} size={18} className="motion-spin" />}
        {busy ? t("auth.dangXuLy") : label}
      </button>
      <span role="status" className="sr-only">
        {busy ? t("auth.dangXuLy") : ""}
      </span>
    </>
  );
}

/** Hop loi / canh bao o dau form. Han muc la `warning`: cho la het (1d). */
export function FormAlert({
  tone,
  icon = CircleAlert,
  children,
}: {
  tone: "danger" | "warning";
  icon?: IconNode;
  children: ReactNode;
}) {
  return (
    <div
      role="alert"
      data-tone={tone}
      className="flex gap-2.5 rounded-md px-3.5 py-3 text-base data-[tone=danger]:bg-danger-subtle data-[tone=danger]:text-danger-text data-[tone=warning]:bg-warning-subtle data-[tone=warning]:text-warning-text"
    >
      <StaticIcon icon={icon} size={18} className="mt-0.5 shrink-0" />
      <span className="text-pretty">{children}</span>
    </div>
  );
}

/**
 * Khung Turnstile CO DINH 336 × 71 tu lan ve dau — T-S.16 Cam bay ②.
 *
 * *"Turnstile loai invisible chiem mot khoang 336×71 px truoc khi hien huy
 * hieu (T-3.1b): bo cuc phai chua cho, khong nhay."* Khung giu nguyen kich
 * thuoc du widget chua tai, da hien hay loi; huy hieu ve vao dung khung do.
 * Ban ve tinh long the desktop 400 − 2 × 32 = 336, nhung the co VIEN 1 px moi
 * ben nen long do duoc la 334 (Chrome, T-S.16) — `max-w-full` giu khung o 334,
 * van rong hon widget 300 px cua Cloudflare. Mobile 343 thi du 336 (B-316).
 *
 * Loi nam DUOI khung, mot `role="alert"`: loi nap script (`auth.turnstileLoi`)
 * thang loi cua form, vi khi script khong tai thi "hay hoan tat o xac minh"
 * khong con lam duoc.
 *
 * Site key rong thi KHONG co khung (T-3.1b Cam bay ②), nhung loi van phai
 * hien: `.env` thieu `TURNSTILE_SITE_KEY` ma backend co secret thi moi lan gui
 * la mot `400 TURNSTILE_FAILED`, va giau cau ay cung voi khung la mot nut bam
 * khong co chuyen gi xay ra.
 */
export function TurnstileSlot({
  turnstile,
  error,
}: {
  turnstile: TurnstileForm;
  error: string | null;
}) {
  const [loadFailed, setLoadFailed] = useState(false);
  const enabled = turnstileEnabled();
  const text = loadFailed ? t("auth.turnstileLoi") : error;
  if (!enabled && text === null) {
    return null;
  }
  return (
    <div className="flex flex-col gap-1.5">
      {enabled && (
        <Turnstile
          onToken={turnstile.onToken}
          ref={turnstile.ref}
          onLoadError={() => setLoadFailed(true)}
          className="h-turnstile-h w-turnstile max-w-full overflow-hidden"
        />
      )}
      {text !== null && (
        <p role="alert" className="text-sm text-danger-text">
          {text}
        </p>
      )}
    </div>
  );
}
