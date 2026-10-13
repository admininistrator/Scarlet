import * as Dialog from "@radix-ui/react-dialog";
import * as Popover from "@radix-ui/react-popover";
import * as Tooltip from "@radix-ui/react-tooltip";
import { ChevronDown, ChevronUp, CircleAlert, LoaderCircle, Lock, RotateCcw, SquareTerminal, X, Zap } from "lucide";
import {
  forwardRef,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type ReactNode,
  type RefObject,
} from "react";

import { useSkills, type SkillRowStatus, type SkillsState } from "../../features/chat/useSkills";
import type { Skill } from "../../lib/api";
import { t } from "../../lib/i18n";
import { ISLAND_COMPACT_QUERY } from "../../lib/motion";
import { useMediaQuery } from "../../lib/viewport";
import { Icon, StaticIcon } from "../ui/Icon";

/**
 * Panel chon skill — T-7.9, ban T-HD11 · v1 (`SkillPicker.tsx`). Nguoi dung
 * bat / tat skill cho CHINH MINH (UC-09 dong 1, 3).
 *
 *   ≥ 640  Popover neo tren KHUNG o nhap (`anchorRef`), side top, align start,
 *          cach 8; khong nen mo, khong nhot focus. Esc / bam ngoai ⇒ dong,
 *          focus ve nut ⚡ (Radix).
 *   < 640  Dialog dang sheet day (lo Model Picker): tay nam, nut dong 44, nen mo.
 *
 * Lech ban ve (B-411): ① ban ve dua khung o nhap vao `frame(skillButton)` de
 * boc `Popover.Anchor asChild`; o day neo bang `virtualRef` — cung cho neo,
 * `Composer` khong phai tach JSX. ② Nhan "Chua duoc chay code" van tren tung
 * hang, nhung CAU giai thich gom thanh MOT dong o dau danh sach thay cho
 * tooltip (desktop) / cau duoi tung hang (< 640): ca bon skill dung san deu
 * `requires_execution` va phan lon tai khoan khong co quyen ⇒ bon cau giong
 * het nhau. Cong tac van bat duoc (model van doc huong dan — ban ve).
 */

const ICON_BUTTON =
  "motion-press grid size-touch shrink-0 place-items-center rounded-md text-muted hover:bg-surface-hover hover:text-foreground";
const TOOLTIP =
  "motion-popover z-50 max-w-tooltip rounded-md bg-surface-tooltip px-2.5 py-1.5 text-xs text-tooltip-foreground shadow-popover";

const isExecBlocked = (skill: Skill, canExecute: boolean) => skill.requires_execution && !canExecute;

/** Nut ⚡: 0 bat nhu nut thuong; ≥ 1 theo lo cong tac Tim web dang bat + so dem. */
const SkillButton = forwardRef<HTMLButtonElement, { count: number } & ComponentPropsWithoutRef<"button">>(
  function SkillButton({ count, className, ...rest }, ref) {
    const isOn = count > 0;
    return (
      <button
        ref={ref}
        type="button"
        {...rest}
        className={`motion-press inline-flex h-touch min-w-touch shrink-0 items-center justify-center gap-1 rounded-md border ${
          isOn
            ? "border-accent bg-accent-subtle pr-2.5 pl-2 text-accent-text"
            : "border-transparent text-muted hover:bg-surface-hover hover:text-foreground data-[state=open]:bg-surface-hover data-[state=open]:text-foreground"
        } ${className ?? ""}`}
      >
        <StaticIcon icon={Zap} size={20} />
        <span className="sr-only">{t("composer.skill")}</span>
        {isOn && (
          <>
            {/* Khoang trang: ten doc "Chọn skill 4 đang bật", khong dinh lien (flex bo qua khi ve). */}{" "}
            <span key={count} className="motion-count tabular text-sm font-semibold">
              {count}
            </span>{" "}
            <span className="sr-only">{t("composer.skill.enabledSuffix")}</span>
          </>
        )}
      </button>
    );
  },
);

