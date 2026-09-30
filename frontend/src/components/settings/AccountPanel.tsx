import { Check, LogOut, Upload } from "lucide";
import { useEffect, useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { useSession } from "../../app/Layout";
import { PATHS } from "../../app/paths";
import { toApiError } from "../../features/admin/useResource";
import type { ProfileOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import {
  AVATAR_COLORS,
  AVATAR_LABEL,
  avatarBackground,
  avatarColorOf,
  initialOf,
  type AvatarColor,
} from "../ui/avatar";
import { ComingSoon } from "../ui/ComingSoon";
import { StaticIcon } from "../ui/Icon";
import { tierLabel } from "../ui/tierLabel";
import { SaveRow } from "./SaveRow";
import { saveErrorText } from "./saveError";

/**
 * Tab Tai khoan — T-S.11, ban T-HD9 A/G1/G2 (`SettingsAccount`).
 *
 * KH tham chieu: §24.2b·S10 · NQ-115, NQ-116 · B-293 · tasks.md T-S.5, T-S.11.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  LUU = `saveSettings`, KHONG BAO GIO MOT BODY THIEU TRUONG             ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `PUT /settings` thay CA tai nguyen (Cam bay ① cua T-S.11): tab nay chi doi
 * `display_name` + `avatar_color`, `useSessionState.saveSettings` ghep chung
 * len `default_model` va `reasoning_prefs` doc tu `/auth/me`. Mot lan doi ten
 * khong duoc la mot lan mat model mac dinh.
 *
 * Ten hien thi: tran do dai tu `display_name_max_chars` cua `/auth/me` (A3 —
 * ban ve ghi 40, `.env` hom nay 64: lech da bao lai), placeholder la email de
 * thay truoc chuyen gi xay ra khi de trong (NQ-116). Ten KHONG bao gio render
 * nhu HTML — React tu thoat, va khong co `dangerouslySetInnerHTML` nao o day.
 *
 * Dang xuat o day vi `/cai-dat` khong co sidebar (NQ-115): day la loi thoat
 * duy nhat cua trang khi header bo nut Dang xuat (T-S.12).
 */

export function AccountPanel() {
  const session = useSession();
  if (session.profile === null) {
    return null;
  }
  return <AccountForm profile={session.profile} />;
}

function colorOf(profile: ProfileOut): AvatarColor {
  return avatarColorOf(profile.avatar_color, profile.id);
}

function AccountForm({ profile }: { profile: ProfileOut }) {
  const session = useSession();
  const navigate = useNavigate();
  const savedName = profile.display_name ?? "";
  const savedColor = colorOf(profile);
  const [name, setName] = useState(savedName);
  const [color, setColor] = useState<AvatarColor>(savedColor);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();
  const hintId = useId();
  const groupName = useId();

  // Ho so doi (vua luu xong, server da cat khoang trang) ⇒ o nhap theo ban cua server.
  useEffect(() => {
    setName(savedName);
    setColor(savedColor);
  }, [savedName, savedColor]);

  // So ban DA CAT khoang trang: server cat hai dau truoc khi luu (T-S.5), nen
  // "An " va "An" la mot ten — va "   " la "de trong".
  const dirty = name.trim() !== savedName || color !== savedColor;
  const shown = name.trim() === "" ? profile.email : name.trim();
  const max = profile.display_name_max_chars;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await session.saveSettings({
        display_name: name.trim() === "" ? null : name,
        // Mau KHONG doi ⇒ gui lai dung gia tri server dang giu: "chua chon"
        // (`null`, mau hash) o lai la "chua chon" sau mot lan doi ten, va mot
        // ten FE khong biet cung khong bi ghi de ngam.
        avatar_color: color === savedColor ? profile.avatar_color : color,
      });
      setSaved(true);
    } catch (err) {
      setError(saveErrorText(toApiError(err)));
    } finally {
      setSaving(false);
    }
  };

  const edit = () => {
    setSaved(false);
    setError(null);
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex min-w-0 flex-[1_1_12.5rem] items-center gap-3.5">
          <span
            aria-hidden="true"
            data-testid="avatar-preview"
            data-color={color}
            className={`grid size-avatar-lg shrink-0 place-items-center rounded-full text-2xl leading-none font-semibold text-avatar-foreground ${avatarBackground(color)}`}
          >
            {initialOf(shown)}
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="truncate text-body font-semibold">{shown}</span>
            <span className="text-sm text-muted">{tierLabel(profile.tier_name)}</span>
          </span>
        </div>
        <ComingSoon
          planned="B-265"
          label={t("account.upload")}
          leadingIcon={<StaticIcon icon={Upload} size={18} className="shrink-0" />}
        />
      </div>

      <fieldset className="min-w-0">
        <legend className="mb-2 text-sm font-semibold">{t("account.avatarColor")}</legend>
        <div className="grid w-max grid-cols-[repeat(4,var(--spacing-touch))] gap-x-2 gap-y-1">
          {AVATAR_COLORS.map((c) => {
            const selected = c === color;
            return (
              <label key={c} className="relative grid size-touch place-items-center">
                <input
                  type="radio"
                  name={groupName}
                  value={c}
                  aria-label={t(AVATAR_LABEL[c])}
                  checked={selected}
                  onChange={() => {
                    setColor(c);
                    edit();
                  }}
                  className="peer sr-only"
                />
                <span
                  className={`grid size-8 place-items-center rounded-full text-avatar-foreground peer-focus-visible:outline-2 peer-focus-visible:outline-offset-4 peer-focus-visible:outline-ring ${avatarBackground(c)} ${
                    selected ? "ring-2 ring-foreground ring-offset-2 ring-offset-background" : ""
                  }`}
                >
                  {selected && <StaticIcon icon={Check} size={16} strokeWidth={3} />}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-baseline justify-between gap-3">
          <label htmlFor={inputId} className="text-sm font-semibold">
            {t("account.displayName")}
          </label>
          <span className="tabular flex gap-1 text-xs text-muted">
            <span>{Array.from(name).length}</span>
            <span aria-hidden="true">/</span>
            <span>{max}</span>
          </span>
        </div>
        <input
          id={inputId}
          type="text"
          maxLength={max}
          value={name}
          placeholder={profile.email}
          autoComplete="nickname"
          aria-describedby={hintId}
          onChange={(e) => {
            setName(e.target.value);
            edit();
          }}
          className="motion-control h-touch w-full min-w-0 rounded-md border border-border-strong bg-surface-panel px-3 text-base text-foreground placeholder:text-muted focus-visible:border-ring"
        />
        <p id={hintId} className="text-sm text-muted">
          {t("account.displayNameHint")}
        </p>
      </div>

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] border-t border-divider">
        <dt className="border-b border-divider py-3 pr-6 text-sm text-muted">{t("account.email")}</dt>
        <dd className="border-b border-divider py-3 text-base leading-5 break-all">{profile.email}</dd>
        <dt className="border-b border-divider py-3 pr-6 text-sm text-muted">{t("account.tier")}</dt>
        <dd className="border-b border-divider py-3 text-base leading-5">{tierLabel(profile.tier_name)}</dd>
      </dl>

      <SaveRow dirty={dirty} saving={saving} saved={saved} error={error} />

      <div className="border-t border-divider pt-6">
        <button
          type="button"
          onClick={() => {
            void session.logout().then(() => navigate(PATHS.login));
          }}
          className="motion-press inline-flex min-h-touch items-center gap-2 rounded-md border border-border-strong px-4 text-base font-medium text-danger-text hover:bg-danger-subtle"
        >
          <StaticIcon icon={LogOut} size={18} className="shrink-0" />
          {t("account.logout")}
        </button>
      </div>
    </form>
  );
}
