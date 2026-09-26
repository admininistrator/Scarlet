/**
 * Model Picker v2 — T-S.14, ban thiet ke T-HD4-v2.
 *
 * KH tham chieu: §24.2b·S3, S4, S11, UC-05, RR-5 · tasks.md T-3.6, T-S.4,
 * T-S.14 · NQ-118, NQ-119, NQ-120 · ADR-16.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHONG MOT ID MODEL NAO TRONG FILE NAY                                 ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Component nhan `models` qua prop va khong so `model.id` voi mot hang chuoi
 * nao; tang mac dinh va muc suy luan cung la du lieu. Do la ly do lenh grep
 * cua DoD T-3.6/T-S.14 tra ve rong tren thu muc nay (A3).
 *
 * ── Nut mo: ten model hieu luc, chu tron (ban A, NQ-115) ─────────────────
 *
 * Khong vien, khong nen o trang thai thuong; mui ten 14 px la dau duy nhat
 * cho biet bam duoc. Tang mac dinh khong con in duoi nut — no o khoi ①.
 *
 * ── Bon khoi (S11, ban B) ────────────────────────────────────────────────
 *
 *   ① Dang dung (`CurrentModel`)  ② Thinking Effort ›  ③ More models ›
 *   ④ Gia (`PriceBlock`)
 *
 * ── Desktop: popover + hai lop con canh ben trai ─────────────────────────
 *
 * Ban ve ghi *"Popover neo vao nut mo"* va chi dat `role="menu"` cho menu con
 * Thinking Effort (`menuitemradio` + `aria-checked`, ban C); danh sach More
 * models la danh sach v1 (`listbox`, hang khoa van `tabIndex 0` de doc ly do —
 * ban D). Vi vay:
 *
 *   * bang chon = `Popover` (khoi ① ④ la noi dung doc, khong phai muc menu —
 *     trong mot `role="menu"` screen reader chi doc cac muc);
 *   * ② = mot `DropdownMenu` (non-modal) neo vao chinh hang ②, mo sang TRAI;
 *   * ③ = mot `Popover` long neo vao hang ③, cung mo sang trai.
 *
 * `DropdownMenu.Sub` cua Radix (mau `MotionV2.tsx`) khong dung duoc cho ②:
 * no doi bang cha la mot `role="menu"`, va Esc trong menu con dong CA menu —
 * trai *"← / Esc dong ve hang ②"* cua ban C. Hai lop rieng cho dung hanh vi
 * ay tu nhien: Esc chi toi lop tren cung, Radix tra tieu diem ve nut mo cua
 * lop (hang ② / ③). → mo, ← dong: hai phim Radix khong gan cho menu goc,
 * them o day.
 *
 * ── Duoi 640 px: MOT sheet, ba man (ban E) ───────────────────────────────
 *
 * Sheet giu chieu cao `h-sheet-screen` (tran `max-h-sheet-max`) khi truot giua
 * cac man nen khong nhay. Man con vao tu phai (`motion-screen`), quay lai vao
 * tu trai; man roi di chay `motion-screen-leave` cung nhip. Nut quay lai 44 ×
 * 44; quay ve thi tieu diem ve dung hang ② / ③.
 */

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Popover from "@radix-ui/react-popover";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Check, ChevronDown, ChevronLeft, ChevronRight, X } from "lucide";

