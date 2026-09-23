import * as Popover from "@radix-ui/react-popover";
import { useCallback, useEffect, useId, useState } from "react";

import { toApiError, useResource } from "../../features/admin/useResource";
import {
  ApiError,
  api,
  type AdminUserListItem,
  type AdminUserPatch,
  type TierRow,
  type TrangThaiUser,
} from "../../lib/api";
import { t, type KhoaChu } from "../../lib/i18n";
import { TableScroll } from "../ui/TableScroll";
import { AdminDialog, DialogButtons } from "./AdminDialog";
import {
  CountCell,
  EffectNotice,
  ErrorNotice,
  LoadingNote,
  MoneyCell,
  PendingBadge,
  ScreenTitle,
  Switch,
  TD,
  TH,
  TH_NUMBER,
} from "./adminUi";
import { formatClock, padMoney } from "./format";
import { TiersSection } from "./TiersSection";
import {
  LIMIT_KEYS,
  STATUS_LABEL,
  effectiveSkills,
  isPending,
  overrideLimit,
  overrideWithLimits,
  overrideWithSkills,
  tierOf,
  type LimitKey,
  type LimitOverride,
} from "./usersView";

/**
 * Man 1b "Nguoi dung" — §16.3, ban T-HD7 · T-3.12.
 *
 * KH tham chieu: §16.3, §10.4, §11.1, §11.3 · tasks.md T-2.16, T-2.20, T-3.12
 * (Cam bay ② ③), NQ-51, NQ-66.
 *
 * Bon hanh dong cua §16.3: doi tier, ghi de han muc, bat `can_execute_skills`,
 * suspend. Hai cot "Chi tieu 7 ngay" va "Hoi thoai" den tu MOT cau JOIN trong
 * `GET /admin/users` (NQ-66) — man nay khong goi them gi cho tung hang.
 *
 * ── "Cho hieu luc", khong phai "da ap dung" (Cam bay ②) ─────────────────
 *
 * Doi tier / han muc / quyen skill co hieu luc trong TOI DA
 * `limits_cache_ttl_s` giay (NQ-51 co y khong go cache). Hang vua doi mang
 * nhan "Cho hieu luc · Da luu luc …" cho toi khi het khoang ay; cau "Co hieu
 * luc trong vong N giay" dung so cua server. Bang van hien gia tri MOI ngay
 * (Postgres da doi) — thu chua doi la cache cua luot chat ke tiep.
 *
 * Khoa/mo khoa thi KHAC: `suspend` thu hoi phien ngay (§11.3), nen khong co
 * nhan "cho hieu luc" nao cho no.
 *
 * ── Khong co thao tac hang loat ──────────────────────────────────────────
 *
 * Ban ve: *"mot quan tri vien, 20 nguoi"*. Menu ⋯ moi hang, khong checkbox.
 */

const LIMIT_LABEL: Record<LimitKey, KhoaChu> = {
  limit_5h_usd: "admin.quota.label5h",
  limit_7d_usd: "admin.quota.label7d",
};
const LIMIT_SHORT: Record<LimitKey, KhoaChu> = {
  limit_5h_usd: "admin.limit.5h",
  limit_7d_usd: "admin.limit.7d",
};

/** Hanh dong trang thai cua menu ⋯ — dung mui ten §11.1 ma backend cho phep. */
function statusAction(status: TrangThaiUser): { action: "suspend" | "approve"; label: KhoaChu } | null {
  switch (status) {
    case "active":
      return { action: "suspend", label: "admin.action.lock" };
    case "suspended":
      return { action: "approve", label: "admin.action.unlock" };
    case "pending_approval":
    case "rejected":
      return { action: "approve", label: "admin.approvals.approve" };
    default:
      return null;
  }
}

