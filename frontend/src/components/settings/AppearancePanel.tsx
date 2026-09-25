import { Monitor, Moon, Sun, type IconNode } from "lucide";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { t, type TextKey } from "../../lib/i18n";
import { StaticIcon } from "../ui/Icon";
import {
  onThemeChange,
  resolveTheme,
  saveThemePreference,
  showTheme,
  storedPreference,
  type ThemePreference,
} from "../ui/ThemeToggle";
import { SaveRow } from "./SaveRow";

/**
 * Tab Giao dien — T-S.11, ban T-HD9 B. Chot 2026-09-26: ba lua chon + nut Luu,
 * luu trong `localStorage` cua trinh duyet (PUT /settings khong co truong theme).
 *
 * KH tham chieu: §19.1 · tasks.md T-0.10, T-3.2, T-3.12, T-S.11.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  CHON = XEM TRUOC · LUU = GHI · ROI TAB CHUA LUU = TRA VE BAN DA LUU   ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Ban ve: *"Giao dien doi ngay khi chon de ban xem truoc. Bam Luu de giu lua
 * chon cho nhung lan dang nhap sau."* Chon mot the ⇒ `showTheme` (doi trang,
 * KHONG ghi); Luu ⇒ `saveThemePreference` (`system` = xoa khoa). Unmount ma
 * chua luu ⇒ hien lai lua chon DA LUU, nen mot lan xem thu khong dinh lai.
 *
 * Nut o header van doi-va-luu ngay nhu T-0.10. Bam no trong luc dang o tab
 * nay ⇒ lua chon da luu doi ⇒ tab theo (`onThemeChange`), khong giu mot ban
 * xem truoc da cu.
 */

export const THEME_LABEL: Record<ThemePreference, TextKey> = {
  system: "appearance.system",
  light: "theme.light",
  dark: "theme.dark",
};

const OPTIONS: readonly { value: ThemePreference; hint: TextKey; icon: IconNode }[] = [
  { value: "system", hint: "appearance.systemHint", icon: Monitor },
  { value: "light", hint: "appearance.lightHint", icon: Sun },
  { value: "dark", hint: "appearance.darkHint", icon: Moon },
];

export function AppearancePanel() {
  const [saved, setSaved] = useState<ThemePreference>(storedPreference);
  const [choice, setChoice] = useState<ThemePreference>(saved);
  const [justSaved, setJustSaved] = useState(false);
  const savedRef = useRef(saved);
  savedRef.current = saved;
  const groupName = useId();

  useEffect(
    () =>
      onThemeChange(() => {
        // Chi phan ung khi lua chon DA LUU doi (nut header). Ban xem truoc cua
        // chinh tab nay cung phat su kien, nhung khong doi `localStorage`.
        const stored = storedPreference();
        if (stored !== savedRef.current) {
          setSaved(stored);
          setChoice(stored);
          setJustSaved(false);
        }
      }),
    [],
  );

  // Roi tab ma chua luu ⇒ trang ve lai theme DA LUU.
  useEffect(() => () => showTheme(resolveTheme(savedRef.current)), []);

  const pick = (next: ThemePreference) => {
    setChoice(next);
    setJustSaved(false);
    showTheme(resolveTheme(next));
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    savedRef.current = choice;
    setSaved(choice);
    saveThemePreference(choice);
    setJustSaved(true);
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-6">
      <fieldset className="min-w-0">
        <legend className="mb-2.5 text-sm font-semibold">{t("appearance.mode")}</legend>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-3">
          {OPTIONS.map((o) => {
            const selected = o.value === choice;
            return (
              <label
                key={o.value}
                className={`relative flex min-h-28 flex-col gap-2.5 rounded-lg border p-4 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ring ${
                  selected
                    ? "border-accent bg-accent-subtle ring-1 ring-accent ring-inset"
                    : "border-border-strong bg-surface-panel"
                }`}
              >
                <input
                  type="radio"
                  name={groupName}
                  value={o.value}
                  checked={selected}
                  onChange={() => pick(o.value)}
                  className="sr-only"
                />
                <span className="flex items-center justify-between">
                  <StaticIcon
                    icon={o.icon}
                    size={22}
                    className={selected ? "text-accent-text" : "text-muted"}
                  />
                  <span
                    aria-hidden="true"
                    className={`grid size-5 place-items-center rounded-full border-2 ${
                      selected ? "border-accent" : "border-border-strong"
                    }`}
                  >
                    {selected && <span className="size-2.5 rounded-full bg-accent" />}
                  </span>
                </span>
                <span className="flex flex-col">
                  <span className="text-base font-semibold">{t(THEME_LABEL[o.value])}</span>
                  <span className="text-sm text-muted">{t(o.hint)}</span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <p className="text-sm text-muted">{t("appearance.previewHint")}</p>
      <SaveRow dirty={choice !== saved} saving={false} saved={justSaved} error={null} />
    </form>
  );
}
