import * as Dialog from "@radix-ui/react-dialog";
import { PanelRight, PanelRightClose, X } from "lucide";
import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { t } from "../../lib/i18n";
import { ISLAND_COMPACT_QUERY } from "../../lib/motion";
import { useMediaQuery } from "../../lib/viewport";
import { plainText } from "../chat/BubbleExtras";
import { Hint } from "../chat/Hint";
import { StaticIcon } from "../ui/Icon";

/**
 * Panel phai cua man chat — T-5.4: khung, dong/mo, keo rong, toan man hinh
 * duoi 640 px. Chua co ban ve (T-HD6 ve tren khung nay): chi token DA CO —
 * `--spacing-panel-right/min/max`, `--shadow-panel`, `.motion-panel`.
 *
 *   ≥ 640 px  `<aside>` canh cot chat (cot chat co lai); tay nam o mep trai
 *   < 640 px  `Dialog` cua Radix phu kin man hinh — cung primitive voi drawer /
 *             sheet cua T-3.10: bay tieu diem, khoa cuon phia sau, Esc
 *
 * Mo / dong song o `ChatScreen`; nut o dao (`PanelToggle`). Dong tu TRONG panel
 * (Esc, nut X) ⇒ `ChatScreen` xin dao tra tieu diem ve nut mo (`focusRequest`):
 * nut ay co the dang nam trong lop `inert` cua dao (B-323 ④).
 */

export const ARTIFACT_PANEL_ID = "artifact-panel";
export const PANEL_WIDTH_STORAGE_KEY = "artifact.panelWidth";
/** Mot lan bam mui ten tren tay nam. */
const KEY_STEP_PX = 16;

/** Phan cua artifact panel can — hinh dang `PathArtifact` / `GET /artifacts/{id}` (T-5.2a). */
export interface PanelArtifact {
  title: string;
  kind: string;
  version: number;
  content: string | null;
}

/** Day tu `ChatScreen` qua dao toi nut. */
export interface PanelBinding {
  open: boolean;
  onToggle: () => void;
  /** Tang moi lan panel dong tu ben trong ⇒ dao dua tieu diem ve nut mo. */
  focusRequest: number;
}

type Limits = { initial: number; min: number; max: number };

/** Token spacing (rem hoac px) → px. */
function readSpacingPx(token: string): number {
  const style = getComputedStyle(document.documentElement);
  const raw = style.getPropertyValue(token).trim();
  const value = Number.parseFloat(raw);
  return raw.endsWith("rem") ? value * Number.parseFloat(style.fontSize) : value;
}

function readLimits(): Limits {
  return {
    initial: readSpacingPx("--spacing-panel-right"),
    min: readSpacingPx("--spacing-panel-min"),
    max: readSpacingPx("--spacing-panel-max"),
  };
}

const clamp = (width: number, { min, max }: Limits) => Math.min(max, Math.max(min, width));

/** Be rong da keo — tien ich tung may, loi theme cua T-0.10: hong ⇒ mac dinh. */
function savedWidth(limits: Limits): number {
  try {
    const saved = Number.parseFloat(localStorage.getItem(PANEL_WIDTH_STORAGE_KEY) ?? "");
    return Number.isFinite(saved) ? clamp(saved, limits) : limits.initial;
  } catch {
    return limits.initial;
  }
}

function saveWidth(width: number): void {
  try {
    localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(width));
  } catch {
    // che do rieng tu co the chan localStorage — be rong chi song toi lan dong
  }
}

/** Nut dong / mo panel trong dao (thanh mo, va chan sidebar doc khi neo hai ben). */
export function PanelToggle({ binding, className }: { binding: PanelBinding; className: string }) {
  const label = t("artifact.panel.label");
  return (
    <Hint label={label} side="bottom">
      <button
        type="button"
        aria-label={label}
        aria-expanded={binding.open}
        aria-controls={ARTIFACT_PANEL_ID}
        onClick={binding.onToggle}
        className={className}
      >
        <StaticIcon icon={binding.open ? PanelRightClose : PanelRight} size={18} />
      </button>
    </Hint>
  );
}

