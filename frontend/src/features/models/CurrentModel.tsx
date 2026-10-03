/**
 * Khoi ① "Dang dung" cua Model Picker v2 — T-S.14, ban T-HD4-v2 muc B, E, F.
 *
 * KH tham chieu: §24.2b·S11 (khoi 1), UC-05, T-3.6 · NQ-120.
 *
 * *"Model hien tai — ten, provider hien thi, badge, capability, va tang mac
 * dinh dang ap dung (hoi thoai › tai khoan › catalog, T-3.6). Moi mo ta cua
 * v1 giu nguyen."* Tang KHONG con in duoi nut mo (ban A: "Nut chi la ten
 * model") — no o day.
 */

import type { ModelOut } from "../../lib/api";
import { VISION } from "./chips";
import { t } from "../../lib/i18n";
import type { DefaultTier } from "./defaults";
import { CapabilityChips, SectionLabel, TierChip, TierRail } from "./chips";

export function CurrentModel({
  model,
  tier,
  narrow,
  conversationHasImages = false,
}: {
  model: ModelOut;
  tier: DefaultTier | null;
  narrow: boolean;
  /** T-4.5 — hoi thoai dang mo da co anh (duong di, `attachments[].kind`). */
  conversationHasImages?: boolean;
}) {
  const warnNoVision = conversationHasImages && !model.capabilities.includes(VISION);
  return (
    <div className={`flex flex-col gap-2.5 ${narrow ? "px-4 pt-2.5 pb-3" : "p-3"}`}>
      <SectionLabel>{t("model.inUse")}</SectionLabel>
      <div className="flex items-stretch gap-2.5">
        <TierRail tier={tier} />
        <div className="flex min-w-0 flex-1 flex-col gap-1.25">
          <div className={`flex flex-wrap items-baseline ${narrow ? "gap-1.5" : "gap-2"}`}>
            <span className="text-body/5.5 font-semibold wrap-anywhere">{model.display_name}</span>
            {model.badge ? (
              <span className="rounded-full border border-border-strong px-2 py-px text-2xs font-medium">
                {model.badge}
              </span>
            ) : null}
          </div>
          <span className="text-xs text-muted">{model.provider}</span>
          <CapabilityChips capability={model.capabilities} filled={!narrow} />
          {/* 375 px: chip tang xuong dong duoi capability (ban E, F). */}
          {narrow && tier ? <TierChip tier={tier} className="self-start" /> : null}
        </div>
        {!narrow && tier ? (
          <div className="shrink-0">
            <TierChip tier={tier} />
          </div>
        ) : null}
      </div>
      <p className="text-2xs text-muted">{t("model.tierOrder")}</p>
      {/*
        T-4.5 — canh bao "model nay khong co vision ma hoi thoai da co anh".
        `empty:hidden`: khong canh bao thi khong chiem mot pixel nao. Anh o
        luot cu khong chan gui (backend thay no bang chu, T-4.4b) — chi bao.
      */}
      <div data-slot="capability-warning" aria-live="polite" className="empty:hidden text-xs text-danger-text">
        {warnNoVision ? t("model.noVisionWithImages") : null}
      </div>
    </div>
  );
}
