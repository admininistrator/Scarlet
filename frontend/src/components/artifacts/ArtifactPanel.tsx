import * as Dialog from "@radix-ui/react-dialog";
import {
  Atom,
  CircleAlert,
  CodeXml,
  Download,
  File,
  FileCode,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  PanelRight,
  PanelRightClose,
  RotateCcw,
  Workflow,
  X,
  type IconNode,
} from "lucide";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import type { PathArtifact } from "../../lib/api";
import { t, type TextKey } from "../../lib/i18n";
import { ISLAND_COMPACT_QUERY } from "../../lib/motion";
import { useMediaQuery } from "../../lib/viewport";
import { plainText } from "../chat/BubbleExtras";
import { Hint } from "../chat/Hint";
import { Markdown } from "../chat/Markdown";
import { highlightLines } from "../chat/highlight";
import { setIslandRightInset, useIslandAnchor } from "../island/islandAnchor";
import { Icon, StaticIcon } from "../ui/Icon";
import { ArtifactFrame } from "./ArtifactFrame";
import { downloadName, extensionFor, languageName, lineCount, mimeFor, resolvePanelLayout } from "./artifactUtils";

/**
 * Panel artifact — khung T-5.4, ve lai theo ban T-HD6 · v1 o T-5.5.
 *
 *   ≥ 640 px  hop noi bo goc (`rounded-panel`, le `--spacing-panel-gap`) neo
 *             mep phai — neo phai thi dung truoc sidebar. Cot chat co lai bang
 *             mot o dem (`motion-push`) khi con cho; het cho thi hop de len
 *             (quy tac 640–1279, `resolvePanelLayout`, B-366). Tay nam nam
 *             NGOAI hop (hop `overflow-hidden` de cat goc).
 *   < 640 px  `Dialog` cua Radix phu kin man hinh (T-5.4, lo drawer T-3.10).
 *
 * Mo / dong song o `ChatScreen`. Nut: thanh dao (neo tren) hoac nut ⑨ goc
 * tren phai cot chat (neo hai ben). Dong tu TRONG panel ⇒ `ChatScreen` xin
 * dao tra tieu diem ve nut mo (`focusRequest`, B-323 ④).
 *
 * Noi dung theo `kind` (T-5.5): `html` ⇒ khung origin phu (ADR-10, T-5.6 /
 * T-5.7); `svg` ⇒ `<img src="blob:">` — SVG KHONG BAO GIO vao DOM cua origin
 * chinh (Q-P5-6); `markdown` ⇒ `Markdown` cua bong bong (ba lop NQ-95, `img`
 * bi chan — B-235); con lai ⇒ ma co so dong (Prism cua `highlight.ts`).
 */

export const ARTIFACT_PANEL_ID = "artifact-panel";
export const PANEL_WIDTH_STORAGE_KEY = "artifact.panelWidth";
/** Mot lan bam mui ten tren tay nam. */
const KEY_STEP_PX = 16;

/** Chay trong khung origin phu (`react`, `mermaid`: runtime CDN cua khung — T-5.8, Q-P5-6). */
const FRAME_KINDS: ReadonlySet<string> = new Set(["html", "react", "mermaid"]);
/** Hai che do Xem truoc / Ma. */
const PREVIEW_KINDS: ReadonlySet<string> = new Set([...FRAME_KINDS, "svg"]);

/** Day tu `ChatScreen` qua dao toi nut. */
export interface PanelBinding {
  open: boolean;
  onToggle: () => void;
  /** Tang moi lan panel dong tu ben trong ⇒ dao dua tieu diem ve nut mo. */
  focusRequest: number;
}

type Limits = { initial: number; min: number; max: number; gap: number; sidebar: number; chatMin: number };