export function UsersScreen({ currentUserId }: { currentUserId: string | null }) {
  const loadUsers = useCallback(async () => (await api.quanTriDanhSachUser()).users, []);
  const users = useResource(loadUsers);
  const tiers = useResource(api.adminListTiers);

  const ttl = tiers.data?.limits_cache_ttl_s ?? null;
  const tierRows = tiers.data?.tiers ?? [];

  /** userId → luc luu thay doi han muc gan nhat (ms). */
  const [savedAt, setSavedAt] = useState<Record<string, number>>({});
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ kind: "tier" | "quota"; userId: string } | null>(null);

  // Mot hen gio DUY NHAT, ban dung luc nhan "cho hieu luc" som nhat het han —
  // khong phai mot bo dem lam tuoi (cung lo T-3.11).
  useEffect(() => {
    if (ttl === null) {
      return;
    }
    const conCho = Object.values(savedAt)
      .map((luc) => luc + ttl * 1000)
      .filter((het) => het > now);
    if (conCho.length === 0) {
      return;
    }
    const hen = setTimeout(() => setNow(Date.now()), Math.min(...conCho) - now + 50);
    return () => clearTimeout(hen);
  }, [savedAt, ttl, now]);

  const patchUser = useCallback(
    async (userId: string, patch: AdminUserPatch): Promise<boolean> => {
      setBusyId(userId);
      setActionError(null);
      try {
        await api.adminUpdateUser(userId, patch);
        const luc = Date.now();
        setSavedAt((cu) => ({ ...cu, [userId]: luc }));
        setLastSavedAt(luc);
        setNow(luc);
        await users.reload();
        return true;
      } catch (e) {
        setActionError(toApiError(e));
        return false;
      } finally {
        setBusyId(null);
      }
    },
    [users],
  );

  const setStatus = useCallback(
    async (userId: string, action: "suspend" | "approve") => {
      setMenuFor(null);
      setBusyId(userId);
      setActionError(null);
      try {
        await api.quanTriDoiTrangThai(userId, action);
        await users.reload();
      } catch (e) {
        setActionError(toApiError(e));
      } finally {
        setBusyId(null);
      }
    },
    [users],
  );

  const dialogUser =
    dialog === null ? null : (users.data?.find((u) => u.id === dialog.userId) ?? null);

  return (
    <>
      <ScreenTitle>{t("admin.users.title")}</ScreenTitle>

      {users.error && (
        <ErrorNotice title={t("admin.loadError")} error={users.error} onRetry={() => void users.reload()} />
      )}
      {tiers.error && (
        <ErrorNotice title={t("admin.loadError")} error={tiers.error} onRetry={() => void tiers.reload()} />
      )}
      {actionError && <ErrorNotice title={t("admin.actionError")} error={actionError} />}

      <EffectNotice
        savedAtLabel={lastSavedAt !== null ? formatClock(lastSavedAt) : undefined}
        ttlSeconds={ttl}
      />

      {users.data === null ? (
        users.loading && <LoadingNote />
      ) : (
        <TableScroll label={t("admin.users.title")}>
          <thead>
            <tr>
              <th scope="col" className={`${TH} sticky-col w-sticky-col`}>
                {t("admin.col.user")}
              </th>
              <th scope="col" className={TH}>
                {t("admin.col.status")}
              </th>
              <th scope="col" className={TH}>
                {t("admin.col.tier")}
              </th>
              <th scope="col" className={TH_NUMBER}>
                {t("admin.col.spend7d")}
              </th>
              <th scope="col" className={TH_NUMBER}>
                {t("admin.col.conversations")}
              </th>
              <th scope="col" className={TH}>
                {t("admin.col.skills")}
              </th>
              <th scope="col" className={TH}>
                <span className="sr-only">{t("admin.col.actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {users.data.map((u) => (
              <UserRow
                key={u.id}
                user={u}
                tiers={tierRows}
                pendingSince={
                  savedAt[u.id] !== undefined && isPending(savedAt[u.id], now, ttl)
                    ? savedAt[u.id]
                    : null
                }
                busy={busyId !== null}
                isSelf={u.id === currentUserId}
                menuOpen={menuFor === u.id}
                onMenuOpenChange={(open) => setMenuFor(open ? u.id : null)}
                onToggleSkills={(next) => {
                  const tier = tierOf(tierRows, u.tier_name);
                  void patchUser(u.id, {
                    limit_override: overrideWithSkills(
                      u.limit_override_json,
                      next,
                      tier?.can_execute_skills ?? null,
                    ),
                  });
                }}
                onChangeTier={() => {
                  setMenuFor(null);
                  setDialog({ kind: "tier", userId: u.id });
                }}
                onOverride={() => {
                  setMenuFor(null);
                  setDialog({ kind: "quota", userId: u.id });
                }}
                onSetStatus={(action) => void setStatus(u.id, action)}
              />
            ))}
          </tbody>
        </TableScroll>
      )}

      {dialogUser !== null && dialog?.kind === "tier" && (
        <TierDialog
          user={dialogUser}
          tiers={tierRows}
          ttlSeconds={ttl}
          onClose={() => setDialog(null)}
          onSave={(tierName) => patchUser(dialogUser.id, { tier_name: tierName })}
        />
      )}
      {dialogUser !== null && dialog?.kind === "quota" && (
        <QuotaOverrideDialog
          user={dialogUser}
          tier={tierOf(tierRows, dialogUser.tier_name)}
          ttlSeconds={ttl}
          onClose={() => setDialog(null)}
          onSave={(values) =>
            patchUser(dialogUser.id, {
              limit_override: overrideWithLimits(dialogUser.limit_override_json, values),
            })
          }
        />
      )}

      <TiersSection
        tiers={tierRows}
        ttlSeconds={ttl}
        onSaved={async () => {
          await tiers.reload();
        }}
      />
    </>
  );
}