import type { ModelOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { useReducedMotion } from "../../lib/motion";
import { StaticIcon } from "../../components/ui/Icon";
import { CurrentModel } from "./CurrentModel";
import type { DefaultPick } from "./defaults";
import { ModelList, SIDE_LAYER_OFFSET, StatusStrip } from "./ModelList";
import { PriceBlock } from "./PriceBlock";
import { effortLabel } from "./reasoning";

/** Duoi be rong nay picker la sheet, khong phai popover (ban T-HD4, 3c). */
const NARROW_QUERY = "(max-width: 639px)";

export interface ModelPickerProps {
  models: ModelOut[];
  /** Ket qua cua `pickDefault()` — model dang dung + tang cua tung id. */
  defaultPick: DefaultPick;
  /**
   * Muc suy luan hieu luc cua model dang dung (`useChat.effectiveEffort`) —
   * gia tri in ben phai hang ②. `null` = model khong co muc.
   */
  effort: string | null;
  /**
   * Moc gio backend DO (`checked_at`, T-S.4) da dinh dang SAN ben ngoai, vi
   * du `"14:32"` — ham `t()` khong co interpolation (`lib/i18n.ts`).
   */
  checkedAtLabel: string;
  /** Lan doc dau tien chua xong (T-S.4): "dang tai" thay cho "chua co". */
  loading?: boolean;
  refreshing?: boolean;
  onRefresh: () => void;
  onPick: (modelId: string) => void;
  /** Chon mot muc cho model dang dung ⇒ `PUT /settings` (`reasoning_prefs`). */
  onPickEffort: (level: string) => void;
  /** Goi moi lan picker MO — `useModels.refreshIfStale` (T-S.4). */
  onOpen?: () => void;
}

/** Be rong nho hay khong. Theo doi song, khong doc mot lan roi thoi. */
function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.matchMedia(NARROW_QUERY).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(NARROW_QUERY);
    const handleChange = (): void => setNarrow(mq.matches);
    mq.addEventListener("change", handleChange);
    // Doc lai ngay: giua lan render dau va lan `useEffect` chay, be rong co
    // the da khac (xoay may, mo DevTools).
    handleChange();
    return () => mq.removeEventListener("change", handleChange);
  }, []);
  return narrow;
}

/** → tren hang ② / ③ mo lop con (ban C: "Mo bang click, Enter, hoac →"). */
function openOnArrowRight(open: () => void) {
  return (e: KeyboardEvent): void => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      open();
    }
  };
}

/** ← trong lop con dong no; Radix tra tieu diem ve hang da mo no. */
function closeOnArrowLeft(close: () => void) {
  return (e: KeyboardEvent): void => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      close();
    }
  };
}

// ─────────────────────────── desktop: hang ② va ③ ───────────────────────────

/** Hang ② / ③ desktop: cao 44, chu 14, gia tri 13 muted, mui ten 16. */
const ROW_CLASS =
  "group motion-control flex min-h-touch w-full items-center gap-2 rounded-md pr-2 pl-2.5 text-left hover:bg-surface-hover data-[state=open]:bg-surface-hover";

function RowChevron({ size }: { size: number }) {
  return (
    <StaticIcon
      icon={ChevronRight}
      size={size}
      className="motion-icon shrink-0 text-muted group-hover:text-foreground group-data-[state=open]:text-foreground"
    />
  );
}

