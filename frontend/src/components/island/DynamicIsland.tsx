import {
  ArrowRight,
  BookOpen,
  ChevronDown,
  GripVertical,
  LoaderCircle,
  MessageSquare,
  Pin,
  Search,
  Settings,
  Shield,
  SquarePen,
  type IconNode,
} from "lucide";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type Ref } from "react";
import { Link } from "react-router";

import { PATHS } from "../../app/paths";
import type { UserOut } from "../../lib/api";
import { t, type TextKey } from "../../lib/i18n";
import { ISLAND_COMPACT_QUERY, readDurationMs } from "../../lib/motion";
import { useMediaQuery } from "../../lib/viewport";
import { Hint } from "../chat/Hint";
import { AccountMenu } from "../sidebar/AccountMenu";
import { ARTIFACT_PANEL_ID, PanelToggle, type PanelBinding } from "../artifacts/ArtifactPanel";
import { ComingSoon } from "../ui/ComingSoon";
import { StaticIcon } from "../ui/Icon";
import { ThemeToggle } from "../ui/ThemeToggle";
import { setIslandAnchor, useIslandAnchor, type Anchor } from "./islandAnchor";
import { useIslandPhysics } from "./useIslandPhysics";

/**
 * Dao dieu huong — T-S.19a, ban Khung chinh v3 (`DynamicIsland.tsx`). Thay
 * header 56 + sidebar 256 + drawer cua v2 tren `/`, `/cai-dat/*`, `/admin`.
 *
 * Bon hinh, MOT khoi:
 *   pill     neo tren, thu   — icon + ten ngu canh (+ trang thai ket noi)
 *   bar      neo tren, mo    — dieu huong, 6 hoi thoai gan day, tai khoan, theme, panel artifact
 *   side     neo hai ben     — sidebar v2 (256), LUON mo; `Layout` day noi dung vao 16 + 256
 *   orb      dang keo        — 56 × 56
 * NQ-136 (nguoi dung, 2026-10-01): neo hai ben KHONG con vien thuoc doc cho re
 * chuot — theo ban v3-beta (`shape = top ? (mo ? bar : pill) : side`, `contentL`).
 * Muon gon thi keo (hoac ⋮⋮ + ↑) ve neo tren.
 * < 640 px: chi neo tren, khong keo; neo trai / phai da luu duoc giu cho man rong.
 *
 * Moi lop luon o trong DOM; lop khong hien mang `inert` (khong nhan Tab, khong
 * vao cay a11y). Nho vay hang "mount" cua §7b.2 (`B-06`, `B-264`) co DUNG mot
 * `data-planned` du dao dang o hinh nao (DoD dong 6).
 */

export type IslandContext = "chat" | "settings" | "admin";
type Shape = "pill" | "bar" | "side" | "orb";
export type RecentConversation = { id: string; title: string; pinned: boolean; untitled: boolean };

const CONTEXT_ICON: Record<IslandContext, IconNode> = { chat: MessageSquare, settings: Settings, admin: Shield };
const CONTEXT_LABEL: Record<IslandContext, TextKey> = {
  chat: "nav.chats",
  settings: "settings.title",
  admin: "admin.tieuDe",
};
const ANCHOR_LABEL: Record<Anchor, TextKey> = {
  top: "island.anchor.top",
  left: "island.anchor.left",
  right: "island.anchor.right",
};

/** So hoi thoai gan day trong thanh mo (ban ve: 6; duoi 640 px: 4, mot cot). */
const RECENT_WIDE = 6;
const RECENT_COMPACT = 4;

const GLASS_BUTTON =
  "motion-control grid size-touch shrink-0 place-items-center rounded-full text-foreground hover:bg-glass-hover";
const NAV_BASE =
  "motion-control inline-flex h-touch min-w-touch items-center justify-center gap-2 rounded-full text-base no-underline";
const NAV_ACTIVE = `${NAV_BASE} bg-accent-subtle font-semibold text-accent-text hover:text-accent-text`;
const NAV_IDLE = `${NAV_BASE} font-medium text-foreground hover:bg-glass-hover hover:text-foreground`;