export function SkillPicker({
  anchorRef,
  canExecuteSkills,
}: {
  /** Khung o nhap — popover neo vao day, khong vao nut ⚡ (ban ve: khong che chu dang go). */
  anchorRef: RefObject<HTMLElement | null>;
  canExecuteSkills: boolean;
}) {
  const skills = useSkills();
  const isCompact = useMediaQuery(ISLAND_COMPACT_QUERY);
  const [isOpen, setIsOpen] = useState(false);
  const titleId = useId();
  const openChange = (open: boolean) => {
    setIsOpen(open);
    if (open) {
      skills.reload(true);
    }
  };
  const body = (closeButton?: ReactNode) => (
    <SkillPanelBody
      skills={skills}
      canExecute={canExecuteSkills}
      titleId={titleId}
      isCompact={isCompact}
      closeButton={closeButton}
    />
  );
  const trigger = (Trigger: typeof Popover.Trigger | typeof Dialog.Trigger) => (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root open={isOpen ? false : undefined}>
        <Tooltip.Trigger asChild>
          <Trigger asChild>
            <SkillButton count={skills.count} />
          </Trigger>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content side="top" sideOffset={8} className={TOOLTIP}>
            {t("composer.skill")}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );

  if (isCompact) {
    return (
      <Dialog.Root open={isOpen} onOpenChange={openChange}>
        {trigger(Dialog.Trigger)}
        <Dialog.Portal>
          <Dialog.Overlay className="motion-scrim fixed inset-0 z-40 bg-scrim" />
          <Dialog.Content
            aria-labelledby={titleId}
            aria-describedby={undefined}
            className="motion-sheet fixed inset-x-0 bottom-(--keyboard-inset) z-50 flex max-h-skill-sheet-max flex-col overflow-hidden rounded-t-xl bg-surface-panel pb-[env(safe-area-inset-bottom)] text-foreground shadow-popover"
          >
            <div className="flex shrink-0 justify-center pt-2">
              <span aria-hidden="true" className="h-1 w-grabber rounded-full bg-border-strong" />
            </div>
            {body(
              <Dialog.Close aria-label={t("composer.skill.close")} className={`${ICON_BUTTON} -mt-1.5 -mr-1`}>
                <StaticIcon icon={X} size={20} />
              </Dialog.Close>,
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }

  return (
    <Popover.Root open={isOpen} onOpenChange={openChange}>
      <Popover.Anchor virtualRef={anchorRef as RefObject<HTMLElement>} />
      {trigger(Popover.Trigger)}
      <Popover.Portal>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={8}
          collisionPadding={16}
          aria-labelledby={titleId}
          className="motion-menu-up z-50 flex max-h-[min(var(--spacing-skill-panel-max),var(--radix-popover-content-available-height))] w-skill-panel max-w-[calc(100vw-2*var(--spacing-island-gap))] flex-col overflow-hidden rounded-lg border border-border bg-surface-panel text-foreground shadow-popover"
        >
          {body()}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function SkillPanelBody({
  skills,
  canExecute,
  titleId,
  isCompact,
  closeButton,
}: {
  skills: SkillsState;
  canExecute: boolean;
  titleId: string;
  isCompact: boolean;
  closeButton?: ReactNode;
}) {
  const { list, rows, count } = skills;
  const blockedId = useId();
  const Title = isCompact ? Dialog.Title : "h2";
  const anyBlocked = list.status === "ready" && list.items.some((s) => isExecBlocked(s, canExecute));
  return (
    <>
      <header
        className={`flex shrink-0 items-start gap-2 border-b border-divider pb-3 pl-4 ${isCompact ? "pt-1 pr-2" : "pt-3.5 pr-3"}`}
      >
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-h-7 items-center gap-2">
            <Title id={titleId} className="text-lg font-semibold">
              {t("composer.skill.title")}
            </Title>
            {list.status === "ready" && list.items.length > 0 && (
              <span
                className={`inline-flex h-5.5 items-center gap-1 rounded-full px-2 text-xs font-semibold ${
                  count > 0 ? "bg-accent-subtle text-accent-text" : "bg-surface-hover text-muted"
                }`}
              >
                <span className="tabular">{count}</span>
                <span>{t("composer.skill.enabledSuffix")}</span>
              </span>
            )}
          </div>
          <p className="text-sm text-pretty text-muted">
            <span>{t("composer.skill.intro")}</span> <span>{t("composer.skill.scope")}</span>
          </p>
        </div>
        {closeButton}
      </header>

      {list.status === "loading" && <LoadingRows />}

      {list.status === "error" && (
        <div role="alert" className="flex flex-col items-center gap-1 px-6 py-8 text-center">
          <StaticIcon icon={CircleAlert} size={24} className="mb-1 text-danger-text" />
          <p className="text-base font-semibold">{t("composer.skill.loadError")}</p>
          <p className="text-sm text-muted">{t("composer.skill.loadErrorHint")}</p>
          <button
            type="button"
            onClick={() => skills.reload()}
            className="motion-press mt-3 inline-flex min-h-touch items-center gap-1.5 rounded-md border border-border-strong bg-surface-panel px-3.5 text-base font-semibold text-foreground hover:bg-surface-hover"
          >
            <StaticIcon icon={RotateCcw} size={16} />
            {t("composer.skill.retry")}
          </button>
        </div>
      )}

      {list.status === "ready" && list.items.length === 0 && (
        <div className="flex flex-col items-center gap-1 px-6 py-8 text-center">
          <StaticIcon icon={Zap} size={28} className="mb-1 text-muted" />
          <p className="text-base font-semibold">{t("composer.skill.empty")}</p>
          <p className="max-w-64 text-sm text-pretty text-muted">{t("composer.skill.emptyHint")}</p>
        </div>
      )}

      {anyBlocked && (
        <p
          id={blockedId}
          className="flex shrink-0 items-start gap-1.5 border-b border-divider bg-warning-subtle px-4 py-2 text-xs text-pretty text-warning-text"
        >
          <StaticIcon icon={Lock} size={14} className="mt-0.5 shrink-0" />
          {t("composer.skill.execBlockedHint")}
        </p>
      )}

      {list.status === "ready" && list.items.length > 0 && (
        <ul aria-label={t("composer.skill.list")} className="scroll-fade-y flex-1">
          {list.items.map((s) => (
            <SkillRow
              key={s.name}
              skill={s}
              status={rows[s.name] ?? "idle"}
              blockedId={isExecBlocked(s, canExecute) ? blockedId : null}
              onToggle={() => void skills.toggle(s.name)}
            />
          ))}
        </ul>
      )}
    </>
  );
}

function LoadingRows() {
  return (
    <div aria-busy="true" className="flex-1">
      <p role="status" className="sr-only">
        {t("composer.skill.loading")}
      </p>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          aria-hidden="true"
          className="motion-pulse flex items-start gap-3 border-t border-divider py-4 pr-3 pl-4 first:border-t-0"
        >
          <div className="flex flex-1 flex-col gap-2.5">
            <span className="h-3 w-28 rounded-full bg-surface-code" />
            <span className="h-2.5 w-full rounded-full bg-surface-code" />
            <span className="h-2.5 w-3/4 rounded-full bg-surface-code" />
          </div>
          <span className="h-6 w-10 rounded-full bg-surface-code" />
        </div>
      ))}
    </div>
  );
}

function SkillRow({
  skill,
  status,
  blockedId,
  onToggle,
}: {
  skill: Skill;
  status: SkillRowStatus;
  /** `id` cua dong giai thich o dau danh sach khi skill can chay code ma tai khoan chua duoc; khong thi `null`. */
  blockedId: string | null;
  onToggle: () => void;
}) {
  const nameId = useId();
  const descId = useId();
  const descRef = useRef<HTMLParagraphElement>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isClamped, setIsClamped] = useState(false);

  // "Xem them" chi khi mo ta THAT SU bi cat o 2 dong — do, khong doan theo so ky tu.
  useLayoutEffect(() => {
    const el = descRef.current;
    if (el === null || isExpanded) {
      return;
    }
    const measure = () => setIsClamped(el.scrollHeight > el.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [skill.description, isExpanded]);

  const hasMeta = skill.requires_execution || isClamped || isExpanded;
  return (
    <li className="flex items-start gap-3 border-t border-divider py-3 pr-2 pl-4 first:border-t-0">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex min-h-5.5 items-baseline gap-2">
          <span id={nameId} className="max-w-full shrink-0 truncate text-base font-semibold">
            {skill.display_name}
          </span>
          <span className="min-w-0 truncate font-mono text-xs text-muted">{skill.name}</span>
          <span role="status" className="ml-auto flex shrink-0 items-center gap-1.5 self-center text-xs text-muted">
            {status === "saving" && (
              <>
                <span aria-hidden="true" className="motion-spin grid place-items-center">
                  <StaticIcon icon={LoaderCircle} size={14} />
                </span>
                {t("composer.skill.saving")}
              </>
            )}
          </span>
        </div>

        <p
          ref={descRef}
          id={descId}
          lang="en"
          className={`text-sm text-pretty break-words text-muted ${isExpanded ? "" : "line-clamp-2"}`}
        >
          {skill.description}
        </p>

        {hasMeta && (
          <div className="mt-0.5 flex min-h-7 flex-wrap items-center gap-x-2">
            {skill.requires_execution &&
              (blockedId === null ? (
                <span className="inline-flex h-6 items-center gap-1 rounded-full border border-border px-2 text-xs font-medium text-muted">
                  <StaticIcon icon={SquareTerminal} size={12} />
                  {t("composer.skill.exec")}
                </span>
              ) : (
                <span className="inline-flex h-6 items-center gap-1 rounded-full border border-warning bg-warning-subtle px-2 text-xs font-medium text-warning-text">
                  <StaticIcon icon={Lock} size={12} />
                  {t("composer.skill.execBlocked")}
                </span>
              ))}
            {(isClamped || isExpanded) && (
              <button
                type="button"
                aria-expanded={isExpanded}
                aria-controls={descId}
                onClick={() => setIsExpanded((v) => !v)}
                className="motion-control -mx-1.5 -my-2 inline-flex min-h-touch items-center gap-1 rounded-md px-1.5 text-xs font-semibold text-foreground hover:bg-surface-hover"
              >
                <Icon icon={isExpanded ? ChevronUp : ChevronDown} spring="skillDescToggle" size={14} />
                {isExpanded ? t("composer.skill.less") : t("composer.skill.more")}
              </button>
            )}
          </div>
        )}

        {(status === "error" || status === "gone") && (
          <p role="alert" className="motion-enter mt-1 flex items-center gap-1.5 text-xs font-medium text-danger-text">
            <StaticIcon icon={CircleAlert} size={14} />
            {t(status === "error" ? "composer.skill.saveError" : "composer.skill.gone")}
          </p>
        )}
      </div>

      {/* Cong tac cua Admin: ranh 40 × 24 trong vung 44 × 44. Dang luu: aria-busy, KHONG mo. */}
      <button
        type="button"
        role="switch"
        aria-checked={skill.enabled}
        aria-labelledby={nameId}
        aria-describedby={blockedId === null ? descId : `${descId} ${blockedId}`}
        aria-busy={status === "saving" || undefined}
        disabled={status === "gone"}
        onClick={() => {
          if (status !== "saving") {
            onToggle();
          }
        }}
        className="motion-press control-disabled -mt-2.5 grid size-touch shrink-0 place-items-center rounded-md aria-busy:cursor-progress"
      >
        <span
          className={`motion-switch flex h-6 w-10 items-center rounded-full border p-0.5 ${
            skill.enabled ? "border-accent bg-accent" : "border-border-strong bg-background"
          }`}
        >
          <span
            className={`size-5 rounded-full ${skill.enabled ? "translate-x-3.5 bg-accent-foreground" : "scale-80 bg-border-strong"}`}
          />
        </span>
      </button>
    </li>
  );
}
