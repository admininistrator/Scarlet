import { useId, useState } from "react";

import { toApiError } from "../../features/admin/useResource";
import { ApiError, api, type TierPatch, type TierRow } from "../../lib/api";
import { t, type TextKey } from "../../lib/i18n";
import { TableScroll } from "../ui/TableScroll";
import { EffectNotice, ErrorNotice, PendingBadge, Switch, TD, TH, TH_NUMBER } from "./adminUi";
import { formatClock, formatCount } from "./format";
import { AdminDialog, DialogButtons } from "./AdminDialog";

/**
 * "Han muc theo tier" — UI cua `GET/PATCH /admin/tiers` (T-2.20 → T-3.12).
 *
 * KH tham chieu: §10.4, §16.3 · tasks.md T-2.20, T-3.12 (Cam bay ② ③), B-152,
 * NQ-51.
 *
 * Ban T-HD7-v2 (muc 1c, B-262 ③) chot cho cua no: TAB thu hai cua man "Nguoi
 * dung" (T-S.17). Ban v2 chi ve hai cot han muc + "So nguoi dung"; o day giu du
 * tam truong (nguoi dung chot o T-S.17) va khong co cot dem — server khong gui.
 *
 * Hai luat cua task:
 *
 *   - **Cam bay ②** — `PATCH` KHONG go cache (NQ-51). Man hinh noi "co hieu
 *     luc trong vong N giay", khong bao gio "da ap dung".
 *   - **Cam bay ③** — `is_default` doc duoc ma KHONG sua duoc (B-152), va hom
 *     nay khong code nao doc no. Khong ve cong tac, khong ve ca cot: mot o
 *     "mac dinh" tren man nay se doc thanh "tier cua nguoi moi", dieu B-152
 *     noi la chua dung.
 *
 * Tam truong sua duoc bang DUNG `OVERRIDABLE_FIELDS` (backend co test canh).
 * Tien giu CHUOI; bon truong so nguyen la so luong, khong phai tien.
 */

type IntField = "web_searches_per_day" | "max_upload_mb" | "max_attachments";
const INT_FIELDS: readonly IntField[] = ["web_searches_per_day", "max_upload_mb", "max_attachments"];
const MONEY_FIELDS = ["limit_5h_usd", "limit_7d_usd"] as const;
type MoneyField = (typeof MONEY_FIELDS)[number];
type BoolField = "can_execute_skills" | "can_use_web";
const BOOL_FIELDS: readonly BoolField[] = ["can_execute_skills", "can_use_web"];

const FIELD_LABEL: Record<MoneyField | IntField | BoolField | "allowed_model_tags", TextKey> = {
  limit_5h_usd: "admin.tiers.col.limit5h",
  limit_7d_usd: "admin.tiers.col.limit7d",
  can_execute_skills: "admin.tiers.col.skills",
  can_use_web: "admin.tiers.col.web",
  web_searches_per_day: "admin.tiers.col.webPerDay",
  max_upload_mb: "admin.tiers.col.uploadMb",
  max_attachments: "admin.tiers.col.attachments",
  allowed_model_tags: "admin.tiers.col.modelTags",
};

