import { useCallback, useState } from "react";

import { toApiError, useResource } from "../../features/admin/useResource";
import { ApiError, api, type AuditEntry } from "../../lib/api";
import { t } from "../../lib/i18n";
import { TableScroll } from "../ui/TableScroll";
import { ErrorNotice, LoadingNote, ScreenTitle, TD, TH } from "./adminUi";
import {
  ACTION_LABEL,
  describeActor,
  describeChanges,
  describeTarget,
  limitWindows,
  type AuditChange,
  type AuditValue,
} from "./auditView";
import { formatShortDateTime } from "./format";

/**
 * Man 1f "Nhat ky quan tri" — §16.3, ban T-HD7 · T-2.20 → T-3.12 (B-191).
 *
 * KH tham chieu: §16.3, §20 · tasks.md T-2.20, T-3.12 (DoD dong 3), B-191.
 *
 * Doc tu `GET /admin/audit-logs`: moi nhat truoc, mot trang
 * `AUDIT_LOG_PAGE_SIZE` dong, "Tai them" theo `next_cursor` (con tro `id`,
 * xem `AuditLogRepository.list_page`). Cach doc mot dong thanh chu nam o
 * `auditView.ts` — file nay chi ve.
 *
 * ≥ 768 px: bang bon cot. < 768 px: danh sach xep chong — so audit khong co
 * cot de so sanh nen khong cuon ngang (ban T-HD7 muc 1h).
 */
export function AuditScreen() {
  // Trang dau qua `useResource` (mot request moi lan mo man, ke ca duoi
  // StrictMode); cac trang sau NOI vao duoi, theo `next_cursor`.
  const loadFirst = useCallback(() => api.adminAuditLogs(null), []);
  const first = useResource(loadFirst);
  const [more, setMore] = useState<AuditEntry[]>([]);
  const [moreCursor, setMoreCursor] = useState<number | null | undefined>(undefined);
  const [moreLoading, setMoreLoading] = useState(false);
  const [moreError, setMoreError] = useState<ApiError | null>(null);

  const items = [...(first.data?.items ?? []), ...more];
  const cursor = moreCursor === undefined ? (first.data?.next_cursor ?? null) : moreCursor;
  const loaded = first.data !== null;
  const error = moreError ?? first.error;

  const loadMore = async () => {
    if (cursor === null) {
      return;
    }
    setMoreLoading(true);
    setMoreError(null);
    try {
      const page = await api.adminAuditLogs(cursor);
      setMore((prev) => [...prev, ...page.items]);
      setMoreCursor(page.next_cursor);
    } catch (e) {
      setMoreError(toApiError(e));
    } finally {
      setMoreLoading(false);
    }
  };
  const loading = first.loading || moreLoading;

  return (
    <>
      <ScreenTitle>{t("admin.audit.title")}</ScreenTitle>
      {error && (
        <ErrorNotice
          title={t("admin.loadError")}
          error={error}
          onRetry={() => void (moreError !== null ? loadMore() : first.reload())}
        />
      )}
      {!loaded ? (
        loading && <LoadingNote />
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-border px-4 py-6 text-base text-muted">
          {t("admin.audit.empty")}
        </p>
      ) : (
        <>
          <div className="hidden min-w-0 md:block">
            <TableScroll label={t("admin.audit.title")}>
              <thead>
                <tr>
                  <th scope="col" className={TH}>
                    {t("admin.col.when")}
                  </th>
                  <th scope="col" className={TH}>
                    {t("admin.col.actor")}
                  </th>
                  <th scope="col" className={TH}>
                    {t("admin.col.action")}
                  </th>
                  <th scope="col" className={TH}>
                    {t("admin.col.target")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.id}>
                    <td className={`${TD} tabular whitespace-nowrap align-top text-muted`}>
                      {formatShortDateTime(e.created_at)}
                    </td>
                    <td className={`${TD} align-top`}>
                      <ActorCell entry={e} />
                    </td>
                    <td className={`${TD} align-top`}>
                      <ChangeCell entry={e} />
                    </td>
                    <td className={`${TD} align-top`}>
                      <TargetCell entry={e} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </TableScroll>
          </div>
          <ol className="flex flex-col divide-y divide-border rounded-lg border border-border bg-surface-panel md:hidden">
            {items.map((e) => (
              <li key={e.id} className="flex min-w-0 flex-col gap-2 px-4 py-3 text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <ActorCell entry={e} />
                  <span className="tabular text-xs text-muted">{formatShortDateTime(e.created_at)}</span>
                </div>
                <ChangeCell entry={e} />
                <TargetCell entry={e} />
              </li>
            ))}
          </ol>
          {cursor !== null && (
            <button
              type="button"
              disabled={loading}
              onClick={() => void loadMore()}
              className="motion-press min-h-touch self-start rounded-md border border-border-strong px-4 text-base font-medium text-foreground hover:bg-surface-hover disabled:opacity-50"
            >
              {t("admin.audit.loadMore")}
            </button>
          )}
        </>
      )}
    </>
  );
}

