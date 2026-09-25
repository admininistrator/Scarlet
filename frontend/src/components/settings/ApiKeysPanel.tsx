import * as Dialog from "@radix-ui/react-dialog";
import { CircleCheck, Trash2 } from "lucide";
import { useCallback, useId, useState, type FormEvent } from "react";

import { toApiError, useResource } from "../../features/admin/useResource";
import { api, type ApiError, type ProviderKey } from "../../lib/api";
import { t } from "../../lib/i18n";
import { AdminDialog } from "../admin/AdminDialog";
import { formatClockDate } from "../admin/format";
import { StaticIcon } from "../ui/Icon";

/**
 * Tab Khoa API (BYOK) — T-S.11, ban T-HD9 D (`ApiKeyRow`).
 *
 * KH tham chieu: §10.5, §20 · tasks.md T-2.14, T-3.12, T-S.11.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BAN RO CUA KHOA DI MOT CHIEU, MOT LAN (§20, T-2.14)                   ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * O nhap `type="password"`, `autoComplete="off"`, va bi XOA ngay TRUOC khi
 * cho server — thanh cong hay that bai. Thu duy nhat hien lai la `masked_key`
 * server tra (`sk-...4f2a`). Khong co nut "hien khoa", khong co ban sao trong
 * state nao song lau hon mot lan gui.
 *
 * Mot hang MOT provider (ban ve): danh sach la `byok_providers` cua server
 * (T-3.12 — khong mot mang go san nao), cong khoa da luu cua provider khong
 * con nhan khoa rieng (van xoa duoc). Co khoa ⇒ ban che + "Them luc" + Xoa;
 * chua co ⇒ o dan khoa + "Luu khoa". Xoa hoi lai trong mot Radix Dialog (ghi
 * chu cuoi `ApiKeyRow.tsx` cua ban ve).
 */

interface Row {
  provider: string;
  label: string;
  stored: ProviderKey | null;
}

function keyErrorText(error: ApiError): string {
  switch (error.code) {
    case "PROVIDER_KEY_REJECTED":
      return t("apiKeys.rejected");
    case "SERVICE_UNAVAILABLE":
      return t("apiKeys.unavailable");
    default:
      return `${t("settings.error")}: ${error.code}`;
  }
}

