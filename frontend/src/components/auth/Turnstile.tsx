/**
 * Widget Cloudflare Turnstile — nua FE cua T-2.6 (KH §11.6, RR-1).
 *
 * KH tham chieu: §11.6, RR-1 · CLAUDE.md A3 · tasks.md T-2.6, T-H5.
 *
 * Cap voi `backend/app/core/turnstile.py`: component nay sinh ra chuoi
 * `cf-turnstile-response`, backend gui chuoi do sang `siteverify`. Doc
 * docstring cua module Python kia truoc khi sua file nay — moi quyet dinh o
 * day deu la he qua cua mot quyet dinh ben ay.
 *
 * ── CHUA CO MAN HINH NAO DUNG NO, VA DO LA DUNG PHAM VI ────────────────────
 *
 * FE hom nay khong co form dang ky lan form quen mat khau: `features/auth/`
 * con trong, va §7 (Phase 3) cung KHONG co task nao dung hai man hinh do
 * (B-138). "Viec can lam" cua T-2.6 ghi "widget o FE", nen phan giao o day la
 * mot component dung duoc ngay khi man hinh ra doi — cung tien le voi template
 * `reset_password.*` ma T-2.2 dung san cho T-2.5.
 *
 * ── TOKEN CHI DUNG DUOC MOT LAN ────────────────────────────────────────────
 *
 * Cloudflare tieu token ngay lan `siteverify` dau tien, va no het han sau
 * 300 s. Nghia la sau BAT KY response loi nao — 400 vi captcha, 422 vi mat
 * khau qua yeu, 429 vi han muc — nguoi goi phai `reset()` roi lay token moi.
 * Khong lam vay thi lan gui thu hai chac chan `400 TURNSTILE_FAILED`, va
 * trieu chung se doc thanh "captcha hong" chu khong phai "mat khau qua yeu".
 * Do la ly do component nay lo `reset` ra ngoai qua `ref`.
 *
 * ── SITE KEY RONG => KHONG HIEN GI ─────────────────────────────────────────
 *
 * Khop voi `TURNSTILE_SECRET` rong o backend (bo qua kiem tra, chi dev): khong
 * co khoa thi khong co widget, va `onToken(null)` cho caller biet de gui
 * request khong kem token. Hien mot o xac minh chet la cach chac chan nhat de
 * khoa nguoi dung ra khoi trang dang ky tren may dev.
 */

import { useCallback, useEffect, useImperativeHandle, useRef } from "react";
import type { Ref } from "react";

/**
 * Duong dan script cua Cloudflare. Mot HANG, khong phai mot nut van.
 *
 * A3 cam literal "URL provider" trong code, va nua backend cua cap nay
 * (`TURNSTILE_VERIFY_URL`) da di vao `.env` dung theo luat do. Nua nay o lai
 * trong code vi no khong phai thu doi duoc theo moi truong: `?render=explicit`
 * la mot phan cua hop dong goi ham `window.turnstile.render()` ben duoi, nen
 * mot gia tri khac khong phai "cau hinh khac" ma la "component nay hong".
 * Cung lap luan voi `"type": "function"` cua `llm/client.py::ToolCall.to_wire`.
 */
const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

/** Khoa cong khai, do docker-compose anh xa tu `TURNSTILE_SITE_KEY`. */
const SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY ?? "";

interface TurnstileOptions {
  sitekey: string;
  callback: (token: string) => void;
  "error-callback": () => void;
  "expired-callback": () => void;
  theme: "auto" | "light" | "dark";
}

interface TurnstileApi {
  render: (el: HTMLElement, options: TurnstileOptions) => string;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

/** Mot lan nap script cho ca trang, du co bao nhieu widget. */
let scriptLoading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.turnstile !== undefined) {
    return Promise.resolve();
  }
  if (scriptLoading !== null) {
    return scriptLoading;
  }
  scriptLoading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // Xoa promise da hong: khong xoa thi moi lan mount sau deu nhan lai dung
      // that bai cu, ke ca khi mang da co lai.
      scriptLoading = null;
      reject(new Error("khong nap duoc script Turnstile"));
    };
    document.head.appendChild(script);
  });
  return scriptLoading;
}

export interface TurnstileHandle {
  /** Xin mot token moi. Goi sau MOI response loi — xem docstring module. */
  reset: () => void;
}

interface Props {
  /** `null` khi chua co token, khi token het han, hoac khi widget tat. */
  onToken: (token: string | null) => void;
  ref?: Ref<TurnstileHandle>;
  className?: string;
  /**
   * Script cua Cloudflare khong nap duoc. T-S.16 (ban T-HD8): cau loi nam
   * DUOI khung chu khong thay cho khung — khung giu nguyen 336 × 71 du widget
   * chua tai, da hien hay loi — nen chu la viec cua `TurnstileSlot`.
   */
  onLoadError?: () => void;
}

/** Turnstile co bat khong — dung de an ca khoi captcha trong form. */
export function turnstileEnabled(): boolean {
  return SITE_KEY.trim() !== "";
}

export function Turnstile({ onToken, ref, className, onLoadError }: Props) {
  const oRef = useRef<HTMLDivElement | null>(null);
  const widgetRef = useRef<string | null>(null);

  // `onToken` giu trong ref: caller thuong truyen mot arrow function moi o moi
  // lan render, va de no vao mang phu thuoc cua useEffect se thao/dung lai
  // widget sau moi lan go phim trong form.
  const onTokenRef = useRef(onToken);
  const onLoadErrorRef = useRef(onLoadError);
  useEffect(() => {
    onTokenRef.current = onToken;
    onLoadErrorRef.current = onLoadError;
  }, [onToken, onLoadError]);

  const reset = useCallback(() => {
    if (widgetRef.current !== null && window.turnstile !== undefined) {
      window.turnstile.reset(widgetRef.current);
      onTokenRef.current(null);
    }
  }, []);

  useImperativeHandle(ref, () => ({ reset }), [reset]);

  useEffect(() => {
    if (!turnstileEnabled()) {
      onTokenRef.current(null);
      return;
    }

    let alive = true;
    loadScript()
      .then(() => {
        // StrictMode cua dev mount/unmount hai lan: khong co co nay thi lan
        // nap xong cua vong doi DA CHET van render mot widget vao mot the div
        // khong con trong cay.
        if (!alive || oRef.current === null || window.turnstile === undefined) {
          return;
        }
        widgetRef.current = window.turnstile.render(oRef.current, {
          sitekey: SITE_KEY,
          callback: (token: string) => onTokenRef.current(token),
          "error-callback": () => onTokenRef.current(null),
          "expired-callback": () => onTokenRef.current(null),
          theme: "auto",
        });
      })
      .catch(() => {
        if (alive) {
          onLoadErrorRef.current?.();
          onTokenRef.current(null);
        }
      });

    return () => {
      alive = false;
      if (widgetRef.current !== null && window.turnstile !== undefined) {
        window.turnstile.remove(widgetRef.current);
        widgetRef.current = null;
      }
    };
  }, []);

  if (!turnstileEnabled()) {
    return null;
  }
  return <div ref={oRef} className={className} />;
}