/** Token spacing (rem hoac px) → px. Token vang (jsdom) ⇒ 0. */
function readSpacingPx(token: string): number {
  const style = getComputedStyle(document.documentElement);
  const raw = style.getPropertyValue(token).trim();
  const value = Number.parseFloat(raw);
  return (raw.endsWith("rem") ? value * Number.parseFloat(style.fontSize) : value) || 0;
}

function readLimits(): Limits {
  return {
    initial: readSpacingPx("--spacing-panel-right"),
    min: readSpacingPx("--spacing-panel-min"),
    max: readSpacingPx("--spacing-panel-max"),
    gap: readSpacingPx("--spacing-panel-gap"),
    // Neo hai ben: sidebar doc + le cua dao (cung so `Layout` day noi dung, NQ-136).
    sidebar: readSpacingPx("--spacing-island-gap") + readSpacingPx("--spacing-sidebar"),
    chatMin: readSpacingPx("--spacing-min"),
  };
}

const clamp = (width: number, low: number, high: number) => Math.min(high, Math.max(low, width));

/** Be rong da keo — tien ich tung may, loi theme cua T-0.10: hong ⇒ mac dinh. */
function savedWidth(limits: Limits): number {
  try {
    const saved = Number.parseFloat(localStorage.getItem(PANEL_WIDTH_STORAGE_KEY) ?? "");
    return Number.isFinite(saved) ? clamp(saved, limits.min, limits.max) : limits.initial;
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

function useViewportWidth(): number {
  return useSyncExternalStore(
    (listener) => {
      window.addEventListener("resize", listener);
      return () => window.removeEventListener("resize", listener);
    },
    () => window.innerWidth,
    () => 0,
  );
}

/** Nut dong / mo panel: thanh dao (neo tren) va nut ⑨. Icon bien hinh bang lo xo `panelToggle`. */
export function PanelToggle({ binding, className }: { binding: PanelBinding; className: string }) {
  return (
    <Hint label={t(binding.open ? "artifact.panel.close" : "artifact.panel.open")} side="bottom">
      <button
        type="button"
        aria-label={t("artifact.panel.label")}
        aria-expanded={binding.open}
        aria-controls={ARTIFACT_PANEL_ID}
        onClick={binding.onToggle}
        className={className}
      >
        <Icon icon={binding.open ? PanelRightClose : PanelRight} spring="panelToggle" size={18} />
      </button>
    </Hint>
  );
}

/**
 * Nut ⑨ (ban T-HD6) — dao neo hai ben: goc tren phai COT CHAT (cot chat la
 * `relative`), ngay cho panel moc ra o ca neo trai lan neo phai. Neo tren van
 * dung nut trong thanh dao.
 */
export function ArtifactPanelToggle({ binding }: { binding: PanelBinding }) {
  return (
    <span className="island-glass absolute top-island-gap right-island-gap z-20 grid rounded-full">
      <PanelToggle
        binding={binding}
        className="motion-press grid size-touch place-items-center rounded-full text-foreground hover:bg-glass-hover"
      />
    </span>
  );
}

export function ArtifactPanel({
  open,
  onClose,
  artifact,
}: {
  open: boolean;
  onClose: () => void;
  /** T-5.3 do du lieu (event `artifact` hoac nut "Mo"); `null` ⇒ trang thai trong. */
  artifact: PathArtifact | null;
}) {
  const fullscreen = useMediaQuery(ISLAND_COMPACT_QUERY);
  if (!fullscreen) {
    return <FloatingPanel open={open} onClose={onClose} artifact={artifact} />;
  }
  if (!open) {
    return null;
  }
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
            heading={(text) => <Dialog.Title className={TITLE}>{text}</Dialog.Title>}
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const TITLE = "truncate text-body leading-5 font-semibold";
const ICON_BUTTON =
  "motion-press grid size-touch shrink-0 place-items-center rounded-md text-foreground hover:bg-surface-hover";
const TEXT_BUTTON =
  "motion-press inline-flex min-h-touch shrink-0 items-center gap-1.5 rounded-md px-3 text-sm font-semibold text-foreground hover:bg-surface-hover";
const SECONDARY_BUTTON =
  "motion-press inline-flex min-h-touch shrink-0 items-center gap-1.5 rounded-md border border-border-strong bg-surface-panel px-3.5 text-base font-semibold text-foreground hover:bg-surface-hover";

function FloatingPanel({ open, onClose, artifact }: { open: boolean; onClose: () => void; artifact: PathArtifact | null }) {
  const anchor = useIslandAnchor();
  const viewport = useViewportWidth();
  const [limits] = useState(readLimits);
  const [stored, setStored] = useState(() => savedWidth(limits));
  const [dragging, setDragging] = useState(false);
  // Diem bat dau keo. Handler pointer gan bang prop React (khong `addEventListener`
  // trong effect): StrictMode chay effect hai lan se gan hai listener (B-260).
  const drag = useRef<{ x: number; width: number } | null>(null);
  const asideRef = useRef<HTMLElement>(null);
  const hintId = useId();

  /*
    Hop o lai trong DOM suot nhip ra (`data-state="closed"`, fast + exit), go o
    `animationend`. Giam chuyen dong (hoac jsdom) ⇒ `animation-name` la `none` /
    rong ⇒ go ngay — khong treo cho mot su kien khong bao gio toi.
  */
  const [closing, setClosing] = useState(false);
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    setClosing(!open);
  }
  useLayoutEffect(() => {
    const el = asideRef.current;
    if (closing && (el === null || ["", "none"].includes(getComputedStyle(el).animationName))) {
      setClosing(false);
    }
  }, [closing]);

  const layout = resolvePanelLayout({
    viewport,
    sidebar: anchor === "top" ? 0 : limits.sidebar,
    gap: limits.gap,
    stored,
    min: limits.min,
    max: limits.max,
    chatMin: limits.chatMin,
  });
  const fit = (width: number) => clamp(width, layout.low, layout.high);

  // Ban T-HD6 ⑦: neo tren can giua phan cot chat o TRAI mep panel.
  const occupied = open ? layout.width + limits.gap : 0;
  useEffect(() => setIslandRightInset(anchor === "top" ? occupied : 0), [anchor, occupied]);
  useEffect(() => () => setIslandRightInset(0), []);

  const onHandleKey = (e: KeyboardEvent) => {
    // Panel o mep phai: tay nam sang trai = panel rong ra.
    const next =
      e.key === "ArrowLeft"
        ? layout.width + KEY_STEP_PX
        : e.key === "ArrowRight"
          ? layout.width - KEY_STEP_PX
          : e.key === "Home"
            ? layout.low
            : e.key === "End"
              ? layout.high
              : null;
    if (next === null) {
      return;
    }
    e.preventDefault();
    setStored(fit(next));
    saveWidth(fit(next));
  };
  const endDrag = () => {
    if (drag.current !== null) {
      drag.current = null;
      setDragging(false);
      saveWidth(layout.width);
    }
  };

  return (
    <>
      {/* O dem trong luong flex cua `ChatScreen`: cot chat co / gian cung nhip hop. */}
      <div
        aria-hidden="true"
        data-panel={open ? "open" : "closed"}
        data-resizing={dragging}
        style={{ width: open && layout.mode === "push" ? layout.width + limits.gap : 0 }}
        className="motion-push shrink-0"
      />
      {(open || closing) && (
        <aside
          ref={asideRef}
          id={ARTIFACT_PANEL_ID}
          aria-label={t("artifact.panel.label")}
          data-state={open ? "open" : "closed"}
          data-anchor={anchor}
          data-mode={layout.mode}
          inert={!open}
          onAnimationEnd={(e) => {
            if (e.target === e.currentTarget && !open) {
              setClosing(false);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              onClose();
            }
          }}
          // So do luc chay (be rong da keo), khong phai mau hay khoang cach co dinh.
          style={{ width: layout.width }}
          className="motion-panel-side fixed top-panel-gap right-panel-gap bottom-panel-gap z-20 data-[anchor=right]:right-[calc(var(--spacing-island-gap)_+_var(--spacing-sidebar)_+_var(--spacing-panel-gap))]"
        >
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={t("artifact.panel.resize")}
            aria-describedby={hintId}
            aria-valuenow={layout.width}
            aria-valuemin={layout.low}
            aria-valuemax={layout.high}
            tabIndex={0}
            data-dragging={dragging}
            onKeyDown={onHandleKey}
            onPointerDown={(e) => {
              if (e.button !== 0) {
                return;
              }
              e.preventDefault(); // khong boi den chu cua cot chat khi keo
              e.currentTarget.setPointerCapture(e.pointerId);
              drag.current = { x: e.clientX, width: layout.width };
              setDragging(true);
            }}
            onPointerMove={(e) => {
              const start = drag.current;
              if (start !== null) {
                setStored(fit(start.width + start.x - e.clientX));
              }
            }}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            className="group motion-control absolute inset-y-0 left-0 z-10 w-3 -translate-x-1/2 cursor-col-resize touch-none rounded-md hover:bg-surface-hover"
          >
            <PanelGrip />
          </div>
          <span id={hintId} className="sr-only">
            {t("artifact.panel.resizeHint")}
          </span>
          <div className="flex size-full min-h-0 flex-col overflow-hidden rounded-panel bg-surface-panel text-foreground shadow-panel-float">
            <PanelBody artifact={artifact} onClose={onClose} heading={(text) => <h2 className={TITLE}>{text}</h2>} />
          </div>
        </aside>
      )}
    </>
  );
}

/**
 * Vach nhin thay duoc trong tay nam 12 px (ban T-HD6 ③). Vung bat 44 × 44 nam
 * han ve phia cot chat (lech 38 / 6): tay nam chi lan vao panel 6 px, khung
 * render cach mep 8 ⇒ khong phu len iframe.
 */
function PanelGrip() {
  return (
    <>
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-6 left-1/2 w-0.5 -translate-x-1/2 rounded-full bg-ring opacity-0 group-data-[dragging=true]:opacity-100"
      />
      <span aria-hidden="true" className="absolute top-1/2 right-0 size-touch -translate-y-1/2" />
      <span
        aria-hidden="true"
        className="motion-control pointer-events-none absolute top-1/2 left-1/2 h-panel-grip w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-border-strong group-hover:bg-foreground group-focus-visible:bg-ring group-data-[dragging=true]:bg-ring"
      />
    </>
  );
}

function PanelHeader({
  heading,
  meta,
  actions,
  onClose,
}: {
  heading: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="flex h-header shrink-0 items-center gap-1 border-b border-divider pr-2 pl-5">
      <div className="flex min-w-0 flex-1 flex-col">
        {heading}
        {meta}
      </div>
      {actions}
      {/*
        Khong tooltip: dialog (< 640 px) tu focus nut nay luc mo, tooltip cua
        Radix mo theo focus va la lop tren cung ⇒ Esc dau chi dong tooltip.
      */}
      <button type="button" onClick={onClose} aria-label={t("artifact.panel.close")} className={ICON_BUTTON}>
        <StaticIcon icon={X} size={20} />
      </button>
    </div>
  );
}

function PanelBody({
  artifact,
  onClose,
  heading,
}: {
  artifact: PathArtifact | null;
  onClose: () => void;
  heading: (text: ReactNode) => ReactNode;
}) {
  if (artifact === null) {
    return (
      <>
        <PanelHeader heading={heading(t("artifact.panel.title"))} onClose={onClose} />
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 bg-background px-8 text-center">
          <StaticIcon icon={PanelRight} size={28} className="mb-1 text-muted" />
          <p className="text-body font-semibold">{t("artifact.panel.empty")}</p>
          <p className="max-w-64 text-sm text-pretty text-muted">{t("artifact.panel.emptyHint")}</p>
        </div>
      </>
    );
  }
  // `key`: artifact khac ⇒ ve lai tu Xem truoc, khung moi.
  return <ArtifactView key={artifact.id} artifact={artifact} onClose={onClose} heading={heading} />;
}

/** Bay `kind` cua DDL (Phu luc A). `kind` la ⇒ nhu `code`. */
const KIND_LABEL: Readonly<Record<string, TextKey>> = {
  html: "artifact.panel.kind.html",
  react: "artifact.panel.kind.react",
  svg: "artifact.panel.kind.svg",
  mermaid: "artifact.panel.kind.mermaid",
  code: "artifact.panel.kind.code",
  markdown: "artifact.panel.kind.markdown",
  file: "artifact.panel.kind.file",
};
const KIND_ICON: Readonly<Record<string, IconNode>> = {
  html: CodeXml,
  react: Atom,
  svg: ImageIcon,
  mermaid: Workflow,
  code: FileCode,
  markdown: FileText,
  file: File,
};
const kindOf = (kind: string) => (Object.hasOwn(KIND_LABEL, kind) ? kind : "code");

type View = "preview" | "source";

function ArtifactView({
  artifact,
  onClose,
  heading,
}: {
  artifact: PathArtifact;
  onClose: () => void;
  heading: (text: ReactNode) => ReactNode;
}) {
  const [view, setView] = useState<View>("preview");
  const kind = kindOf(artifact.kind);
  const content = artifact.content ?? "";
  const ext = extensionFor(artifact.kind, artifact.language);
  const previewable = PREVIEW_KINDS.has(kind);
  const preview = previewable && view === "preview";
  const title = plainText(artifact.title);

  return (
    <>
      <PanelHeader
        heading={heading(title !== "" ? title : <DerivedTitle artifact={artifact} kind={kind} />)}
        meta={
          <span className="flex items-center gap-1.5 text-xs text-muted">
            <StaticIcon icon={KIND_ICON[kind]} size={13} />
            {t(KIND_LABEL[kind])}
          </span>
        }
        onClose={onClose}
        actions={
          <button
            type="button"
            onClick={() => download(artifact, content)}
            aria-label={`${t("artifact.panel.download")} ${ext}`}
            className={`${TEXT_BUTTON} px-2.5 font-normal`}
          >
            <StaticIcon icon={Download} size={18} />
            <span className="font-mono text-xs">{ext}</span>
          </button>
        }
      />
      {previewable && (
        <div className="flex shrink-0 items-center gap-2 border-b border-divider p-1 pl-2">
          <ViewSwitch value={view} onChange={setView} />
        </div>
      )}
      {preview && FRAME_KINDS.has(kind) && <FrameStage key={content} kind={kind} content={content} />}
      {preview && kind === "svg" && <SvgStage content={content} alt={title !== "" ? title : t(KIND_LABEL.svg)} />}
      {!preview && kind === "markdown" && <MarkdownStage content={content} />}
      {!preview && kind !== "markdown" && <SourceStage content={content} language={artifact.language ?? ""} />}
    </>
  );
}

/** Tieu de rong ⇒ "Python · 42 dong" (B-367 ③). Ghep tung manh, khong interpolation. */
function DerivedTitle({ artifact, kind }: { artifact: PathArtifact; kind: string }) {
  const name = languageName(artifact.language) || t(KIND_LABEL[kind]);
  if (artifact.content === null) {
    return <>{name}</>;
  }
  return (
    <>
      <span>{name}</span>
      <span aria-hidden="true"> · </span>
      <span className="tabular">{lineCount(artifact.content)}</span> <span>{t("artifact.lines")}</span>
    </>
  );
}

/**
 * Tai (UC-10 dong 5): `Blob` + `<a download>`, thu hoi ngay sau khi bam. Ten
 * va duoi qua MOT ham (`downloadName`) — tieu de do model dat.
 */
function download(artifact: PathArtifact, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mimeFor(artifact.kind) }));
  const link = document.createElement("a");
  link.href = url;
  link.download = downloadName(artifact);
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

