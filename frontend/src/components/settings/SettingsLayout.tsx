import {
  ChevronLeft,
  ChevronRight,
  Contrast,
  Cpu,
  Gauge,
  KeyRound,
  User,
  type IconNode,
} from "lucide";
import { useCallback, type ReactNode } from "react";
import { Link, Navigate } from "react-router";

import { useSession } from "../../app/Layout";
import { PATHS } from "../../app/paths";
import { useResource } from "../../features/admin/useResource";
import { api } from "../../lib/api";
import { t, type TextKey } from "../../lib/i18n";
import { useDrawerMode } from "../../lib/viewport";
import { StaticIcon } from "../ui/Icon";
import { storedPreference } from "../ui/ThemeToggle";
import { THEME_LABEL } from "./AppearancePanel";

/**
 * Khung trang Cai dat v2 — T-S.11, ban T-HD9 (`Scarlet Cài đặt.dc.html`).
 *
 * KH tham chieu: §24.2b·S10 · NQ-114, NQ-115, NQ-116 · tasks.md T-S.11.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOI TAB MOT DUONG DAN — TAB LA LIEN KET, KHONG PHAI `role="tab"`      ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Tab co URL rieng (deep link `/cai-dat/muc-su-dung` tu dong han muc T-S.10
 * va menu tai khoan T-S.12), nen no la `<a aria-current="page">` — dung ghi
 * chu cuoi `SettingsLayout.tsx` cua ban ve. `role="tablist"` hua phim mui ten
 * va mot `tabpanel`, ma o day doi tab la doi trang.
 *
 * ── Hai be rong, hai cach di ──────────────────────────────────────────────
 *
 * ≥ 1024 px: cot tab 216 (`--spacing-settings-nav`) cach noi dung 48, noi
 * dung toi da 640 (`--spacing-settings-form`), ca khoi 904 can giua; `/cai-dat`
 * chuyen thang sang Tai khoan. Hep hon: `/cai-dat` la DANH SACH tab (ban ve
 * F — nam nhan khong vua 343 px, dai tab cuon ngang se giau Muc su dung), moi
 * man con co header 56 px voi nut quay lai 44 px ve `/cai-dat`.
 *
 * ── Khong co sidebar (NQ-115) ──────────────────────────────────────────────
 *
 * Artboard desktop cua T-HD9 ve ca sidebar hoi thoai ben trai; KE-HOACH
 * (NQ-115, Cam bay ① cua T-S.12) chot `/admin` va `/cai-dat` KHONG co sidebar —
 * loi Dang xuat o day la tab Tai khoan. Lech nay da bao lai, khong tu sua.
 */

export const SETTINGS_TABS = [
  { path: PATHS.settingsAccount, labelKey: "settings.tab.account", icon: User },
  { path: PATHS.settingsAppearance, labelKey: "settings.tab.appearance", icon: Contrast },
  { path: PATHS.settingsModel, labelKey: "settings.tab.model", icon: Cpu },
  { path: PATHS.settingsApiKeys, labelKey: "settings.tab.apiKeys", icon: KeyRound },
  { path: PATHS.settingsUsage, labelKey: "settings.tab.usage", icon: Gauge },
] as const satisfies readonly { path: string; labelKey: TextKey; icon: IconNode }[];

export type SettingsTabPath = (typeof SETTINGS_TABS)[number]["path"];

/*
  Cot tab + khoang cach + cot noi dung = 904 (bang "Con so" cua ban ve). Viet
  bang chinh ba token, khong mot con so px nao.
*/
const PAGE_WIDTH =
  "lg:max-w-[calc(var(--spacing-settings-nav)_+_var(--spacing)_*_12_+_var(--spacing-settings-form))]";

/**
 * Header man con / danh sach tab duoi 1024 px — cao 56, dan sat mep tren. Duoi
 * no: 12 toi danh sach tab (ban F, `nav` dem 12), 20 toi noi dung man con (ban
 * G/H, `main` dem 20 — khe `gap-5` cua `section`).
 */
const MOBILE_HEADER =
  "-mx-gutter -mt-5 flex h-header shrink-0 items-center gap-1 border-b border-border px-1.5 lg:hidden";

