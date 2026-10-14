import * as Dialog from "@radix-ui/react-dialog";
import { Check, CircleAlert, Copy, LoaderCircle, RotateCcw, TriangleAlert, X } from "lucide";
import { useCallback, useEffect, useId, useRef, useState, type RefObject } from "react";

import { ApiError, api, type ShareLink } from "../../lib/api";
import { copyText } from "../../lib/clipboard";
import { type TextKey, t } from "../../lib/i18n";
import { newKey } from "../../lib/idempotency";
import { ISLAND_COMPACT_QUERY, readDurationMs } from "../../lib/motion";
import { useMediaQuery } from "../../lib/viewport";
import { Icon, StaticIcon } from "../ui/Icon";

/**
 * Hop thoai Chia se — T-8.2, ban T-HD12 (`ShareDialog.tsx`).
 *
 * KH tham chieu: UC-11 dong 1, ADR-14, R15, §16.1, A8 (§11.4) · NQ-149.
 *
 *   ≥ 640  dialog giua man, rong `--spacing-dialog`; < 640 sheet day (loi Model Picker).
 *
 * ── Mot lan mo = MOT POST = mot khoa ───────────────────────────────────────
 *
 * Moi lan mo la mot anh chup moi + link moi (ADR-14), nen khoa
 * `Idempotency-Key` sinh LUC MO; Thu lai giu khoa (server nha khoa khi response
 * loi — `core/idempotency.py`). POST chay tu su kien mo chu khong tu effect:
 * StrictMode ban doi effect (B-260) se thanh hai POST cung khoa, cai sau dung
 * `409 IN_PROGRESS`. Response ve sau khi da dong / mo lai (khoa khac) bi bo.
 *
 * Ban ve goi `navigator.clipboard` thang; o day la `copyText` — co loi lui
 * ngoai secure context (T-3.7, Cam bay ③).
 */

type ShareState =
  | { status: "creating" }
  | { status: "ready"; link: ShareLink }
  | { status: "error"; code: string };

/** Moi ma mot cau; ma khac va mat mang roi ve cau chung. */
const SHARE_ERROR_KEY: Record<string, TextKey> = {
  GENERATION_IN_PROGRESS: "share.error.generating",
  CONVERSATION_EMPTY: "share.error.empty",
  SHARE_STORAGE_UNAVAILABLE: "share.error.storage",
};

export function useShareLink(conversationId: string) {
  const [state, setState] = useState<ShareState | null>(null);
  const keyRef = useRef<string | null>(null);

  const send = useCallback(() => {
    const key = keyRef.current;
    if (key === null) {
      return;
    }
    setState({ status: "creating" });
    api.createShare(conversationId, key).then(
      (link) => keyRef.current === key && setState({ status: "ready", link }),
      (e: unknown) =>
        keyRef.current === key && setState({ status: "error", code: e instanceof ApiError ? e.code : "" }),
    );
  }, [conversationId]);

  const open = useCallback(() => {
    keyRef.current = newKey();
    send();
  }, [send]);

  const close = useCallback(() => {
    keyRef.current = null;
    setState(null);
  }, []);

  return { state, open, close, retry: send };
}

const ICON_BUTTON =
  "motion-press grid size-touch shrink-0 place-items-center rounded-md text-muted hover:bg-surface-hover hover:text-foreground";
const SECONDARY_BUTTON =
  "motion-press inline-flex min-h-touch shrink-0 items-center justify-center gap-2 rounded-md border border-border-strong px-4 text-base font-medium text-foreground hover:bg-surface-hover";