const VIEWS: readonly [View, TextKey][] = [
  ["preview", "artifact.panel.preview"],
  ["source", "artifact.panel.source"],
];

function ViewSwitch({ value, onChange }: { value: View; onChange: (v: View) => void }) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") {
      return;
    }
    e.preventDefault();
    const next = value === "preview" ? "source" : "preview";
    onChange(next);
    buttons.current[VIEWS.findIndex(([v]) => v === next)]?.focus();
  };
  return (
    <div
      role="radiogroup"
      aria-label={t("artifact.panel.viewMode")}
      onKeyDown={onKeyDown}
      className="relative grid grid-cols-2 rounded-md border border-border-strong p-0.5"
    >
      {/* Vien den truot giua hai o bang nhau; chu doi mau theo, khong doi cho. */}
      <span
        aria-hidden="true"
        className={`motion-segment pointer-events-none absolute inset-y-0.5 left-0.5 w-[calc(50%_-_--spacing(0.5))] rounded-sm bg-foreground${
          value === "source" ? " translate-x-full" : ""
        }`}
      />
      {VIEWS.map(([v, key], i) => (
        <button
          key={v}
          ref={(el) => {
            buttons.current[i] = el;
          }}
          type="button"
          role="radio"
          aria-checked={value === v}
          tabIndex={value === v ? 0 : -1}
          onClick={() => onChange(v)}
          className={`motion-control relative min-h-touch rounded-sm px-3 text-sm font-medium ${
            value === v ? "text-background" : "text-foreground"
          }`}
        >
          {t(key)}
        </button>
      ))}
    </div>
  );
}