function EffortMenu({
  model,
  effort,
  onPickEffort,
}: {
  model: ModelOut;
  effort: string | null;
  onPickEffort: (level: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const reasoning = model.reasoning;

  if (reasoning === null) {
    /*
      Ban F: hang van o cho cu, khong an — `aria-disabled` + `control-disabled`
      (mo `--disabled-opacity`, con tro not-allowed), khong mo menu con, khong
      in gia tri. `aria-disabled` chu khong `disabled`: nut van nhan tieu diem
      nen tooltip ly do toi duoc nguoi dung ban phim.
    */
    return (
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            aria-disabled="true"
            className="control-disabled flex min-h-touch w-full items-center gap-2 rounded-md pr-2 pl-2.5 text-left"
          >
            <span className="flex-1 text-base font-medium">{t("model.effort")}</span>
            <StaticIcon icon={ChevronRight} size={16} className="shrink-0 text-muted" />
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            side="left"
            sideOffset={SIDE_LAYER_OFFSET}
            collisionPadding={16}
            className="motion-popover z-50 max-w-tooltip rounded-md bg-surface-tooltip px-3 py-2 text-xs leading-relaxed text-tooltip-foreground shadow-popover"
          >
            {t("model.effortNone")}
            <Tooltip.Arrow className="fill-surface-tooltip" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    );
  }

  return (
    <DropdownMenu.Root modal={false} open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button type="button" onKeyDown={openOnArrowRight(() => setOpen(true))} className={ROW_CLASS}>
          <span className="flex-1 text-base font-medium">{t("model.effort")}</span>
          {effort !== null ? <span className="text-sm text-muted">{effortLabel(effort)}</span> : null}
          <RowChevron size={16} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="left"
          align="end"
          sideOffset={SIDE_LAYER_OFFSET}
          collisionPadding={16}
          onKeyDown={closeOnArrowLeft(() => setOpen(false))}
          className="motion-submenu z-50 w-submenu rounded-lg border border-border bg-surface-panel p-1.5 text-foreground shadow-popover"
        >
          {/* Chi cac muc cua model nay, dung thu tu catalog (ban C). */}
          <DropdownMenu.RadioGroup
            value={effort ?? undefined}
            onValueChange={onPickEffort}
            className="flex flex-col gap-0.5"
          >
            {reasoning.options.map((o) => (
              <DropdownMenu.RadioItem
                key={o.id}
                value={o.id}
                className="motion-control flex min-h-touch cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-base outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring data-[state=checked]:bg-accent-subtle data-[state=checked]:font-semibold data-[state=unchecked]:data-highlighted:bg-surface-hover"
              >
                <span className="flex w-4 shrink-0 justify-center">
                  <DropdownMenu.ItemIndicator>
                    <StaticIcon icon={Check} size={16} strokeWidth={2.25} className="text-accent-text" />
                  </DropdownMenu.ItemIndicator>
                </span>
                <span>{effortLabel(o.id)}</span>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function MoreModels({
  models,
  defaultPick,
  checkedAtLabel,
  refreshing,
  onRefresh,
  onPick,
}: Pick<ModelPickerProps, "models" | "defaultPick" | "checkedAtLabel" | "refreshing" | "onRefresh" | "onPick">) {
  const [open, setOpen] = useState(false);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button type="button" onKeyDown={openOnArrowRight(() => setOpen(true))} className={ROW_CLASS}>
          <span className="flex-1 text-base font-medium">{t("model.moreModels")}</span>
          <RowChevron size={16} />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="left"
          align="end"
          sideOffset={SIDE_LAYER_OFFSET}
          collisionPadding={16}
          aria-label={t("model.moreModels")}
          onKeyDown={closeOnArrowLeft(() => setOpen(false))}
          className="motion-submenu z-50 flex max-h-(--radix-popover-content-available-height) w-picker max-w-picker-max flex-col overflow-hidden rounded-lg border border-border bg-surface-panel text-foreground shadow-popover"
        >
          <StatusStrip
            checkedAtLabel={checkedAtLabel}
            refreshing={refreshing}
            narrow={false}
            onRefresh={onRefresh}
          />
          <ModelList
            models={models}
            defaultPick={defaultPick}
            narrow={false}
            onPick={onPick}
            className="min-h-0 overflow-y-auto p-1.5"
          />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function EmptyBody({ loading, narrow }: { loading?: boolean; narrow: boolean }) {
  /*
    T-S.4 — hai cau khac nhau cho hai trang thai khac nhau: dang cho lan doc
    dau (`role="status"` de screen reader duoc bao khi no doi) va da doc xong
    ma that su rong. Ban A: khong vong quay.
  */
  return (
    <p
      role="status"
      className={`text-center text-sm text-muted ${narrow ? "border-t border-divider px-4 py-7" : "px-4 py-7"}`}
    >
      {loading ? t("model.loading") : t("model.trong")}
    </p>
  );
}

// ───────────────────────────── 375 px: ba man ─────────────────────────────

type Screen = "main" | "effort" | "more";
type Direction = "forward" | "back";

/** Hang ② / ③ o 375 px: cao 48 (`min-h-row-menu`), chu 15, mui ten 18. */
const NARROW_ROW_CLASS =
  "motion-control flex min-h-row-menu w-full items-center gap-2 rounded-md px-2 text-left hover:bg-surface-hover";

function CloseButton() {
  return (
    <Dialog.Close
      aria-label={t("model.closeSheet")}
      className="motion-press flex size-touch shrink-0 items-center justify-center rounded-md text-muted hover:bg-surface-hover hover:text-foreground"
    >
      <StaticIcon icon={X} size={18} strokeWidth={1.75} />
    </Dialog.Close>
  );
}

/**
 * `live = false` la ban sao cua man DANG ROI DI (hoat anh ra): cung hinh, nhung
 * khong `Dialog.Title` (hai tieu de cung `id`) va khong nhan tieu diem (`inert`).
 */
function ScreenTitle({ live, children }: { live: boolean; children: string }) {
  const className = "min-w-0 flex-1 text-lg font-semibold";
  return live ? <Dialog.Title className={className}>{children}</Dialog.Title> : <h3 className={className}>{children}</h3>;
}

function SheetScreens(props: ModelPickerProps & { selected: ModelOut | undefined; close: () => void }) {
  const { models, defaultPick, effort, selected } = props;
  const reduced = useReducedMotion();
  const [screen, setScreen] = useState<Screen>("main");
  const [direction, setDirection] = useState<Direction>("forward");
  //: Chi truot khi DA dieu huong — man chinh luc mo sheet di len cung sheet.
  const [navigated, setNavigated] = useState(false);
  const [leaving, setLeaving] = useState<Screen | null>(null);
  const effortRowRef = useRef<HTMLButtonElement>(null);
  const moreRowRef = useRef<HTMLButtonElement>(null);
  const backRef = useRef<HTMLButtonElement>(null);
  //: Man vua roi — quay ve man chinh thi tieu diem ve dung hang da mo no.
  const cameFromRef = useRef<Screen | null>(null);

  const go = (next: Screen, dir: Direction): void => {
    cameFromRef.current = screen;
    // Giam chuyen dong: khong co man roi di nao de ve (`motion-screen-leave`
    // bi tat, `animationend` se khong bao gio toi de go no).
    setLeaving(reduced ? null : screen);
    setDirection(dir);
    setNavigated(true);
    setScreen(next);
  };

  useEffect(() => {
    if (!navigated) {
      return;
    }
    if (screen === "main") {
      const from = cameFromRef.current;
      (from === "effort" ? effortRowRef : moreRowRef).current?.focus();
    } else {
      backRef.current?.focus();
    }
  }, [screen, navigated]);

  const pickModel = (id: string): void => {
    props.onPick(id);
    props.close();
  };

  const pickEffort = (level: string): void => {
    props.onPickEffort(level);
    go("main", "back");
  };

  const subHeader = (title: string, live: boolean): ReactNode => (
    <div className="flex shrink-0 items-center gap-1 border-b border-divider px-1.5 py-0.5">
      <button
        ref={live ? backRef : undefined}
        type="button"
        aria-label={t("model.back")}
        onClick={() => go("main", "back")}
        className="motion-press flex size-touch shrink-0 items-center justify-center rounded-md text-foreground hover:bg-surface-hover"
      >
        <StaticIcon icon={ChevronLeft} size={20} />
      </button>
      <ScreenTitle live={live}>{title}</ScreenTitle>
      <CloseButton />
    </div>
  );

  const render = (s: Screen, live: boolean): ReactNode => {
    if (s === "effort" && selected?.reasoning) {
      return (
        <>
          {subHeader(t("model.effort"), live)}
          {/* Ban E: dong ten model de biet dang dat muc cho model nao. */}
          <p className="px-4 pt-3 pb-1 text-xs text-muted">{selected.display_name}</p>
          <EffortScreenItems options={selected.reasoning.options} effort={effort} onPick={pickEffort} />
        </>
      );
    }
    if (s === "more") {
      return (
        <>
          {subHeader(t("model.moreModels"), live)}
          <StatusStrip
            checkedAtLabel={props.checkedAtLabel}
            refreshing={props.refreshing}
            narrow
            onRefresh={props.onRefresh}
          />
          <ModelList
            models={models}
            defaultPick={defaultPick}
            narrow
            onPick={pickModel}
            className="min-h-0 flex-1 overflow-y-auto px-2 py-1.5"
          />
        </>
      );
    }
    return (
      <>
        <div className="flex shrink-0 items-center justify-between gap-2 py-0.5 pr-1.5 pl-4">
          <ScreenTitle live={live}>{t("model.picker")}</ScreenTitle>
          <CloseButton />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {selected === undefined ? (
            <EmptyBody loading={props.loading} narrow />
          ) : (
            <>
              <div className="border-t border-divider">
                <CurrentModel model={selected} tier={defaultPick.tier} narrow />
              </div>
              <div className="border-t border-divider px-2 py-1">
                {selected.reasoning === null ? (
                  /* Ban F 375 px: khong co hover ⇒ cau ly do in thang duoi nhan. */
                  <button
                    type="button"
                    aria-disabled="true"
                    className="control-disabled flex min-h-14 w-full items-center gap-2 rounded-md px-2 py-1.5 text-left"
                  >
                    <span className="flex flex-1 flex-col gap-0.5">
                      <span className="text-body font-medium">{t("model.effort")}</span>
                      <span className="text-xs text-muted">{t("model.effortNone")}</span>
                    </span>
                    <StaticIcon icon={ChevronRight} size={18} className="shrink-0 text-muted" />
                  </button>
                ) : (
                  <button
                    ref={live ? effortRowRef : undefined}
                    type="button"
                    onClick={() => go("effort", "forward")}
                    className={NARROW_ROW_CLASS}
                  >
                    <span className="flex-1 text-body font-medium">{t("model.effort")}</span>
                    {effort !== null ? <span className="text-base text-muted">{effortLabel(effort)}</span> : null}
                    <StaticIcon icon={ChevronRight} size={18} className="shrink-0 text-muted" />
                  </button>
                )}
              </div>
              <div className="border-t border-divider px-2 py-1">
                <button
                  ref={live ? moreRowRef : undefined}
                  type="button"
                  onClick={() => go("more", "forward")}
                  className={NARROW_ROW_CLASS}
                >
                  <span className="flex-1 text-body font-medium">{t("model.moreModels")}</span>
                  <StaticIcon icon={ChevronRight} size={18} className="shrink-0 text-muted" />
                </button>
              </div>
              <PriceBlock model={selected} narrow />
            </>
          )}
        </div>
      </>
    );
  };

  return (
    <div className="relative min-h-0 flex-1 overflow-hidden">
      {leaving !== null ? (
        <div
          aria-hidden="true"
          inert
          data-direction={direction}
          onAnimationEnd={() => setLeaving(null)}
          className="motion-screen-leave pointer-events-none absolute inset-0 flex flex-col"
        >
          {render(leaving, false)}
        </div>
      ) : null}
      <div
        key={screen}
        data-screen={screen}
        data-direction={direction}
        className={`absolute inset-0 flex flex-col bg-surface-panel ${navigated ? "motion-screen" : ""}`}
      >
        {render(screen, true)}
      </div>
    </div>
  );
}

/**
 * Man Thinking Effort o 375 px — `role="menu"` + `menuitemradio` nhu menu con
 * desktop (ban E ve cung vai tro). ↑/↓ di giua cac muc.
 */
function EffortScreenItems({
  options,
  effort,
  onPick,
}: {
  options: { id: string }[];
  effort: string | null;
  onPick: (level: string) => void;
}) {
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") {
      return;
    }
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitemradio"]'));
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next = items[(at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length];
    e.preventDefault();
    next?.focus();
  };
  return (
    <div
      role="menu"
      aria-label={t("model.effort")}
      onKeyDown={handleKeyDown}
      className="flex flex-col gap-0.5 px-2 py-1"
    >
      {options.map((o) => {
        const checked = o.id === effort;
        return (
          <button
            key={o.id}
            type="button"
            role="menuitemradio"
            aria-checked={checked}
            onClick={() => onPick(o.id)}
            className="motion-control flex min-h-row-menu cursor-pointer items-center gap-3 rounded-md px-2.5 text-left text-body focus-visible:-outline-offset-2 aria-checked:bg-accent-subtle aria-checked:font-semibold aria-[checked=false]:hover:bg-surface-hover"
          >
            <span className="flex w-4.5 shrink-0 justify-center">
              {checked ? (
                <StaticIcon icon={Check} size={18} strokeWidth={2.25} className="text-accent-text" />
              ) : null}
            </span>
            {effortLabel(o.id)}
          </button>
        );
      })}
    </div>
  );
}

// ─────────────────────────────── goc ───────────────────────────────────────

export function ModelPicker(props: ModelPickerProps) {
  const narrow = useIsNarrow();
  const [open, setOpen] = useState(false);
  const selected = props.models.find((m) => m.id === props.defaultPick.modelId);
  const name = selected?.display_name ?? (props.loading ? t("model.loadingShort") : t("model.trong"));

  /*
    Ban A: chu tron 13 px `muted`; hover va dang mo len nen `surface-hover` +
    chu `foreground`; dang mo chu dam hon va mui ten quay 180° (`motion-icon`).
    Ten truy cap bat dau bang "Chon mo hinh" (an voi mat) roi den dung chu
    dang hien — nhan nhin thay nam tron trong ten (WCAG 2.5.3).
  */
  const trigger = (
    <button
      type="button"
      className="group motion-control flex min-h-touch max-w-full items-center gap-1 rounded-md pr-2 pl-2.5 text-sm font-medium text-muted hover:bg-surface-hover hover:text-foreground data-[state=open]:bg-surface-hover data-[state=open]:font-semibold data-[state=open]:text-foreground"
    >
      <span className="sr-only">{t("model.pickerOpen")} </span>
      <span className="truncate">{name}</span>
      <StaticIcon
        icon={ChevronDown}
        size={14}
        className="motion-icon shrink-0 group-data-[state=open]:rotate-180"
      />
    </button>
  );

  /*
    T-S.4 — moi lan MO bao cho `useModels` biet; no tu quyet co hoi lai hay
    khong (chi khi `checked_at` da cu). Danh sach dang cam van hien va bam
    duoc trong luc cho — khong che, khong skeleton.
  */
  const handleOpenChange = (next: boolean): void => {
    setOpen(next);
    if (next) {
      props.onOpen?.();
    }
  };

  // Chon mot model o bat ky dau → dong ca picker, nut mo doi ten (ban D).
  const pickAndClose = (id: string): void => {
    props.onPick(id);
    setOpen(false);
  };

  if (narrow) {
    return (
      <Dialog.Root open={open} onOpenChange={handleOpenChange}>
        <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="motion-scrim fixed inset-0 z-40 bg-scrim" />
          <Dialog.Content
            aria-describedby={undefined}
            className="motion-sheet fixed inset-x-0 bottom-0 z-50 flex h-sheet-screen max-h-sheet-max flex-col overflow-hidden rounded-t-xl bg-surface-panel text-foreground shadow-popover"
          >
            <div className="flex shrink-0 justify-center pt-2">
              <span aria-hidden="true" className="h-1 w-grabber rounded-full bg-border-strong" />
            </div>
            <SheetScreens {...props} selected={selected} close={() => setOpen(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }

  return (
    <Tooltip.Provider delayDuration={200}>
      <Popover.Root open={open} onOpenChange={handleOpenChange}>
        <Popover.Trigger asChild>{trigger}</Popover.Trigger>
        <Popover.Portal>
          {/* Ban B: neo vao nut mo, `side="top" align="end"`, de len o nhap. */}
          <Popover.Content
            side="top"
            align="end"
            sideOffset={8}
            collisionPadding={16}
            aria-label={t("model.picker")}
            className="motion-popover z-50 w-picker max-w-picker-max rounded-lg border border-border bg-surface-panel text-foreground shadow-popover"
          >
            {selected === undefined ? (
              <EmptyBody loading={props.loading} narrow={false} />
            ) : (
              <>
                <CurrentModel model={selected} tier={props.defaultPick.tier} narrow={false} />
                <div className="border-t border-divider p-1.5">
                  <EffortMenu model={selected} effort={props.effort} onPickEffort={props.onPickEffort} />
                </div>
                <div className="border-t border-divider p-1.5">
                  <MoreModels
                    models={props.models}
                    defaultPick={props.defaultPick}
                    checkedAtLabel={props.checkedAtLabel}
                    refreshing={props.refreshing}
                    onRefresh={props.onRefresh}
                    onPick={pickAndClose}
                  />
                </div>
                <PriceBlock model={selected} narrow={false} />
              </>
            )}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </Tooltip.Provider>
  );
}
