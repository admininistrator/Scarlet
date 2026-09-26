/**
 * Rail tang, chip tang, chip capability — dung chung cho khoi ① "Dang dung"
 * va danh sach "More models" cua Model Picker v2 (T-S.14, ban T-HD4-v2 muc
 * B, D, E, F).
 *
 * Tach khoi `ModelPicker.tsx` vi CUNG mot hang model hien o hai cho (khoi ①
 * va danh sach) va ban ve giu nguyen luat v1 cho ca hai: rail bao TANG nao
 * dat ra model, dau tich bao model NAO dang chon — hai thong tin khac nhau.
 */

import { t, type TextKey } from "../../lib/i18n";
import type { DefaultPick, DefaultTier } from "./defaults";

/**
 * Bon capability cua §9.4 → khoa chuoi trong `vi.json`.
 *
 * Catalog la file sua nong, nen mot capability la (hoac mot cai moi cua §9.4
 * chua co ban dich) phai hien duoc chu khong duoc lam vo hang: `capabilityLabel`
 * roi ve chinh chuoi tho.
 */
const CAPABILITY_LABELS: Record<string, TextKey> = {
  tools: "model.cap.tools",
  vision: "model.cap.vision",
  reasoning: "model.cap.reasoning",
  attachments: "model.cap.attachments",
};

const TIER_LABELS: Record<DefaultTier, TextKey> = {
  conversation: "model.tierConversation",
  account: "model.tierAccount",
  catalog: "model.tierCatalog",
};

function capabilityLabel(capability: string): string {
  const key = CAPABILITY_LABELS[capability];
  return key === undefined ? capability : t(key);
}

/** Tang da dat `modelId` ra — `null` khi khong tang nao (model thuong). */
export function tierOf(modelId: string, defaultPick: DefaultPick): DefaultTier | null {
  if (modelId === defaultPick.byTier.conversation) {
    return "conversation";
  }
  if (modelId === defaultPick.byTier.account) {
    return "account";
  }
  if (modelId === defaultPick.byTier.catalog) {
    return "catalog";
  }
  return null;
}

/** Thanh doc ben trai hang — bao tang mac dinh, khong bao "dang chon". */
export function TierRail({ tier }: { tier: DefaultTier | null }) {
  const tone =
    tier === "conversation"
      ? "bg-accent"
      : tier === "account"
        ? "border border-accent-text"
        : tier === "catalog"
          ? "bg-border-strong"
          : "";
  return <span aria-hidden="true" className={`w-rail shrink-0 self-stretch rounded-full ${tone}`} />;
}

/** Chip "Mac dinh hoi thoai / tai khoan / catalog". */
export function TierChip({ tier, className = "" }: { tier: DefaultTier; className?: string }) {
  const tone =
    tier === "conversation"
      ? "bg-accent font-semibold text-accent-foreground"
      : tier === "account"
        ? "border border-accent-text font-semibold text-accent-text"
        : "border border-border font-medium text-muted";
  return (
    <span className={`rounded-full px-2 py-px text-2xs whitespace-nowrap ${tone} ${className}`}>
      {t(TIER_LABELS[tier])}
    </span>
  );
}

/**
 * Chip capability. `filled` = nen `background` — ban T-HD4-v2 chi to nen o
 * khoi ① desktop (muc B); trong danh sach va o 375 px chip khong co nen.
 * `locked` = hang khoa: chip an theo mau `disabled-foreground` cua hang.
 *
 * Model khong co capability nao: mot dong chu thay cho hang chip rong.
 */
export function CapabilityChips({
  capability,
  filled = false,
  locked = false,
}: {
  capability: string[];
  filled?: boolean;
  locked?: boolean;
}) {
  if (capability.length === 0) {
    return <span className={`text-xs ${locked ? "" : "text-muted"}`}>{t("model.capNone")}</span>;
  }
  return (
    <ul className="flex flex-wrap items-center gap-1">
      {capability.map((name) => (
        <li
          key={name}
          className={`rounded-sm border border-border px-1.5 py-px text-2xs font-medium ${locked ? "" : "text-muted"} ${filled ? "bg-background" : ""}`}
        >
          {capabilityLabel(name)}
        </li>
      ))}
    </ul>
  );
}

/** Nhan khoi (11 px, chu hoa) — "Dang dung", "Gia". */
export function SectionLabel({ children }: { children: string }) {
  return <span className="text-2xs font-semibold tracking-wider text-muted uppercase">{children}</span>;
}