type FrameState = { status: "loading" | "ready" } | { status: "error" | "stalled"; message: string };

/**
 * `html` / `react` / `mermaid` trong khung origin phu (T-5.6 / T-5.7 / T-5.8).
 * Dai trang thai nam PHIA TREN khung, khong de len no (ban T-HD6 ⑥): khung o
 * origin khac, khong ve gi vao trong. Treo (watchdog C32) ⇒ khung da bi go,
 * cung dai loi voi tieu de rieng. "Chay lai" = iframe MOI (`key`).
 */
function FrameStage({ kind, content }: { kind: string; content: string }) {
  const [run, setRun] = useState(0);
  const [state, setState] = useState<FrameState>({ status: "loading" });
  const rerun = () => {
    setState({ status: "loading" });
    setRun((n) => n + 1);
  };
  return (
    <>
      {state.status === "loading" && (
        <p
          role="status"
          className="motion-enter flex min-h-touch shrink-0 items-center gap-2 border-b border-divider bg-surface-panel px-4 text-sm text-muted"
        >
          <StaticIcon icon={LoaderCircle} size={16} className="motion-spin" />
          {t("artifact.panel.loading")}
        </p>
      )}
      {(state.status === "error" || state.status === "stalled") && (
        <div role="alert" className="motion-enter flex shrink-0 flex-col gap-1.5 border-b border-divider bg-danger-subtle py-2 pr-2 pl-4">
          <div className="flex items-center gap-2">
            <p className="flex flex-1 items-center gap-2 text-sm font-semibold text-danger-text">
              <StaticIcon icon={CircleAlert} size={16} />
              {t(state.status === "stalled" ? "artifact.panel.stalledTitle" : "artifact.panel.errorTitle")}
            </p>
            <button type="button" onClick={rerun} className={SECONDARY_BUTTON}>
              <StaticIcon icon={RotateCcw} size={16} />
              {t("artifact.panel.rerun")}
            </button>
          </div>
          <pre tabIndex={0} className="max-h-24 overflow-auto pr-2 font-mono text-xs whitespace-pre-wrap text-foreground wrap-anywhere">
            {state.message}
          </pre>
        </div>
      )}
      {/* Le 8 nen background quanh khung: ranh gioi giua giao dien Scarlet va noi dung do model sinh. */}
      <div className="flex min-h-0 flex-1 bg-background p-2">
        <ArtifactFrame
          key={run}
          title={t("artifact.panel.frameTitle")}
          kind={kind}
          content={content}
          onResult={(result) =>
            setState(
              result.type === "rendered"
                ? { status: "ready" }
                : result.type === "stalled"
                  ? { status: "stalled", message: t("artifact.panel.stalledHint") }
                  : { status: "error", message: result.message },
            )
          }
          className={`size-full rounded-xl border border-border bg-surface-artifact${
            state.status === "loading" ? " invisible" : ""
          }`}
        />
      </div>
    </>
  );
}

