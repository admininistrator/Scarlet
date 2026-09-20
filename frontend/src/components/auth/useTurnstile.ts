import { useCallback, useRef, useState } from "react";
import type { Ref } from "react";

import { turnstileDaBat, type TurnstileHandle } from "./Turnstile";

/**
 * Trang thai cua mot widget Turnstile trong mot form — T-3.1b.
 *
 * KH tham chieu: §11.6 · tasks.md T-2.6, T-3.1b Cam bay ②.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOT HOOK CHU KHONG HAI BAN CHEP                                       ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * §11.6 dat captcha o DUNG hai form — dang ky va quen mat khau — va ca hai
 * phai lam y het bon viec: giu token, giu `ref` de `reset()`, chan lan gui
 * khi widget bat ma chua co token, va goi `reset()` sau MOI response loi.
 *
 * Viec thu tu la viec de quen nhat, va docstring cua `Turnstile.tsx` da noi
 * ro vi sao: Cloudflare tieu token ngay lan `siteverify` dau tien, nen sau
 * mot `422` vi mat khau qua yeu, lan gui thu hai chac chan `400
 * TURNSTILE_FAILED` — va trieu chung doc thanh "captcha hong" chu khong phai
 * "mat khau qua yeu". Hai ban chep cua bon viec ay la hai co hoi de mot ben
 * quen viec thu tu.
 */
export interface TurnstileForm {
  /** `null` khi chua co token, khi token het han, hoac khi widget tat. */
  token: string | null;
  /** Gan vao `<Turnstile ref={...}>`. */
  ref: Ref<TurnstileHandle>;
  /** Gan vao `<Turnstile onToken={...}>`. */
  onToken: (token: string | null) => void;
  /**
   * Widget dang BAT ma chua co token — form phai chan lan gui lai.
   *
   * `false` khi `VITE_TURNSTILE_SITE_KEY` rong (Cam bay ②): khong co khoa thi
   * khong co widget, va bat nguoi dung hoan tat mot o khong ton tai la khoa
   * ho ra khoi trang dang ky tren may dev.
   */
  thieuToken: boolean;
  /** Xin mot token moi. Goi sau MOI response loi — xem docstring tren. */
  reset: () => void;
}

export function useTurnstile(): TurnstileForm {
  const [token, setToken] = useState<string | null>(null);
  const ref = useRef<TurnstileHandle>(null);

  const reset = useCallback(() => {
    setToken(null);
    ref.current?.reset();
  }, []);

  return {
    token,
    ref,
    onToken: setToken,
    thieuToken: turnstileDaBat() && token === null,
    reset,
  };
}
