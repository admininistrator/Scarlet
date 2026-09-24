import * as Tooltip from "@radix-ui/react-tooltip";
import { FileText, Image, Paperclip, X } from "lucide";

import { DISPLAY_LOCALE, t } from "../../lib/i18n";
import { StaticIcon } from "../ui/Icon";

/**
 * Hai thanh phan cua o nhap DUNG SAN, CHUA MOUNT — T-S.10, §7b.2, NQ-121.
 *
 * KH tham chieu: §24.2b·S12, S15 (P4) · ban T-HD2-v2 muc G6, G7.
 *
 * Chua co du lieu nao de chung hien: duong ong anh/tep la T-4.1–T-4.3, nut
 * dinh kem that la T-4.7, trang thai "model khong doc duoc anh" bat o T-4.5.
 * Chung co mat o day de P4 chi con viec GAN (mount trong hop nhap cua
 * `Composer`, tren textarea) chu khong ve lai o nhap — va co test render voi
 * fixture de hinh dang khong muc di trong luc cho.
 *
 * Ten tep di vao JSX nhu CHU (React tu thoat), khong bao gio qua
 * `dangerouslySetInnerHTML`: ten do nguoi dung dat, va ngay no la du lieu that
 * thi no la du lieu khong tin cay.
 */

export type PendingAttachment = {
  id: string;
  kind: "image" | "file";
  name: string;
  bytes: number;
  /** URL xem truoc do trinh duyet tao (`blob:`) — P4 cap; vang mat ⇒ icon. */
  previewUrl?: string;
};

const KILO = 1024;

/** `2516582` → `"2,4 MB"`, theo locale hien thi (ban ve G6). */
export function formatBytes(bytes: number): string {
  const units = ["byte", "kilobyte", "megabyte", "gigabyte"] as const;
  let value = bytes;
  let unit = 0;
  while (value >= KILO && unit < units.length - 1) {
    value /= KILO;
    unit += 1;
  }
  return new Intl.NumberFormat(DISPLAY_LOCALE, {
    style: "unit",
    unit: units[unit],
    unitDisplay: "short",
    maximumFractionDigits: 1,
  }).format(value);
}

/**
 * Khay xem truoc tep TRUOC khi gui (T-4.7) — nam trong hop nhap, tren
 * textarea. Anh 56 × 56; chip tep cao 56, rong toi da 240, ten cat bang dau
 * "…". Nut xoa tren anh VE 20 px nhung vung cham 44 × 44 tran ra goc.
 */
export function AttachmentPreviews({
  items,
  onRemove,
}: {
  items: PendingAttachment[];
  onRemove: (id: string) => void;
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <ul aria-label={t("composer.attachments")} data-planned="T-4.7" className="flex flex-wrap gap-2 px-2.5 pt-2.5">
      {items.map((item) =>
        item.kind === "image" ? (
          <li
            key={item.id}
            className="relative grid size-attachment shrink-0 place-items-center rounded-md border border-border bg-surface-code text-muted"
          >
            {item.previewUrl === undefined ? (
              <StaticIcon icon={Image} size={20} />
            ) : (
              <img src={item.previewUrl} alt={item.name} className="size-full rounded-md object-cover" />
            )}
            <button
              type="button"
              aria-label={`${t("composer.removeAttachment")} — ${item.name}`}
              onClick={() => onRemove(item.id)}
              className="absolute -top-3 -right-3 grid size-touch place-items-center"
            >
              <span className="grid size-5 place-items-center rounded-full bg-foreground text-background">
                <StaticIcon icon={X} size={12} strokeWidth={2.5} />
              </span>
            </button>
          </li>
        ) : (
          <li
            key={item.id}
            className="flex h-attachment max-w-60 min-w-0 flex-[0_1_auto] items-center gap-2.5 rounded-md border border-border bg-background pl-2.5"
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-sm bg-danger-subtle text-danger-text">
              <StaticIcon icon={FileText} size={18} />
            </span>
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-medium">{item.name}</span>
              <span className="tabular text-xs text-muted">{formatBytes(item.bytes)}</span>
            </span>
            <button
              type="button"
              aria-label={`${t("composer.removeAttachment")} — ${item.name}`}
              onClick={() => onRemove(item.id)}
              className="motion-control grid size-touch shrink-0 place-items-center rounded-md text-muted hover:text-foreground"
            >
              <StaticIcon icon={X} size={16} />
            </button>
          </li>
        ),
      )}
    </ul>
  );
}

/**
 * Nut dinh kem khi model dang chon KHONG doc duoc anh (T-4.5, ban ve G7).
 *
 * Mo nhu nut cho, nhung tooltip noi LY DO cu the thay cho "Sap co" — nen no
 * khong phai `ComingSoon`. `aria-disabled` chu khong `disabled`, cung ly do
 * voi `ComingSoon`: tooltip phai toi duoc nguoi dung ban phim.
 */
export function AttachButtonNoVision() {
  return (
    <Tooltip.Provider>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            aria-disabled="true"
            aria-label={t("composer.attach")}
            data-planned="T-4.5"
            className="control-disabled inline-flex size-touch shrink-0 items-center justify-center rounded-md text-muted"
          >
            <StaticIcon icon={Paperclip} size={20} />
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className="motion-popover z-50 rounded-md bg-surface-tooltip px-2.5 py-1.5 text-xs text-tooltip-foreground shadow-popover">
            {t("composer.noVision")}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