export function ShareDialog({
  state,
  onClose,
  onRetry,
  returnFocusRef,
}: {
  /** `null` = dong. */
  state: ShareState | null;
  onClose: () => void;
  onRetry: () => void;
  /**
   * Dong ⇒ tieu diem ve day (nut "⋯"). Muc menu da mo hop thoai bien mat cung
   * menu, nen mac dinh cua Radix (tra ve phan tu truoc khi mo) roi vao `body`.
   */
  returnFocusRef: RefObject<HTMLElement | null>;
}) {
  const isCompact = useMediaQuery(ISLAND_COMPACT_QUERY);
  const titleId = useId();
  const descId = useId();

  return (
    <Dialog.Root open={state !== null} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="motion-scrim fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-labelledby={titleId}
          aria-describedby={descId}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            returnFocusRef.current?.focus();
          }}
          className={
            isCompact
              ? "motion-sheet fixed inset-x-0 bottom-(--keyboard-inset) z-50 flex max-h-sheet-max flex-col overflow-y-auto rounded-t-xl bg-surface-panel px-gutter pb-[calc(var(--spacing-gutter)_+_env(safe-area-inset-bottom))] text-foreground shadow-popover"
              : "motion-panel fixed top-1/2 left-1/2 z-50 flex w-[min(var(--spacing-dialog),calc(100vw_-_2*var(--spacing-gutter)))] -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl bg-surface-panel p-6 text-foreground shadow-popover"
          }
        >
          {isCompact ? (
            <div className="flex shrink-0 justify-center pt-2">
              <span aria-hidden="true" className="h-1 w-grabber rounded-full bg-border-strong" />
            </div>
          ) : null}
          <div className={`flex items-start gap-2 ${isCompact ? "pt-2" : ""}`}>
            <Dialog.Title id={titleId} className="m-0 min-w-0 flex-1 pt-2.5 text-lg leading-snug font-semibold">
              {t("share.title")}
            </Dialog.Title>
            <Dialog.Close aria-label={t("a11y.closeDialog")} className={`${ICON_BUTTON} -mt-1.5 -mr-2`}>
              <StaticIcon icon={X} size={20} />
            </Dialog.Close>
          </div>

          <div id={descId} className="mt-1 flex flex-col gap-1 text-sm leading-relaxed text-pretty text-muted">
            <p className="m-0">{t("share.snapshotNote")}</p>
            <p className="m-0">{t("share.publicNote")}</p>
          </div>

          <div className="mt-5">
            {state?.status === "ready" ? (
              <ReadyLink link={state.link} />
            ) : state?.status === "error" ? (
              <div className="flex flex-col items-start gap-3">
                <p role="alert" className="motion-enter m-0 inline-flex items-start gap-2 text-sm leading-relaxed text-danger-text">
                  <StaticIcon icon={CircleAlert} size={16} className="mt-0.5 shrink-0" />
                  {t(SHARE_ERROR_KEY[state.code] ?? "share.error.generic")}
                </p>
                <button type="button" onClick={onRetry} className={SECONDARY_BUTTON}>
                  <StaticIcon icon={RotateCcw} size={18} />
                  {t("share.retry")}
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <div aria-hidden="true" className="motion-pulse h-touch rounded-md bg-surface-code" />
                <p role="status" className="m-0 inline-flex min-h-6 items-center gap-2 text-sm text-muted">
                  <StaticIcon icon={LoaderCircle} size={16} className="motion-spin shrink-0" />
                  {t("share.creating")}
                </p>
              </div>
            )}
          </div>

          <p className="mt-4 mb-0 inline-flex items-start gap-2 text-sm leading-relaxed text-warning-text">
            <StaticIcon icon={TriangleAlert} size={16} className="mt-0.5 shrink-0" />
            {t("share.irrevocable")}
          </p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ReadyLink({ link }: { link: ShareLink }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const labelId = useId();

  useEffect(() => {
    if (copy !== "copied") {
      return undefined;
    }
    // `--duration-copied` la hen gio, khong ve 0 khi reduced-motion (theme.css, khoi SHARE).
    const id = window.setTimeout(() => setCopy("idle"), readDurationMs("--duration-copied"));
    return () => window.clearTimeout(id);
  }, [copy]);

  const copyLink = async () => {
    if (await copyText(link.url)) {
      setCopy("copied");
      return;
    }
    inputRef.current?.focus();
    inputRef.current?.select();
    setCopy("failed");
  };
  const isCopied = copy === "copied";

  return (
    <div className="flex flex-col gap-2">
      <span id={labelId} className="text-sm font-medium text-foreground">
        {t("share.linkLabel")}
      </span>
      <div className="flex min-w-0 items-center gap-2">
        <input
          ref={inputRef}
          readOnly
          value={link.url}
          aria-labelledby={labelId}
          onFocus={(e) => e.currentTarget.select()}
          className="motion-control h-touch min-w-0 flex-1 rounded-md border border-border-strong bg-background px-3 font-mono text-sm text-foreground"
        />
        <button
          type="button"
          onClick={() => void copyLink()}
          data-toggle={isCopied ? "on" : undefined}
          className={`motion-toggle inline-flex h-touch min-w-touch shrink-0 items-center justify-center gap-2 rounded-md border px-4 text-base font-semibold ${
            isCopied
              ? "border-accent bg-accent-subtle text-accent-text"
              : "border-transparent bg-accent text-accent-foreground hover:bg-accent-hover"
          }`}
        >
          <Icon icon={isCopied ? Check : Copy} spring="shareCopy" size={18} />
          {/* Hai chu xep chong trong mot o ⇒ nut rong bang chu dai hon, khong co gian khi doi. */}
          <span className="grid">
            <span aria-hidden="true" className="invisible col-start-1 row-start-1">
              {t("share.copy")}
            </span>
            <span aria-hidden="true" className="invisible col-start-1 row-start-1">
              {t("share.copied")}
            </span>
            <span key={isCopied ? "copied" : "copy"} className="motion-label-in col-start-1 row-start-1 text-center">
              {isCopied ? t("share.copied") : t("share.copy")}
            </span>
          </span>
        </button>
      </div>
      {/* Doi chu tren nut khong duoc doc lai khi tieu diem van o nut ⇒ bao rieng. */}
      <span role="status" className="sr-only">
        {isCopied ? t("share.copied") : ""}
      </span>
      {copy === "failed" ? (
        <p role="alert" className="motion-enter m-0 text-sm leading-relaxed text-danger-text">
          {t("share.copyFailed")}
        </p>
      ) : null}
    </div>
  );
}