function UserRow({
  user,
  tiers,
  pendingSince,
  busy,
  isSelf,
  menuOpen,
  onMenuOpenChange,
  onToggleSkills,
  onChangeTier,
  onOverride,
  onSetStatus,
}: {
  user: AdminUserListItem;
  tiers: readonly TierRow[];
  pendingSince: number | null;
  busy: boolean;
  isSelf: boolean;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  onToggleSkills: (next: boolean) => void;
  onChangeTier: () => void;
  onOverride: () => void;
  onSetStatus: (action: "suspend" | "approve") => void;
}) {
  const hanhDong = isSelf ? null : statusAction(user.status);
  const ghiDe = LIMIT_KEYS.filter((k) => overrideLimit(user.limit_override_json, k) !== "");
  const ten = user.display_name ?? user.email;

  return (
    <tr>
      <th scope="row" className={`${TD} sticky-col w-sticky-col max-w-sticky-col text-left font-normal`}>
        <span className="block truncate font-semibold">{ten}</span>
        {user.display_name !== null && (
          <span className="block truncate text-xs text-muted">{user.email}</span>
        )}
      </th>
      <td className={`${TD} whitespace-nowrap`}>
        <span
          className={
            user.status === "active"
              ? "text-success-text"
              : user.status === "suspended" || user.status === "rejected"
                ? "font-semibold text-danger-text"
                : "text-warning-text"
          }
        >
          {t(STATUS_LABEL[user.status])}
        </span>
      </td>
      <td className={TD}>
        <span className="flex flex-col items-start gap-1">
          <span className="rounded-sm border border-border px-1.5 font-mono text-xs">{user.tier_name}</span>
          {pendingSince !== null && <PendingBadge savedAtLabel={formatClock(pendingSince)} />}
          {ghiDe.length > 0 && (
            <span className="text-2xs text-muted">
              {t("admin.override.label")}
              {ghiDe.map((k) => (
                <span key={k}>
                  {" · "}
                  {t(LIMIT_SHORT[k])}{" "}
                  <span className="tabular text-foreground">
                    {padMoney(overrideLimit(user.limit_override_json, k), 4)}
                  </span>
                </span>
              ))}
            </span>
          )}
        </span>
      </td>
      <MoneyCell value={user.spend_7d_usd} />
      <CountCell value={user.conversation_count} />
      <td className={TD}>
        <Switch
          checked={effectiveSkills(user, tiers)}
          label={`${t("admin.col.skills")} — ${ten}`}
          disabled={busy}
          onChange={onToggleSkills}
        />
      </td>
      <td className={`${TD} w-touch`}>
        <Popover.Root open={menuOpen} onOpenChange={onMenuOpenChange}>
          <Popover.Trigger asChild>
            <button
              type="button"
              aria-label={`${t("admin.action.more")} — ${ten}`}
              aria-haspopup="menu"
              disabled={busy}
              className="motion-press flex size-touch items-center justify-center rounded-md text-muted hover:bg-surface-hover hover:text-foreground disabled:opacity-50"
            >
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="fill-current">
                <circle cx="4" cy="9" r="1.5" />
                <circle cx="9" cy="9" r="1.5" />
                <circle cx="14" cy="9" r="1.5" />
              </svg>
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              align="end"
              sideOffset={4}
              role="menu"
              className="motion-popover z-50 flex w-56 flex-col gap-0.5 rounded-lg border border-border bg-surface-panel p-1.5 text-base shadow-popover"
            >
              <button
                type="button"
                role="menuitem"
                onClick={onChangeTier}
                className="flex min-h-touch items-center rounded-md px-2.5 text-left text-foreground hover:bg-surface-hover"
              >
                {t("admin.action.changeTier")}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={onOverride}
                className="flex min-h-touch items-center rounded-md px-2.5 text-left text-foreground hover:bg-surface-hover"
              >
                {t("admin.action.overrideQuota")}
              </button>
              {hanhDong !== null && (
                <>
                  <span role="separator" className="my-1 h-px bg-border" />
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => onSetStatus(hanhDong.action)}
                    className={
                      hanhDong.action === "suspend"
                        ? "flex min-h-touch items-center rounded-md px-2.5 text-left font-medium text-danger-text hover:bg-surface-hover"
                        : "flex min-h-touch items-center rounded-md px-2.5 text-left text-foreground hover:bg-surface-hover"
                    }
                  >
                    {t(hanhDong.label)}
                  </button>
                </>
              )}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </td>
    </tr>
  );
}