export function SettingsLayout({ tab, children }: { tab: SettingsTabPath; children: ReactNode }) {
  const current = SETTINGS_TABS.find((x) => x.path === tab) ?? SETTINGS_TABS[0];
  const label = t(current.labelKey);
  return (
    <div className="px-gutter py-5 lg:px-gutter-lg lg:py-8">
      <div className={`mx-auto flex w-full min-w-0 flex-col gap-7 ${PAGE_WIDTH}`}>
        <h2 className="hidden text-2xl font-semibold lg:block">{t("settings.title")}</h2>
        <div className="flex min-w-0 items-start gap-12">
          <nav
            aria-label={t("settings.navLabel")}
            className="hidden w-settings-nav shrink-0 flex-col gap-0.5 lg:flex"
          >
            {SETTINGS_TABS.map((x) => {
              const active = x.path === tab;
              return (
                <Link
                  key={x.path}
                  to={x.path}
                  aria-current={active ? "page" : undefined}
                  className={
                    active
                      ? "motion-control flex min-h-touch items-center gap-3 rounded-md border border-accent bg-accent-subtle px-3 text-base font-semibold text-foreground no-underline hover:text-foreground hover:no-underline"
                      : "motion-control flex min-h-touch items-center gap-3 rounded-md border border-transparent px-3 text-base text-foreground no-underline hover:bg-surface-hover hover:text-foreground hover:no-underline"
                  }
                >
                  <StaticIcon
                    icon={x.icon}
                    size={18}
                    className={active ? "shrink-0 text-accent-text" : "shrink-0 text-muted"}
                  />
                  {t(x.labelKey)}
                </Link>
              );
            })}
          </nav>
          <section aria-label={label} className="flex min-w-0 flex-1 flex-col gap-5 lg:max-w-settings-form lg:gap-6">
            <header className={MOBILE_HEADER}>
              <Link
                to={PATHS.settings}
                aria-label={t("settings.back")}
                className="grid size-touch place-items-center rounded-md text-foreground hover:bg-surface-hover hover:text-foreground"
              >
                <StaticIcon icon={ChevronLeft} size={20} />
              </Link>
              <h2 className="text-lg font-semibold">{label}</h2>
            </header>
            <h3 className="hidden text-xl font-semibold lg:block">{label}</h3>
            {children}
          </section>
        </div>
      </div>
    </div>
  );
}

/**
 * `/cai-dat` — ≥ 1024 px chuyen sang Tai khoan (mac dinh cua `/cai-dat`); hep
 * hon la danh sach tab kem gia tri hien tai (ban ve F).
 */
export function SettingsIndex() {
  const drawer = useDrawerMode();
  if (!drawer) {
    return <Navigate to={PATHS.settingsAccount} replace />;
  }
  return <SettingsTabList />;
}

function SettingsTabList() {
  const session = useSession();
  const profile = session.profile;
  const loadModels = useCallback(() => api.listModels(), []);
  const models = useResource(loadModels);

  const defaultModel = profile?.default_model ?? null;
  const values: Partial<Record<SettingsTabPath, string>> = {
    [PATHS.settingsAccount]: profile?.display_name ?? session.user?.email ?? "",
    [PATHS.settingsAppearance]: t(THEME_LABEL[storedPreference()]),
    [PATHS.settingsModel]:
      defaultModel === null
        ? t("settings.model.catalogDefault")
        : (models.data?.find((m) => m.id === defaultModel)?.display_name ?? ""),
  };

  return (
    <div className="px-gutter py-5">
      <header className={MOBILE_HEADER}>
        <h2 className="px-2.5 text-lg font-semibold">{t("settings.title")}</h2>
      </header>
      <nav aria-label={t("settings.navLabel")} className="pt-3">
        <div className="flex flex-col gap-px overflow-hidden rounded-lg border border-border bg-divider">
          {SETTINGS_TABS.map((x) => (
            <Link
              key={x.path}
              to={x.path}
              className="flex min-h-row-settings items-center gap-3 bg-surface-panel pr-2 pl-4 text-foreground no-underline hover:bg-surface-hover hover:text-foreground hover:no-underline"
            >
              <span className="min-w-0 flex-1 text-body font-medium">{t(x.labelKey)}</span>
              <span className="min-w-0 max-w-35 truncate text-sm text-muted">{values[x.path] ?? ""}</span>
              <StaticIcon icon={ChevronRight} size={18} className="shrink-0 text-muted" />
            </Link>
          ))}
        </div>
      </nav>
    </div>
  );
}