/**
 * SVG qua `<img src="blob:">` (Q-P5-6): `<img>` khong chay script, SVG khong
 * vao DOM cua trang. Thu hoi URL ngay khi anh NAP XONG (anh da giai ma o lai
 * tren man hinh) va khi doi / dong neu chua nap: URL con song thi "Mo anh
 * trong tab moi" / keo anh len thanh tab mo chinh blob ay thanh MOT TAI LIEU
 * SVG o origin chinh — `<script>` cua no chay voi quyen cua app. `revoke` chi
 * chay mot lan moi URL (dem `create` = dem `revoke`).
 */
function SvgStage({ content, alt }: { content: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const release = useRef(() => {});
  useEffect(() => {
    const objectUrl = URL.createObjectURL(new Blob([content], { type: mimeFor("svg") }));
    let live = true;
    const revoke = () => {
      if (live) {
        live = false;
        URL.revokeObjectURL(objectUrl);
      }
    };
    release.current = revoke;
    setUrl(objectUrl);
    return revoke;
  }, [content]);
  return (
    <div className="flex min-h-0 flex-1 bg-background p-2">
      <div className="grid size-full place-items-center overflow-auto rounded-xl border border-border bg-surface-artifact p-4">
        {url !== null && (
          <img src={url} alt={alt} onLoad={() => release.current()} className="max-h-full max-w-full object-contain" />
        )}
      </div>
    </div>
  );
}

/** Ma: so dong bang `.code-lines` / `.code-line` (cung `CodeBlock`); dong dai cuon TRONG khoi. */
function SourceStage({ content, language }: { content: string; language: string }) {
  const lines = useMemo(() => highlightLines(content.replace(/\n$/, ""), language), [content, language]);
  return (
    <div className="flex min-h-0 flex-1 bg-background p-2">
      <pre
        tabIndex={0}
        aria-label={t("artifact.panel.source")}
        className="code-lines m-0 size-full overflow-auto overscroll-contain rounded-xl border border-border bg-surface-code py-3 font-mono text-sm leading-5 text-foreground"
      >
        <code>
          {lines.map((line, index) => (
            <span key={index} className="code-line pr-4">
              {line.map((piece, j) =>
                piece.cls === null ? (
                  piece.text
                ) : (
                  <span key={j} className={piece.cls}>
                    {piece.text}
                  </span>
                ),
              )}
              {index < lines.length - 1 ? "\n" : null}
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}

/**
 * Markdown do Scarlet dung (khong iframe) — `Markdown` cua bong bong, cung ba
 * lop NQ-95: khong HTML tho, `img` bi chan (B-235) nen anh hien… khong gi ca.
 */
function MarkdownStage({ content }: { content: string }) {
  return (
    <div className="flex min-h-0 flex-1 bg-background p-2">
      <div tabIndex={0} className="size-full overflow-auto rounded-xl border border-border bg-surface-panel px-5 py-4 text-foreground wrap-anywhere">
        <Markdown text={content} streaming={false} />
      </div>
    </div>
  );
}