function TierDialog({
  user,
  tiers,
  ttlSeconds,
  onClose,
  onSave,
}: {
  user: AdminUserListItem;
  tiers: readonly TierRow[];
  ttlSeconds: number | null;
  onClose: () => void;
  onSave: (tierName: string) => Promise<boolean>;
}) {
  const [value, setValue] = useState(user.tier_name);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const selectId = useId();

  const save = async () => {
    setSaving(true);
    if (await onSave(value)) {
      setSavedAt(Date.now());
    }
    setSaving(false);
  };

  return (
    <AdminDialog title={t("admin.tierDialog.title")} subtitle={user.display_name ?? user.email} onClose={onClose}>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={selectId} className="text-sm font-medium text-foreground">
          {t("admin.tierDialog.label")}
        </label>
        <select
          id={selectId}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="motion-control min-h-touch rounded-md border border-border-strong bg-background px-3 font-mono text-base text-foreground"
        >
          {tiers.map((tier) => (
            <option key={tier.name} value={tier.name}>
              {tier.name}
            </option>
          ))}
        </select>
      </div>
      <EffectNotice savedAtLabel={savedAt !== null ? formatClock(savedAt) : undefined} ttlSeconds={ttlSeconds} />
      <DialogButtons saved={savedAt !== null} saving={saving} onSave={() => void save()} />
    </AdminDialog>
  );
}

/**
 * Ghi de han muc — ban T-HD7 ve MOT o "Han muc thang"; he thong nay co HAI
 * cua so (5 gio, 7 ngay — §10.3), nen dialog co hai o cung khuon. O nhap giu
 * CHUOI, can phai, khong parse: go "20" luu "20", server chuan hoa.
 */
function QuotaOverrideDialog({
  user,
  tier,
  ttlSeconds,
  onClose,
  onSave,
}: {
  user: AdminUserListItem;
  tier: TierRow | null;
  ttlSeconds: number | null;
  onClose: () => void;
  onSave: (values: Record<LimitKey, string>) => Promise<boolean>;
}) {
  const current: LimitOverride | null = user.limit_override_json;
  const [values, setValues] = useState<Record<LimitKey, string>>({
    limit_5h_usd: overrideLimit(current, "limit_5h_usd"),
    limit_7d_usd: overrideLimit(current, "limit_7d_usd"),
  });
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const baseId = useId();

  const save = async () => {
    setSaving(true);
    if (await onSave(values)) {
      setSavedAt(Date.now());
    }
    setSaving(false);
  };

  return (
    <AdminDialog title={t("admin.quota.dialogTitle")} subtitle={user.display_name ?? user.email} onClose={onClose}>
      {LIMIT_KEYS.map((key) => (
        <div key={key} className="flex flex-col gap-1.5">
          <label htmlFor={`${baseId}-${key}`} className="text-sm font-medium text-foreground">
            {t(LIMIT_LABEL[key])}
          </label>
          <input
            id={`${baseId}-${key}`}
            inputMode="decimal"
            autoComplete="off"
            value={values[key]}
            onChange={(e) => setValues((cu) => ({ ...cu, [key]: e.target.value }))}
            className="motion-control min-h-touch rounded-md border border-border-strong bg-background px-3 text-right text-base tabular text-foreground"
          />
          {tier !== null && (
            <p className="text-xs text-muted">
              {t("admin.quota.tierDefaultPrefix")} <span className="tabular">{tier[key]}</span>
            </p>
          )}
        </div>
      ))}
      <EffectNotice savedAtLabel={savedAt !== null ? formatClock(savedAt) : undefined} ttlSeconds={ttlSeconds} />
      <DialogButtons saved={savedAt !== null} saving={saving} onSave={() => void save()} />
    </AdminDialog>
  );
}