export function TiersSection({
  tiers,
  ttlSeconds,
  pendingSince,
  onSaved,
}: {
  tiers: readonly TierRow[];
  ttlSeconds: number | null;
  /** T-S.17 (ban v2 muc 1c): luc luu cua tier con "cho hieu luc", hoac `null`. */
  pendingSince: (tierName: string) => number | null;
  onSaved: (tierName: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState<TierRow | null>(null);

  if (tiers.length === 0) {
    return null;
  }

  return (
    <>
      <TableScroll label={t("admin.tiers.title")}>
        <thead>
          <tr>
            <th scope="col" className={`${TH} sticky-col w-sticky-col`}>
              {t("admin.tiers.col.name")}
            </th>
            {MONEY_FIELDS.map((f) => (
              <th key={f} scope="col" className={TH_NUMBER}>
                {t(FIELD_LABEL[f])}
              </th>
            ))}
            {BOOL_FIELDS.map((f) => (
              <th key={f} scope="col" className={TH}>
                {t(FIELD_LABEL[f])}
              </th>
            ))}
            {INT_FIELDS.map((f) => (
              <th key={f} scope="col" className={TH_NUMBER}>
                {t(FIELD_LABEL[f])}
              </th>
            ))}
            <th scope="col" className={TH}>
              {t("admin.tiers.col.modelTags")}
            </th>
            <th scope="col" className={TH}>
              <span className="sr-only">{t("admin.col.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {tiers.map((tier) => {
            const since = pendingSince(tier.name);
            return (
            <tr key={tier.name}>
              <th scope="row" className={`${TD} sticky-col w-sticky-col text-left font-normal`}>
                <span className="flex flex-col items-start gap-1">
                  <span className="rounded-sm border border-border-strong px-1.5 font-mono text-sm">{tier.name}</span>
                  {since !== null && <PendingBadge savedAtLabel={formatClock(since)} />}
                </span>
              </th>
              {MONEY_FIELDS.map((f) => (
                <td key={f} className={`${TD} money`}>
                  {tier[f]}
                </td>
              ))}
              {BOOL_FIELDS.map((f) => (
                <td key={f} className={TD}>
                  {tier[f] ? t("admin.yes") : t("admin.no")}
                </td>
              ))}
              {INT_FIELDS.map((f) => (
                <td key={f} className={`${TD} money`}>
                  {formatCount(tier[f])}
                </td>
              ))}
              <td className={`${TD} font-mono text-xs`}>
                {tier.allowed_model_tags.length === 0 ? "—" : tier.allowed_model_tags.join(", ")}
              </td>
              <td className={TD}>
                <button
                  type="button"
                  onClick={() => setEditing(tier)}
                  aria-label={`${t("admin.tiers.edit")} — ${tier.name}`}
                  className="motion-press min-h-touch rounded-md border border-border-strong px-3 text-base font-medium text-foreground hover:bg-surface-hover"
                >
                  {t("admin.tiers.edit")}
                </button>
              </td>
            </tr>
            );
          })}
        </tbody>
      </TableScroll>

      {editing !== null && (
        <TierEditDialog
          tier={editing}
          ttlSeconds={ttlSeconds}
          onClose={() => setEditing(null)}
          onSaved={onSaved}
        />
      )}
    </>
  );
}

/** Chi gui nhung truong THAT SU doi — server cung bo qua cai khong doi. */
export function tierPatch(
  tier: TierRow,
  form: {
    money: Record<MoneyField, string>;
    ints: Record<IntField, string>;
    bools: Record<BoolField, boolean>;
    tags: string;
  },
): TierPatch {
  const patch: TierPatch = {};
  for (const f of MONEY_FIELDS) {
    const value = form.money[f].trim();
    if (value !== tier[f]) {
      patch[f] = value;
    }
  }
  for (const f of INT_FIELDS) {
    const value = Number(form.ints[f]);
    if (value !== tier[f]) {
      patch[f] = value;
    }
  }
  for (const f of BOOL_FIELDS) {
    if (form.bools[f] !== tier[f]) {
      patch[f] = form.bools[f];
    }
  }
  const tags = form.tags
    .split(",")
    .map((tag) => tag.trim())
    .filter((tag) => tag !== "");
  if (tags.join(",") !== tier.allowed_model_tags.join(",")) {
    patch.allowed_model_tags = tags;
  }
  return patch;
}

function TierEditDialog({
  tier,
  ttlSeconds,
  onClose,
  onSaved,
}: {
  tier: TierRow;
  ttlSeconds: number | null;
  onClose: () => void;
  onSaved: (tierName: string) => Promise<void>;
}) {
  const [money, setMoney] = useState<Record<MoneyField, string>>({
    limit_5h_usd: tier.limit_5h_usd,
    limit_7d_usd: tier.limit_7d_usd,
  });
  const [ints, setInts] = useState<Record<IntField, string>>({
    web_searches_per_day: String(tier.web_searches_per_day),
    max_upload_mb: String(tier.max_upload_mb),
    max_attachments: String(tier.max_attachments),
  });
  const [bools, setBools] = useState<Record<BoolField, boolean>>({
    can_execute_skills: tier.can_execute_skills,
    can_use_web: tier.can_use_web,
  });
  const [tags, setTags] = useState(tier.allowed_model_tags.join(", "));
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const baseId = useId();

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.adminUpdateTier(tier.name, tierPatch(tier, { money, ints, bools, tags }));
      setSavedAt(Date.now());
      await onSaved(tier.name);
    } catch (e) {
      setError(toApiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <AdminDialog
      title={t("admin.tiers.dialogTitle")}
      subtitle={`${t("admin.tiers.subtitlePrefix")} ${tier.name}`}
      onClose={onClose}
    >
      {MONEY_FIELDS.map((f) => (
        <div key={f} className="flex flex-col gap-1.5">
          <label htmlFor={`${baseId}-${f}`} className="text-sm font-medium text-foreground">
            {t(FIELD_LABEL[f])}
          </label>
          <input
            id={`${baseId}-${f}`}
            inputMode="decimal"
            autoComplete="off"
            value={money[f]}
            onChange={(e) => setMoney((prev) => ({ ...prev, [f]: e.target.value }))}
            className="motion-control min-h-touch rounded-md border border-border-strong bg-background px-3 text-right text-base tabular text-foreground"
          />
        </div>
      ))}
      <div className="flex flex-wrap gap-x-6">
        {BOOL_FIELDS.map((f) => (
          <div key={f} className="flex items-center gap-1">
            <Switch
              checked={bools[f]}
              label={t(FIELD_LABEL[f])}
              onChange={(next) => setBools((prev) => ({ ...prev, [f]: next }))}
            />
            <span aria-hidden="true" className="text-sm text-foreground">
              {t(FIELD_LABEL[f])}
            </span>
          </div>
        ))}
      </div>
      {INT_FIELDS.map((f) => (
        <div key={f} className="flex flex-col gap-1.5">
          <label htmlFor={`${baseId}-${f}`} className="text-sm font-medium text-foreground">
            {t(FIELD_LABEL[f])}
          </label>
          <input
            id={`${baseId}-${f}`}
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            value={ints[f]}
            onChange={(e) => setInts((prev) => ({ ...prev, [f]: e.target.value }))}
            className="motion-control min-h-touch rounded-md border border-border-strong bg-background px-3 text-right text-base tabular text-foreground"
          />
        </div>
      ))}
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${baseId}-tags`} className="text-sm font-medium text-foreground">
          {t("admin.tiers.col.modelTags")}
        </label>
        <input
          id={`${baseId}-tags`}
          autoComplete="off"
          aria-describedby={`${baseId}-tags-hint`}
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          className="motion-control min-h-touch rounded-md border border-border-strong bg-background px-3 font-mono text-base text-foreground"
        />
        <p id={`${baseId}-tags-hint`} className="text-xs text-muted">
          {t("admin.tiers.modelTagsHint")}
        </p>
      </div>
      {error && <ErrorNotice title={t("admin.actionError")} error={error} />}
      <EffectNotice savedAtLabel={savedAt !== null ? formatClock(savedAt) : undefined} ttlSeconds={ttlSeconds} />
      <DialogButtons saved={savedAt !== null} saving={saving} onSave={() => void save()} />
    </AdminDialog>
  );
}
