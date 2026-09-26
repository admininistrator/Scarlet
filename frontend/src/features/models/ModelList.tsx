/**
 * Danh sach "More models ›" — T-S.14, ban T-HD4-v2 muc D (desktop) va E (màn
 * thu ba cua sheet 375 px).
 *
 * KH tham chieu: §24.2b·S11, UC-05, RR-5 · tasks.md T-3.6 (DoD dong 3, Cam bay
 * ③), T-S.4.
 *
 * Ban ve: *"Danh sach = danh sach v1 (hang 64 px, rail + chip tang, ✓ cho
 * model dang chon, strip 'Trang thai kiem luc' + nut kiem lai 44 × 44)"*. Vi
 * vay file nay giu nguyen hai luat cua v1:
 *
 * ── Hang khoa: `aria-disabled`, KHONG phai `disabled` ─────────────────────
 *
 * Hang khong dung duoc giu nguyen `tabIndex 0` va van focus duoc — nguoi dung
 * ban phim phai DOC duoc ly do. `disabled` se lam hang bien mat khoi tab
 * order va khoi screen reader, tuc giau di dung cau can noi.
 *
 * "Khong chon duoc" la that chu khong chi la mo di: hang khoa **khong gan**
 * `onClick`/`onKeyDown` (Cam bay ③ cua T-3.6). FE khong phai lop bao ve — lop
 * do la lan goi model — nhung no cung khong duoc tu mau thuan.
 *
 * ── Ly do khoa: tooltip o desktop, nam THANG trong hang o 375 px ──────────
 *
 * Khong co hover thi khong co tooltip. Ly do la mot cau dai khong doan truoc
 * (ban ve do 150+ ky tu), nen tooltip rong `max-w-tooltip` va xuong dong.
 */

import * as Tooltip from "@radix-ui/react-tooltip";
import { Check, RotateCw } from "lucide";