function ActorCell({ entry }: { entry: AuditEntry }) {
  const actor = describeActor(entry);
  if (actor.kind === "unknown") {
    return <span className="italic text-muted">{t("admin.actor.unknown")}</span>;
  }
  return (
    <span className="flex min-w-0 flex-col">
      <span className="break-all font-semibold text-foreground">{actor.name}</span>
      {actor.email !== null && <span className="break-all text-xs text-muted">{actor.email}</span>}
    </span>
  );
}

function valueText(value: AuditValue): string {
  if ("text" in value) {
    return value.text;
  }
  if ("key" in value) {
    return t(value.key);
  }
  return "—";
}

function ChangeLine({ change }: { change: AuditChange }) {
  const label = "key" in change.label ? t(change.label.key) : change.label.raw;
  return (
    <span className="flex flex-wrap items-center gap-1 font-mono text-xs text-muted">
      <span className="font-sans">{label}:</span>
      {change.from !== undefined && (
        <>
          <span className="break-all">{valueText(change.from)}</span>
          <span aria-hidden="true">→</span>
        </>
      )}
      <span className="break-all text-foreground">{valueText(change.to)}</span>
    </span>
  );
}

function ChangeCell({ entry }: { entry: AuditEntry }) {
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="flex flex-wrap items-baseline gap-1.5 text-foreground">
        <span>{t(ACTION_LABEL[entry.action])}</span>
        {limitWindows(entry).map((key) => (
          <span key={key} className="rounded-sm border border-border-strong px-1.5 text-2xs font-semibold">
            {t(key)}
          </span>
        ))}
      </span>
      {describeChanges(entry).map((change, i) => (
        <ChangeLine key={i} change={change} />
      ))}
    </span>
  );
}

function TargetCell({ entry }: { entry: AuditEntry }) {
  const target = describeTarget(entry);
  if (target.kind === "none") {
    return <span className="text-muted">—</span>;
  }
  const kindLabel =
    target.kind === "tier"
      ? t("admin.target.tier")
      : target.kind === "model"
        ? t("admin.target.model")
        : target.kind === "catalog"
        ? t("admin.target.catalog")
        : target.kind === "deletedUser"
          ? t("admin.target.deletedUser")
          : t("admin.target.user");
  return (
    <span className="flex min-w-0 flex-col items-start gap-0.5">
      <span className="text-2xs font-semibold uppercase tracking-wider text-muted">{kindLabel}</span>
      {target.kind === "user" && (
        <>
          <span className="break-all font-semibold text-foreground">{target.name}</span>
          {target.email !== null && <span className="break-all text-xs text-muted">{target.email}</span>}
        </>
      )}
      {(target.kind === "tier" || target.kind === "model") && (
        <span className="rounded-sm border border-border-strong px-1.5 font-mono text-sm text-foreground">
          {target.name}
        </span>
      )}
      {target.kind === "deletedUser" && (
        <span className="font-mono text-xs text-muted">{target.shortId}</span>
      )}
    </span>
  );
}