export function DynamicIsland(props: {
  context: IslandContext;
  recent: RecentConversation[];
  activeId: string | null;
  isAdmin: boolean;
  user: UserOut;
  avatarColor: string | null;
  onLogout: () => Promise<void>;
  reconnecting: boolean;
  /** T-5.4 — nut panel artifact; NQ-128 c: chi canh hoi thoai (`/`), noi khac `undefined`. */
  artifactPanel?: PanelBinding;
  onNewChat: () => void;
  onSelect: (conversationId: string) => void;
  onOpenSearch: () => void;
  /** Noi dung sidebar v2 (nhom ngay, hang + menu ⋯, khoi tai khoan mo len) cho hinh "side". */
  sidebar: ReactNode;
}) {
  const compact = useMediaQuery(ISLAND_COMPACT_QUERY);
  const anchor = useIslandAnchor();
  /** Chi co nghia o neo tren (vien thuoc ↔ thanh mo); hai ben luon la sidebar. */
  const [expanded, setExpanded] = useState(false);

  const islandRef = useRef<HTMLElement>(null);
  const glassRef = useRef<HTMLDivElement>(null);
  const trailRef = useRef<HTMLCanvasElement>(null);
  const pillRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const pillTriggerRef = useRef<HTMLButtonElement>(null);
  const barGripRef = useRef<HTMLButtonElement>(null);
  const sideGripRef = useRef<HTMLButtonElement>(null);
  const hovered = useRef(false);
  const waitLeave = useRef(false);
  const linger = useRef<number | undefined>(undefined);
  /**
   * Tieu diem chinh dao dang chuyen, cho lop dich commit xong. Lop cu mang
   * `inert` ngay luc commit nen trinh duyet bo tieu diem khoi no (`blur`,
   * `relatedTarget = null`): lan `blur` ay KHONG phai nguoi dung roi dao, va
   * `focus()` chi goi duoc SAU commit — goi truoc la goi vao mot nut `inert`.
   *   layer   vao lop vua mo: nut ⋮⋮ (hoac muc dau o man hep)
   *   trigger ve nut mo cua vien thuoc (Esc, sau mot thao tac)
   *   grip    sang ⋮⋮ cua neo moi (doi neo bang phim)
   *   panel   ve nut panel artifact (panel vua dong tu ben trong — T-5.4)
   */
  const pendingFocus = useRef<"layer" | "trigger" | "grip" | "panel" | null>(null);

  const { dragging, near, handlers } = useIslandPhysics({
    islandRef,
    glassRef,
    trailRef,
    anchor,
    expanded,
    compact,
    measure: () => ({
      pillWidth: pillRef.current?.offsetWidth ?? 0,
      barHeight: barRef.current?.offsetHeight ?? 0,
    }),
    onRelease: (next) => {
      waitLeave.current = true; // con tro van tren dao sau khi tha — chua no lai
      setExpanded(false);
      setIslandAnchor(next);
    },
  });

  const shape: Shape = dragging ? "orb" : anchor !== "top" ? "side" : expanded ? "bar" : "pill";
  const atTop = anchor === "top";

  /**
   * Mot menu Radix mo tu TRONG dao (menu tai khoan, menu ⋯ cua hang) song o
   * portal ngoai `<nav>`: re chuot / dua tieu diem sang no khong duoc lam dao
   * thu lai, neu khong thi nut mo cua menu thanh `inert` giua chung.
   */
  const menuOpenInside = () =>
    islandRef.current?.querySelector('[aria-haspopup="menu"][data-state="open"]') != null;
  const collapse = () => {
    if (!menuOpenInside()) {
      setExpanded(false);
    }
  };
  /** Sau mot thao tac (mo hoi thoai, hoi thoai moi…): thu lai; tieu diem dang trong dao ⇒ ve nut mo. */
  const collapseAfterAction = () => {
    const focused = document.activeElement;
    // Chi khi hinh THAT SU doi (dao dang mo) — khong thi co treo, chan moi `blur` sau.
    if (expanded && focused !== null && islandRef.current?.contains(focused) === true) {
      pendingFocus.current = "trigger";
    }
    waitLeave.current = hovered.current;
    setExpanded(false);
  };
  /** Mo dao tu nut mo (ban phim, chuot, cham): tieu diem vao lop vua mo. */
  const open = () => {
    pendingFocus.current = "layer";
    setExpanded(true);
  };

  useLayoutEffect(() => {
    const pending = pendingFocus.current;
    if (pending === null) {
      return;
    }
    const grip = (anchor === "top" ? barGripRef : sideGripRef).current;
    if (pending === "panel") {
      visiblePanelToggle(islandRef.current)?.focus({ preventScroll: true });
    } else if (pending === "trigger") {
      pillTriggerRef.current?.focus({ preventScroll: true });
    } else if (grip !== null) {
      grip.focus({ preventScroll: true });
    } else {
      islandRef.current
        ?.querySelector<HTMLElement>('[data-active="true"] :is(a[href], button, input)')
        ?.focus({ preventScroll: true });
    }
    // Ha co SAU `focus()`: `onFocus` cua chinh lan nay khong duoc mo lai dao (Esc).
    pendingFocus.current = null;
  }, [shape, anchor]);
  useEffect(() => () => window.clearTimeout(linger.current), []);

  /*
    T-5.4 — panel dong tu ben trong (Esc, nut X) ⇒ tieu diem ve nut da mo no.
    Nut o lop dang hien (thanh mo / sidebar doc) ⇒ focus ngay; dao dang thu
    (neo tren) ⇒ nut nam trong lop `inert`: mo thanh roi focus SAU commit (B-323 ④).
  */
  const panelFocusRequest = props.artifactPanel?.focusRequest ?? 0;
  const seenPanelFocus = useRef(panelFocusRequest);
  useEffect(() => {
    if (panelFocusRequest === seenPanelFocus.current) {
      return;
    }
    seenPanelFocus.current = panelFocusRequest;
    const button = visiblePanelToggle(islandRef.current);
    if (button !== null) {
      button.focus({ preventScroll: true });
      return;
    }
    pendingFocus.current = "panel";
    setExpanded(true);
  }, [panelFocusRequest]);

  /*
    Cham / bam ra ngoai dao ⇒ thu lai (ban ve A1 `onStageDown`). Thieu dong nay
    thi tren man cam ung — khong co `pointerleave`, Safari khong focus nut khi
    cham — dao mo ra la khong dong lai duoc.
  */
  useEffect(() => {
    if (!expanded) {
      return undefined;
    }
    const onDown = (event: PointerEvent) => {
      const target = event.target as Element | null;
      if (target === null || islandRef.current?.contains(target) || target.closest('[role="menu"]') !== null) {
        return;
      }
      setExpanded(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [expanded]);

  const onAnchorKey = (next: Anchor) => {
    if (next !== anchor) {
      pendingFocus.current = "grip";
    }
    // Ve neo tren bang phim: mo thanh, de tieu diem sang duoc ⋮⋮ cua no.
    if (next === "top") {
      setExpanded(true);
    }
    setIslandAnchor(next);
  };

  const recent = props.recent.slice(0, compact ? RECENT_COMPACT : RECENT_WIDE);

  return (
    <>
      <canvas ref={trailRef} aria-hidden="true" className="pointer-events-none fixed inset-0 z-40 size-full" />
      {!compact && (
        <AnchorHints visible={dragging} near={near} pillWidth={pillRef.current?.offsetWidth ?? 0} />
      )}
      {props.reconnecting && anchor !== "top" && (
        <div
          aria-hidden="true"
          className="motion-enter fixed top-island-gap left-1/2 z-30 flex -translate-x-1/2 items-center gap-2 rounded-full border border-border-strong bg-surface-panel px-3.5 py-2 text-sm whitespace-nowrap shadow-popover"
        >
          <StaticIcon icon={LoaderCircle} size={16} className="motion-spin text-muted" />
          {t("chat.ketNoi.dangNoiLai")}
        </div>
      )}

      <nav
        ref={islandRef}
        aria-label={t("island.label")}
        data-dragging={dragging}
        data-anchor={anchor}
        data-shape={shape}
        {...handlers}
        onPointerEnter={(e) => {
          if (e.pointerType !== "mouse" || !atTop) {
            return;
          }
          hovered.current = true;
          window.clearTimeout(linger.current);
          if (!dragging && !waitLeave.current) {
            setExpanded(true);
          }
        }}
        onPointerLeave={(e) => {
          if (e.pointerType !== "mouse" || !atTop) {
            return;
          }
          hovered.current = false;
          waitLeave.current = false;
          window.clearTimeout(linger.current);
          linger.current = window.setTimeout(() => {
            const focused = document.activeElement;
            const keyboardInside =
              focused !== null && islandRef.current?.contains(focused) === true && focused.matches(":focus-visible");
            if (!keyboardInside && !hovered.current) {
              collapse();
            }
          }, readDurationMs("--duration-island-linger"));
        }}
        onFocus={(e) => {
          if (!atTop || pendingFocus.current !== null || expanded || !e.target.matches(":focus-visible")) {
            return;
          }
          if (e.target.hasAttribute("data-island-trigger")) {
            open();
          } else {
            setExpanded(true);
          }
        }}
        onBlur={(e) => {
          const next = e.relatedTarget as Element | null;
          if (
            pendingFocus.current !== null ||
            (next !== null && (islandRef.current?.contains(next) || next.closest('[role="menu"]') !== null)) ||
            hovered.current
          ) {
            return;
          }
          collapse();
        }}
        onKeyDown={(e) => {
          if (e.key !== "Escape" || !atTop || !expanded || menuOpenInside()) {
            return;
          }
          e.stopPropagation();
          pendingFocus.current = "trigger";
          setExpanded(false);
        }}
        // Sidebar doc o man cam ung rong: vuot doc de cuon danh sach, vuot ngang van keo dao.
        className="fixed top-0 left-0 z-50 cursor-grab touch-none select-none data-[dragging=true]:cursor-grabbing data-[shape=side]:touch-pan-y"
      >
        <div ref={glassRef} aria-hidden="true" data-dragging={dragging} className="island-glass absolute inset-0 rounded-[inherit]" />
        <div className="absolute inset-0 overflow-hidden rounded-[inherit]">
          <Layer
            on={shape === "pill"}
            ref={pillRef}
            className="top-0 left-1/2 flex h-island-pill -translate-x-1/2 items-center whitespace-nowrap"
          >
            <IslandTrigger
              ref={pillTriggerRef}
              context={props.context}
              expanded={expanded}
              grip={!compact}
              onOpen={open}
            />
            {props.reconnecting && <ConnectionSegment />}
          </Layer>

          <Layer on={shape === "orb"} className="inset-0 grid place-items-center text-accent-text">
            <StaticIcon icon={CONTEXT_ICON[props.context]} size={22} />
          </Layer>

          <Layer
            on={shape === "bar"}
            ref={barRef}
            className="top-0 left-1/2 flex w-[min(var(--spacing-island-bar),calc(100vw_-_2*var(--spacing-island-gap)))] origin-top -translate-x-1/2 flex-col gap-0.5 p-2"
          >
            {props.reconnecting && (
              <div aria-hidden="true" className="flex h-9 items-center justify-center gap-2 text-sm font-medium">
                <StaticIcon icon={LoaderCircle} size={16} className="motion-spin text-muted" />
                {t("chat.ketNoi.dangNoiLai")}
              </div>
            )}
            <div className="flex items-center gap-1">
              {!compact && <GripButton ref={barGripRef} anchor={anchor} onAnchor={onAnchorKey} />}
              <ul className="flex min-w-0 flex-1 items-center justify-center gap-0.5">
                <li className="flex">
                  <NavAction
                    icon={SquarePen}
                    label={t("nav.newChat")}
                    onClick={() => {
                      props.onNewChat();
                      collapseAfterAction();
                    }}
                  />
                </li>
                <li className="flex">
                  <NavLink to={PATHS.home} icon={MessageSquare} label={t("nav.chats")} active={props.context === "chat"} compact={compact} />
                </li>
                <li className="flex">
                  <NavAction icon={Search} label={t("sidebar.search")} onClick={props.onOpenSearch} />
                </li>
                <li className="flex">
                  {/* NQ-135: RAG la B-06 o Backlog — chua co task gan. */}
                  <ComingSoon
                    planned="B-06"
                    label={t("nav.knowledge")}
                    icon={<StaticIcon icon={BookOpen} size={18} />}
                    className={`${NAV_IDLE} control-disabled`}
                  />
                </li>
                <li className="flex">
                  <NavLink
                    to={PATHS.settings}
                    icon={Settings}
                    label={t("settings.title")}
                    active={props.context === "settings"}
                    compact={compact}
                  />
                </li>
                {/* An khi khong phai admin la lich su, KHONG phai phan quyen (`require_admin` o backend). */}
                {props.isAdmin && (
                  <li className="flex">
                    <NavLink
                      to={PATHS.admin}
                      icon={Shield}
                      label={t("admin.tieuDe")}
                      active={props.context === "admin"}
                      compact={compact}
                    />
                  </li>
                )}
              </ul>
              {!compact && <span aria-hidden="true" className="w-touch shrink-0" />}
            </div>
            <div role="separator" className="mx-2 my-1 h-px bg-divider" />
            <div className="flex items-center justify-between gap-2 pl-3">
              <h2 className="text-xs font-semibold text-muted">{t("island.recent")}</h2>
              <button
                type="button"
                onClick={props.onOpenSearch}
                className="motion-control inline-flex min-h-touch items-center gap-1.5 rounded-full px-3 text-sm font-semibold text-accent-text hover:bg-glass-hover"
              >
                {t("island.seeAll")}
                <StaticIcon icon={ArrowRight} size={16} />
              </button>
            </div>
            <ul className="grid grid-cols-1 gap-0.5 sm:grid-cols-2">
              {recent.map((item) => {
                const current = item.id === props.activeId;
                return (
                  <li key={item.id} className="flex min-w-0">
                    <button
                      type="button"
                      aria-current={current ? "page" : undefined}
                      onClick={() => {
                        props.onSelect(item.id);
                        collapseAfterAction();
                      }}
                      className={
                        current
                          ? "flex h-touch min-w-0 flex-1 items-center gap-1.5 rounded-island-item border border-accent bg-accent-subtle px-3 text-left text-base font-semibold text-foreground"
                          : "motion-control flex h-touch min-w-0 flex-1 items-center gap-1.5 rounded-island-item border border-transparent px-3 text-left text-base text-foreground hover:bg-glass-hover"
                      }
                    >
                      <span className={item.untitled ? "min-w-0 flex-1 truncate text-muted" : "min-w-0 flex-1 truncate"}>
                        {item.title}
                      </span>
                      {item.pinned && <StaticIcon icon={Pin} size={14} label={t("sidebar.pinned")} className="shrink-0 text-muted" />}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div role="separator" className="mx-2 my-1 h-px bg-divider" />
            <div className="flex items-center gap-1">
              <AccountMenu placement="island" user={props.user} avatarColor={props.avatarColor} onLogout={props.onLogout} />
              <ThemeToggle />
              {props.artifactPanel !== undefined && (
                <PanelToggle binding={props.artifactPanel} className={GLASS_BUTTON} />
              )}
            </div>
          </Layer>

          <Layer
            on={shape === "side"}
            data-anchor={anchor}
            className="top-0 left-0 h-full w-sidebar data-[anchor=right]:right-0 data-[anchor=right]:left-auto"
          >
            {props.sidebar}
            {!compact && (
              <GripButton
                ref={sideGripRef}
                anchor={anchor}
                onAnchor={onAnchorKey}
                // Vo hinh cho toi khi focus bang phim — va khong an chuot, khong thi no chan
                // goc phai nut "Hoi thoai moi" ben duoi (sidebar nay luon mo, NQ-136).
                className="pointer-events-none absolute top-3 right-3 z-10 rounded-md bg-surface-panel opacity-0 shadow-popover focus-visible:pointer-events-auto focus-visible:opacity-100"
              />
            )}
          </Layer>
        </div>
      </nav>

      <span id="island-move-hint" className="sr-only">
        {t("island.moveHint")}
      </span>
      <p role="status" className="sr-only">
        <span>{t("island.anchoredPrefix")}</span> <span>{t(ANCHOR_LABEL[anchor])}</span>
      </p>
      <p role="status" className="sr-only">
        {props.reconnecting ? t("chat.ketNoi.dangNoiLai") : null}
      </p>
    </>
  );
}

/** Nut panel artifact cua lop dang hien (thanh mo, hoac chan sidebar doc) — `null` khi lop ay `inert`. */
function visiblePanelToggle(island: HTMLElement | null): HTMLElement | null {
  return island?.querySelector<HTMLElement>(`[data-active="true"] [aria-controls="${ARTIFACT_PANEL_ID}"]`) ?? null;
}

/** `inert`: lop an khong nhan Tab, khong vao cay a11y. React 19: `inert` la boolean, `ref` la prop. */
function Layer({
  on,
  className,
  ref,
  ...rest
}: {
  on: boolean;
  className: string;
  ref?: Ref<HTMLDivElement>;
  children?: ReactNode;
  "data-anchor"?: string;
}) {
  return <div ref={ref} data-active={on} inert={!on} className={`motion-island-layer absolute ${className}`} {...rest} />;
}

function IslandTrigger({
  context,
  expanded,
  grip,
  onOpen,
  ref,
}: {
  context: IslandContext;
  expanded: boolean;
  grip: boolean;
  onOpen: () => void;
  ref?: Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={ref}
      type="button"
      aria-expanded={expanded}
      data-island-trigger
      onClick={onOpen}
      className="flex h-island-pill items-center gap-2 rounded-full pr-4 pl-2.5 text-base font-semibold text-foreground"
    >
      {grip && <StaticIcon icon={GripVertical} size={18} className="text-muted" />}
      <span className="grid size-7.5 place-items-center rounded-full bg-accent-subtle text-accent-text">
        <StaticIcon icon={CONTEXT_ICON[context]} size={18} />
      </span>
      <span>{t(CONTEXT_LABEL[context])}</span>
      <span className="sr-only">{t("island.open")}</span>
      <StaticIcon icon={ChevronDown} size={14} className="text-muted" />
    </button>
  );
}

/** Phan trang thai gan vao vien thuoc. Dao gian bang lo xo morph vi be ngang pill do tu noi dung. */
function ConnectionSegment() {
  return (
    <span aria-hidden="true" className="flex h-island-pill items-center gap-2 pr-4.5 text-sm font-medium text-foreground">
      <span className="mr-1 h-5 w-px bg-divider" />
      <StaticIcon icon={LoaderCircle} size={16} className="motion-spin text-muted" />
      {t("chat.ketNoi.dangNoiLai")}
    </span>
  );
}

function GripButton({
  anchor,
  onAnchor,
  className = "",
  ref,
}: {
  anchor: Anchor;
  onAnchor: (next: Anchor) => void;
  className?: string;
  ref?: Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={t("island.move")}
      aria-describedby="island-move-hint"
      onKeyDown={(e) => {
        const byArrow: Partial<Record<string, Anchor>> = { ArrowUp: "top", ArrowLeft: "left", ArrowRight: "right" };
        const cycle: Record<Anchor, Anchor> = { top: "right", right: "left", left: "top" };
        const next = byArrow[e.key] ?? (e.key === "Enter" || e.key === " " ? cycle[anchor] : undefined);
        if (next === undefined) {
          return;
        }
        e.preventDefault();
        onAnchor(next);
      }}
      className={`motion-control grid size-touch shrink-0 cursor-grab place-items-center rounded-full text-muted hover:bg-glass-hover ${className}`}
    >
      <StaticIcon icon={GripVertical} size={18} />
    </button>
  );
}

function NavAction({ icon, label, onClick }: { icon: IconNode; label: string; onClick: () => void }) {
  return (
    <Hint label={label} side="bottom">
      <button type="button" aria-label={label} onClick={onClick} className={NAV_IDLE}>
        <StaticIcon icon={icon} size={18} />
      </button>
    </Hint>
  );
}

/** Muc dang chon co nhan (≥ 640 px); con lai chi icon + tooltip ten. */
function NavLink({
  to,
  icon,
  label,
  active,
  compact,
}: {
  to: string;
  icon: IconNode;
  label: string;
  active: boolean;
  compact: boolean;
}) {
  const showLabel = active && !compact;
  const link = (
    <Link
      to={to}
      aria-current={active ? "page" : undefined}
      aria-label={showLabel ? undefined : label}
      // Dang o chinh trang nay: bam khong dieu huong lai (giu `?c=` cua man chat).
      onClick={active ? (e) => e.preventDefault() : undefined}
      // Keo dao tu mot link: khong cho trinh duyet keo-tha link (no ban
      // `pointercancel`, dao bi tha giua chung).
      draggable={false}
      className={showLabel ? `${NAV_ACTIVE} pr-4 pl-3.5` : active ? NAV_ACTIVE : NAV_IDLE}
    >
      <StaticIcon icon={icon} size={18} />
      {showLabel && <span>{label}</span>}
    </Link>
  );
  return showLabel ? link : <Hint label={label} side="bottom">{link}</Hint>;
}

/** O neo hien trong luc keo — hai ben la CA khoi sidebar (ban v3-beta), tren la vien thuoc. */
function AnchorHints({ visible, near, pillWidth }: { visible: boolean; near: Anchor | null; pillWidth: number }) {
  const base =
    "motion-anchor-hint pointer-events-none fixed z-40 box-border border-[1.5px] border-dashed border-border-strong";
  const side = `${base} top-island-gap bottom-island-gap w-sidebar rounded-island-side`;
  return (
    <div aria-hidden="true">
      <div
        data-visible={visible}
        data-near={near === "top"}
        // So do that luc chay (be ngang vien thuoc), khong phai mau hay thoi luong.
        style={{ width: pillWidth }}
        className={`${base} top-island-gap left-1/2 h-island-pill -translate-x-1/2 rounded-full`}
      />
      <div data-visible={visible} data-near={near === "left"} className={`${side} left-island-gap`} />
      <div data-visible={visible} data-near={near === "right"} className={`${side} right-island-gap`} />
    </div>
  );
}