import type { ModelOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { StaticIcon } from "../../components/ui/Icon";
import type { DefaultPick, DefaultTier } from "./defaults";
import { CapabilityChips, TierChip, TierRail, tierOf } from "./chips";

/**
 * Khoang tu mep mot HANG toi lop mo sang ben canh (menu con ②, danh sach ③,
 * tooltip ly do): 6 (dem `p-1.5` quanh hang) + 1 (vien bang) + 8 (khe ban
 * C/D/F ve giua mep bang va lop con — 424 − 416, 816 − 808). Radix do
 * `sideOffset` tu hop cua NUT mo (chinh hang), va voi tooltip la tu mui ten.
 */
export const SIDE_LAYER_OFFSET = 15;

export function StatusStrip({
  checkedAtLabel,
  refreshing,
  narrow,
  onRefresh,
}: {
  checkedAtLabel: string;
  refreshing?: boolean;
  narrow: boolean;
  onRefresh: () => void;
}) {
  return (
    <div
      className={`flex shrink-0 items-center justify-between gap-2 border-b border-divider pr-1.5 ${narrow ? "pl-4" : "pl-3"}`}
    >
      <p className="min-w-0 text-xs text-muted">
        <span>{t("model.checkedAtPrefix")}</span>{" "}
        <span className="tabular font-medium text-foreground">{checkedAtLabel}</span>
      </p>
      <button
        type="button"
        onClick={onRefresh}
        aria-label={refreshing ? t("model.refreshing") : t("model.refresh")}
        aria-busy={refreshing || undefined}
        className="motion-press flex size-touch shrink-0 items-center justify-center rounded-md text-muted hover:bg-surface-hover hover:text-foreground"
      >
        <StaticIcon
          icon={RotateCw}
          size={18}
          strokeWidth={1.75}
          className={refreshing ? "motion-spin" : undefined}
        />
      </button>
    </div>
  );
}

function ModelRow({
  model,
  tier,
  selected,
  narrow,
  onPick,
}: {
  model: ModelOut;
  tier: DefaultTier | null;
  selected: boolean;
  narrow: boolean;
  onPick: (modelId: string) => void;
}) {
  const locked = !model.available;
  const reasonId = `${model.id}-reason`;

  const row = (
    <li
      role="option"
      aria-selected={selected}
      aria-disabled={locked || undefined}
      /*
        CHI o nhanh hep, vi chi o do cau ly do co that trong DOM. O desktop
        no nam trong tooltip — thu chua ton tai khi tooltip dong — nen mot
        `aria-describedby` co dinh se tro vao mot `id` khong co that suot
        thoi gian con lai. Duong desktop de Radix tu gan.

        SPREAD CO DIEU KIEN chu khong `? reasonId : undefined`: `Tooltip.Trigger
        asChild` gop props bang `{...slotProps, ...childProps}`, nen mot
        `aria-describedby: undefined` viet ro se GHI DE gia tri Radix vua dat.
      */
      {...(locked && narrow ? { "aria-describedby": reasonId } : {})}
      tabIndex={0}
      // Cam bay ③ — hang khoa KHONG co duong nao vao `onPick`, ke ca ban phim.
      onClick={locked ? undefined : () => onPick(model.id)}
      onKeyDown={
        locked
          ? undefined
          : (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onPick(model.id);
              }
            }
      }
      className={`motion-control flex min-h-row-model shrink-0 items-stretch gap-2.5 rounded-md p-2 focus-visible:-outline-offset-2 ${
        locked
          ? "cursor-not-allowed bg-surface-disabled text-disabled-foreground"
          : selected
            ? "cursor-pointer bg-accent-subtle"
            : "cursor-pointer hover:bg-surface-hover"
      }`}
    >
      <TierRail tier={tier} />
      <span className="w-4 shrink-0 pt-0.75 text-accent-text">
        {selected ? <StaticIcon icon={Check} size={16} strokeWidth={2.25} /> : null}
      </span>
      <span className={`flex min-w-0 flex-1 flex-col ${locked && narrow ? "gap-1.25" : "gap-1"}`}>
        <span className={`flex flex-wrap items-baseline ${narrow ? "gap-1.5" : "gap-2"}`}>
          <span className="text-base font-semibold">{model.display_name}</span>
          {model.badge ? (
            <span className="rounded-full border border-border-strong px-2 py-px text-2xs font-medium">
              {model.badge}
            </span>
          ) : null}
        </span>
        <span className={`text-xs ${locked ? "" : "text-muted"}`}>{model.provider}</span>
        {locked && narrow ? (
          <span className="flex items-center gap-1.5">
            <CapabilityChips capability={model.capabilities} locked />
            <LockedLabel />
          </span>
        ) : (
          <CapabilityChips capability={model.capabilities} locked={locked} />
        )}
        {/* 375 px: chip tang xuong dong duoi capability (ban E). */}
        {narrow && tier ? <TierChip tier={tier} className="self-start" /> : null}
        {locked && narrow ? (
          <span
            id={reasonId}
            className="rounded-sm border border-border bg-background px-2 py-1.5 text-xs break-words text-muted"
          >
            {model.unavailable_reason}
          </span>
        ) : null}
      </span>
      {!narrow && (tier || locked) ? (
        <span className="flex shrink-0 flex-col items-end gap-1">
          {tier ? <TierChip tier={tier} /> : null}
          {locked ? <LockedLabel /> : null}
        </span>
      ) : null}
    </li>
  );

  if (!locked || narrow) {
    return row;
  }
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{row}</Tooltip.Trigger>
      <Tooltip.Portal>
        {/* Danh sach nam BEN TRAI bang chon (ban D) ⇒ tooltip mo sang trai. */}
        <Tooltip.Content
          side="left"
          align="start"
          sideOffset={SIDE_LAYER_OFFSET}
          collisionPadding={16}
          className="motion-popover z-50 max-w-tooltip rounded-md bg-surface-tooltip px-3 py-2 text-xs leading-relaxed break-words text-tooltip-foreground shadow-popover"
        >
          {model.unavailable_reason}
          <Tooltip.Arrow className="fill-surface-tooltip" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function LockedLabel() {
  return (
    <span className="text-2xs font-semibold tracking-wide whitespace-nowrap uppercase">
      {t("model.unavailable")}
    </span>
  );
}

export function ModelList({
  models,
  defaultPick,
  narrow,
  onPick,
  className = "",
}: {
  models: ModelOut[];
  defaultPick: DefaultPick;
  narrow: boolean;
  onPick: (modelId: string) => void;
  className?: string;
}) {
  return (
    <ul role="listbox" aria-label={t("model.listLabel")} className={`flex flex-col gap-0.5 ${className}`}>
      {models.map((m) => (
        <ModelRow
          key={m.id}
          model={m}
          tier={tierOf(m.id, defaultPick)}
          selected={m.id === defaultPick.modelId}
          narrow={narrow}
          onPick={onPick}
        />
      ))}
    </ul>
  );
}