export function ApiKeysPanel() {
  const loadKeys = useCallback(() => api.listProviderKeys(), []);
  const keys = useResource(loadKeys);
  const [justSaved, setJustSaved] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<Row | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const rows: Row[] = [];
  if (keys.data !== null) {
    const stored = new Map(keys.data.keys.map((k) => [k.provider, k]));
    for (const p of keys.data.byok_providers) {
      rows.push({ provider: p.provider, label: p.label, stored: stored.get(p.provider) ?? null });
      stored.delete(p.provider);
    }
    for (const k of stored.values()) {
      rows.push({ provider: k.provider, label: k.provider, stored: k });
    }
  }

  const remove = async (row: Row) => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteProviderKey(row.provider);
      setConfirming(null);
      setJustSaved(null);
    } catch (err) {
      setDeleteError(keyErrorText(toApiError(err)));
    } finally {
      await keys.reload();
      setDeleting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <p className="mb-2 text-base text-muted">{t("apiKeys.intro")}</p>

      {keys.error && (
        <p role="alert" className="text-sm text-danger-text">
          {`${t("settings.error")}: ${keys.error.code}`}
        </p>
      )}

      {keys.data !== null && rows.length === 0 && (
        <p className="text-sm text-muted">{t("apiKeys.noProviders")}</p>
      )}

      {rows.length > 0 && (
        <div className="flex flex-col gap-px overflow-hidden rounded-lg border border-border bg-divider">
          {rows.map((row) => (
            <ApiKeyRow
              key={row.provider}
              row={row}
              justSaved={justSaved === row.provider}
              onSaved={async () => {
                setJustSaved(row.provider);
                await keys.reload();
              }}
              onDelete={() => {
                setDeleteError(null);
                setConfirming(row);
              }}
            />
          ))}
        </div>
      )}

      {confirming !== null && confirming.stored !== null && (
        <AdminDialog
          title={t("apiKeys.deleteTitle")}
          subtitle={`${confirming.label} · ${confirming.stored.masked_key}`}
          onClose={() => setConfirming(null)}
        >
          {deleteError !== null && (
            <p role="alert" className="text-sm text-danger-text">
              {deleteError}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <Dialog.Close className="motion-press min-h-touch rounded-md border border-border-strong px-4 text-base font-medium text-foreground hover:bg-surface-hover">
              {t("admin.cancel")}
            </Dialog.Close>
            <button
              type="button"
              disabled={deleting}
              onClick={() => void remove(confirming)}
              className="control-disabled motion-press inline-flex min-h-touch items-center gap-1.5 rounded-md bg-danger px-4 text-base font-semibold text-accent-foreground"
            >
              <StaticIcon icon={Trash2} size={16} className="shrink-0" />
              {t("apiKeys.delete")}
            </button>
          </div>
        </AdminDialog>
      )}
    </div>
  );
}

function ApiKeyRow({
  row,
  justSaved,
  onSaved,
  onDelete,
}: {
  row: Row;
  justSaved: boolean;
  onSaved: () => Promise<void>;
  onDelete: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const headingId = useId();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const plaintext = draft;
    // Xoa o nhap TRUOC khi cho server — ban ro khong song qua lan gui nay.
    setDraft("");
    setBusy(true);
    setError(null);
    try {
      await api.putProviderKey(row.provider, plaintext);
      await onSaved();
    } catch (err) {
      setError(keyErrorText(toApiError(err)));
    } finally {
      setBusy(false);
    }
  };

  const stored = row.stored;
  return (
    <div className="flex flex-col gap-2.5 bg-surface-panel px-4 py-3">
      <div className="flex min-h-touch min-w-0 items-center gap-3">
        <div className="flex min-w-0 flex-1 flex-col">
          <strong id={headingId} className="text-base font-semibold">
            {row.label}
          </strong>
          {stored !== null ? (
            <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-muted">
              <code className="font-mono text-sm text-foreground" data-testid="masked-key">
                {stored.masked_key}
              </code>
              <span className="flex gap-1">
                <span>{t("apiKeys.addedAt")}</span>
                <time dateTime={stored.created_at} className="tabular">
                  {formatClockDate(stored.created_at)}
                </time>
              </span>
              {!stored.usable && <span className="text-danger-text">{t("apiKeys.unusable")}</span>}
            </span>
          ) : (
            <span className="text-xs text-muted">{t("apiKeys.none")}</span>
          )}
        </div>
        <span role="status" className="text-sm font-medium text-success-text">
          {justSaved && (
            <span className="motion-enter flex items-center gap-1.5">
              <StaticIcon icon={CircleCheck} size={16} className="shrink-0" />
              {t("settings.saved")}
            </span>
          )}
        </span>
        {stored !== null && (
          <button
            type="button"
            aria-describedby={headingId}
            onClick={onDelete}
            className="motion-press inline-flex min-h-touch shrink-0 items-center gap-1.5 rounded-md px-3 text-base font-medium text-danger-text hover:bg-danger-subtle"
          >
            <StaticIcon icon={Trash2} size={16} className="shrink-0" />
            {t("apiKeys.delete")}
          </button>
        )}
      </div>
      {stored === null && (
        <form className="flex min-w-0 gap-2" autoComplete="off" onSubmit={(e) => void submit(e)}>
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            aria-labelledby={headingId}
            placeholder={t("apiKeys.placeholder")}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setError(null);
            }}
            className="motion-control h-touch min-w-0 flex-1 rounded-md border border-border-strong bg-background px-3 font-mono text-base text-foreground placeholder:text-muted focus-visible:border-ring"
          />
          <button
            type="submit"
            disabled={busy || draft.trim() === ""}
            className="control-disabled motion-press min-h-touch shrink-0 rounded-md bg-accent px-4.5 text-base font-semibold whitespace-nowrap text-accent-foreground enabled:hover:bg-accent-hover"
          >
            {busy ? t("apiKeys.verifying") : t("apiKeys.saveKey")}
          </button>
        </form>
      )}
      {error !== null && (
        <p role="alert" className="text-sm text-danger-text">
          {error}
        </p>
      )}
    </div>
  );
}