export function ArtifactPanel({
  open,
  onClose,
  artifact,
}: {
  open: boolean;
  onClose: () => void;
  /** T-5.3 do du lieu; T-5.5 ve theo `kind`. `null` ⇒ trang thai trong. */
  artifact: PanelArtifact | null;
}) {
  const fullscreen = useMediaQuery(ISLAND_COMPACT_QUERY);
  if (!open) {
    return null;
  }
  if (fullscreen) {
    return (
      <Dialog.Root open onOpenChange={(next) => !next && onClose()}>
        <Dialog.Portal>
          <Dialog.Content
            id={ARTIFACT_PANEL_ID}
            aria-describedby={undefined}
            // Tieu diem ve nut mo do dao lo (`focusRequest`), khong phai Radix.
            onCloseAutoFocus={(e) => e.preventDefault()}
            className="motion-panel fixed inset-0 z-60 flex flex-col bg-surface-panel text-foreground"
          >
            <PanelBody
              artifact={artifact}
              onClose={onClose}
              title={(text) => <Dialog.Title className={TITLE}>{text}</Dialog.Title>}
            />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }
  return <SidePanel artifact={artifact} onClose={onClose} />;
}

const TITLE = "min-w-0 flex-1 truncate text-base font-semibold";

function SidePanel({ artifact, onClose }: { artifact: PanelArtifact | null; onClose: () => void }) {
  const [limits] = useState(readLimits);
  const [width, setWidth] = useState(() => savedWidth(limits));
  // Diem bat dau keo. Handler pointer gan bang prop React (khong `addEventListener`
  // trong effect): StrictMode chay effect hai lan se gan hai listener (B-260).
  const drag = useRef<{ x: number; width: number } | null>(null);

  const onHandleKey = (e: KeyboardEvent) => {
    // Panel o mep phai: tay nam sang trai = panel rong ra.
    const delta = e.key === "ArrowLeft" ? KEY_STEP_PX : e.key === "ArrowRight" ? -KEY_STEP_PX : 0;
    if (delta === 0) {
      return;
    }
    e.preventDefault();
    const next = clamp(width + delta, limits);
    setWidth(next);
    saveWidth(next);
  };
  const endDrag = () => {
    if (drag.current !== null) {
      drag.current = null;
      saveWidth(width);
    }
  };

  return (
    <aside
      id={ARTIFACT_PANEL_ID}
      aria-label={t("artifact.panel.label")}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      // So do luc chay (be rong da keo), khong phai mau hay khoang cach co dinh.
      style={{ width }}
      className="motion-panel relative flex h-full min-h-0 shrink-0 flex-col border-l border-border bg-surface-panel text-foreground shadow-panel"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("artifact.panel.resize")}
        aria-valuenow={width}
        aria-valuemin={limits.min}
        aria-valuemax={limits.max}
        tabIndex={0}
        onKeyDown={onHandleKey}
        onPointerDown={(e) => {
          if (e.button !== 0) {
            return;
          }
          e.preventDefault(); // khong boi den chu cua cot chat khi keo
          e.currentTarget.setPointerCapture(e.pointerId);
          drag.current = { x: e.clientX, width };
        }}
        onPointerMove={(e) => {
          const start = drag.current;
          if (start !== null) {
            setWidth(clamp(start.width + start.x - e.clientX, limits));
          }
        }}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        className="motion-control absolute inset-y-0 left-0 z-10 w-3 -translate-x-1/2 cursor-col-resize touch-none hover:bg-surface-hover"
      />
      <PanelBody artifact={artifact} onClose={onClose} title={(text) => <h2 className={TITLE}>{text}</h2>} />
    </aside>
  );
}

function PanelBody({
  artifact,
  onClose,
  title,
}: {
  artifact: PanelArtifact | null;
  onClose: () => void;
  title: (text: string) => ReactNode;
}) {
  // Tieu de do model dat: bo ky tu dieu khien / dao chieu (T-S.15 ②).
  const heading = artifact === null ? "" : plainText(artifact.title);
  return (
    <>
      <div className="flex shrink-0 items-center gap-2 border-b border-border py-1 pr-1 pl-4">
        {title(heading === "" ? t("artifact.panel.label") : heading)}
        {/*
          Khong tooltip: dialog (< 640 px) tu focus nut nay luc mo, tooltip cua
          Radix mo theo focus va la lop tren cung ⇒ Esc dau chi dong tooltip.
        */}
        <button
          type="button"
          aria-label={t("artifact.panel.close")}
          onClick={onClose}
          className="motion-control grid size-touch shrink-0 place-items-center rounded-md text-muted hover:bg-surface-hover hover:text-foreground"
        >
          <StaticIcon icon={X} size={18} />
        </button>
      </div>
      {artifact === null ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-1 p-6 text-center">
          <p className="text-base font-semibold">{t("artifact.panel.empty")}</p>
          <p className="text-sm text-muted">{t("artifact.panel.emptyHint")}</p>
        </div>
      ) : (
        // Cho T-5.5 (ve theo `kind`): tam thoi la chu tran.
        <pre className="min-h-0 flex-1 overflow-auto p-4 text-sm">{artifact.content ?? ""}</pre>
      )}
    </>
  );
}
