import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { t } from "../../lib/i18n";

/**
 * Khung render artifact — T-5.6 (ADR-10, §14.3). Noi dung toi sau bang
 * `postMessage` (T-5.7); `src` chi la trang khung tinh cua origin phu theo
 * `kind` (`/react`, `/mermaid` co runtime — T-5.8), khong id, khong query.
 *
 * Ba lop chong nhau, moi lop chan mot thu ma hai lop kia khong chan:
 *   1. origin phu (`VITE_ARTIFACTS_BASE_URL`, anh xa tu `ARTIFACTS_BASE_URL`)
 *   2. `sandbox` KHONG co `allow-same-origin` ⇒ script chay voi origin `null`
 *   3. CSP cua origin phu (Nginx, Phu luc D) ⇒ `connect-src 'none'`
 *
 * `allow-same-origin` cung `allow-scripts` la vo hieu hoa toan bo sandbox
 * (§14.3). "Iframe khong gui cookie / `localStorage` nem" la HANG RAO, khong
 * phai loi can sua. `scripts/test_artifact_origin.mjs` doc chuoi duoi day tu
 * chinh file nay — sua mot cho la S12 do ngay.
 */
export const ARTIFACT_SANDBOX = "allow-scripts allow-popups allow-forms";

/**
 * Bat tay voi trang khung (`backend/app/api/artifacts_render.py`, T-5.7):
 * khung gui `ready {watchdog}` khi da gan listener ⇒ cha gui `render` (KHONG
 * dua vao `onload`) ⇒ khung tra `rendered` hoac `error {message}`. Watchdog
 * (C32, T-5.8): cha gui `ping` moi nhip, khung tra `alive` (khong `pong` —
 * `check-identifiers` do).
 */
export const ARTIFACT_MESSAGE = {
  ready: "ready",
  render: "render",
  rendered: "rendered",
  error: "error",
  ping: "ping",
  alive: "alive",
} as const;

export type ArtifactFrameResult = { type: "rendered" } | { type: "error"; message: string } | { type: "stalled" };

type Props = {
  title: string;
  kind: string;
  content: string;
  onResult?: (result: ArtifactFrameResult) => void;
  /** Khung quanh noi dung (T-5.5, ban T-HD6) — do panel quyet. */
  className?: string;
};

type Watchdog = { pingIntervalMs: number; timeoutMs: number };

/**
 * Hai nhip cua `config/artifact_runtime.json` (A3) — trang khung doc tep luc
 * phuc vu va gui trong `ready`, nen sua tep khong can build lai FE.
 */
function readWatchdog(data: object): Watchdog | null {
  const value = "watchdog" in data ? data.watchdog : null;
  if (typeof value !== "object" || value === null) return null;
  const ping = "ping_interval_ms" in value ? value.ping_interval_ms : null;
  const timeout = "timeout_ms" in value ? value.timeout_ms : null;
  const positive = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n > 0;
  return positive(ping) && positive(timeout) ? { pingIntervalMs: ping, timeoutMs: timeout } : null;
}

/**
 * Doi noi dung (doi phien ban, T-5.9) ⇒ iframe MOI qua `key`, khong `render`
 * lan hai vao khung cu: state va timer cua script cu chet cung iframe cu
 * (khung cung tu xoa listener sau `render` dau tien).
 */
export function ArtifactFrame(props: Props) {
  return <Frame key={`${props.kind}\u0000${props.content}`} {...props} />;
}

function Frame({ title, kind, content, onResult, className }: Props) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const onResultRef = useRef(onResult);
  const [stalled, setStalled] = useState(false);
  useEffect(() => {
    onResultRef.current = onResult;
  });

  // Layout effect: gan listener cung task voi lan commit chen iframe ⇒ `ready`
  // khong the toi truoc listener.
  useLayoutEffect(() => {
    let timer: number | undefined;
    // Dem NHIP chu khong doc dong ho: tab nen bi giam nhip thi watchdog cham
    // lai theo, khong huy khung oan vi mot lan `setInterval` den tre.
    let silentMs = 0;
    let dead = false;
    function onMessage(event: MessageEvent) {
      // Chi tin dung `contentWindow` cua iframe nay. KHONG loc `event.origin`:
      // khung sandbox co origin `null`, so voi `ARTIFACTS_BASE_URL` la khong
      // bao gio nhan duoc `ready`.
      const target = frameRef.current?.contentWindow;
      if (dead || !target || event.source !== target) return;
      const data: unknown = event.data;
      if (typeof data !== "object" || data === null || !("type" in data)) return;
      silentMs = 0;
      if (data.type === ARTIFACT_MESSAGE.ready) {
        const watchdog = readWatchdog(data);
        if (watchdog === null) {
          // Khong co watchdog thi khong chay code do model sinh.
          onResultRef.current?.({ type: "error", message: t("artifact.panel.noWatchdog") });
          return;
        }
        // `"*"`: origin `null` khong dat lam targetOrigin duoc. Gui thang toi
        // `contentWindow` cua chinh iframe nay — khong ai khac nhan.
        target.postMessage({ type: ARTIFACT_MESSAGE.render, kind, content }, "*");
        if (timer !== undefined) return;
        timer = window.setInterval(() => {
          silentMs += watchdog.pingIntervalMs;
          if (silentMs >= watchdog.timeoutMs) {
            // C32: huy iframe (go khoi DOM), bao "stalled" (treo); tra loi muon bi bo qua.
            dead = true;
            window.clearInterval(timer);
            setStalled(true);
            onResultRef.current?.({ type: "stalled" });
            return;
          }
          target.postMessage({ type: ARTIFACT_MESSAGE.ping }, "*");
        }, watchdog.pingIntervalMs);
      } else if (data.type === ARTIFACT_MESSAGE.rendered) {
        onResultRef.current?.({ type: "rendered" });
      } else if (data.type === ARTIFACT_MESSAGE.error) {
        const message = "message" in data ? String(data.message) : "";
        onResultRef.current?.({ type: "error", message });
      }
    }
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      window.clearInterval(timer);
    };
  }, [kind, content]);

  if (stalled) {
    return null;
  }
  return (
    <iframe
      ref={frameRef}
      src={`${import.meta.env.VITE_ARTIFACTS_BASE_URL}/${encodeURIComponent(kind)}`}
      sandbox={ARTIFACT_SANDBOX}
      title={title}
      className={className}
    />
  );
}
