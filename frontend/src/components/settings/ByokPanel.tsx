import * as Dialog from "@radix-ui/react-dialog";
import {
  Check,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  Eye,
  EyeOff,
  Info,
  LoaderCircle,
  Lock,
  Pencil,
  Plug,
  Plus,
  Search,
  Trash2,
  TriangleAlert,
  X,
  type IconNode,
} from "lucide";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";

import { toApiError, useResource } from "../../features/admin/useResource";
import { api, type ApiError, type ByokEndpoint, type ProviderKey } from "../../lib/api";
import { t, type TextKey } from "../../lib/i18n";
import { newKey } from "../../lib/idempotency";
import { formatClockDate, formatCount } from "../admin/format";
import { StaticIcon } from "../ui/Icon";

/**
 * Tab BYOK — T-S.19c, ban T-HD10 (`Scarlet BYOK.dc.html`, ma kem `ByokSettings.tsx`).
 * Thay tab Khoa API (T-S.11) o vi tri thu tu, duong `/cai-dat/byok`.
 *
 * KH tham chieu: §10.5, §12.2, §11.4, §20 · C20, C22, C42, C43 · CLAUDE.md A5,
 * A8 · NQ-134 ② ③, NQ-137 · tasks.md T-2.14, T-S.19b, T-S.19c.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHOA DI MOT CHIEU · TAB KHONG CO USD                                  ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Server chi tra ban che (`masked_key`). Khoa dang go chi song trong state
 * cua o nhap: hang provider XOA o nhap truoc khi cho server (T-2.14, thanh
 * cong hay that bai); form endpoint giu khoa toi khi Luu xong (can no cho ca
 * Kiem tra lan Luu) roi go ca form. Loi kiem tra la MA (`URL_UNSAFE`,
 * `PROVIDER_KEY_REJECTED`, `SERVICE_UNAVAILABLE`) — cau goc cua endpoint
 * khong toi trinh duyet. Luot BYOK chi dem token (NQ-134 ③): moi khoa / moi
 * endpoint mang Token vao + Token ra.
 *
 * Chan localhost / mang noi bo / IP rieng la viec cua MAY CHU (A5, §12.2 lop
 * 2–4). Trinh duyet chi kiem hinh thuc: https + `/v1`.
 */

/** > 8 model thi hien o loc (ban T-HD10, `FILTER_AFTER`). */
const FILTER_AFTER = 8;

/* ---------- Class dung chung (chi tien ich sinh tu theme.css) ---------- */
const INPUT =
  "motion-control h-touch w-full min-w-0 rounded-md border border-border-strong bg-background px-3 text-input " +
  "text-foreground placeholder:text-muted focus-visible:border-ring focus-visible:shadow-focus focus-visible:outline-none " +
  "aria-invalid:border-danger-text aria-invalid:shadow-invalid";
const BTN =
  "motion-press inline-flex min-h-touch shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md font-semibold";
const BTN_PRIMARY = `${BTN} bg-accent px-4.5 text-accent-foreground enabled:hover:bg-accent-hover`;
const BTN_SECONDARY = `${BTN} border border-border-strong bg-surface-panel px-4 text-foreground hover:bg-surface-hover aria-disabled:hover:bg-surface-panel`;
const BTN_GHOST = `${BTN} px-3 font-medium text-foreground hover:bg-surface-hover`;
const BTN_DANGER_GHOST = `${BTN} px-3 font-medium text-danger-text hover:bg-danger-subtle`;

const fold = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

const hostOf = (baseUrl: string) => {
  try {
    return new URL(baseUrl).host;
  } catch {
    return baseUrl;
  }
};

/** Kiem HINH THUC o trinh duyet; chan IP rieng / DNS la viec cua server (A5). */
export function validateBaseUrl(raw: string): "byok.form.urlNotHttps" | "byok.form.urlNoV1" | null {
  const v = raw.trim().replace(/\/+$/, "");
  if (!/^https:\/\/[^/\s]+/i.test(v)) {
    return "byok.form.urlNotHttps";
  }
  if (!v.endsWith("/v1")) {
    return "byok.form.urlNoV1";
  }
  return null;
}

/** Cau loi chung cho ma khong co cho rieng tren ban ve. */
function genericError(error: ApiError): string {
  return `${t("settings.error")}: ${error.code}`;
}

/**
 * Nut co trang thai cho. Dang cho: `aria-disabled` + `aria-busy`, KHONG mo (bo
 * `control-disabled`), giu focus tren nut trong luc cho.
 */
function BusyButton({
  busy,
  disabled,
  className,
  children,
  type = "button",
  onClick,
  describedBy,
}: {
  busy: boolean;
  disabled?: boolean;
  className: string;
  children: ReactNode;
  type?: "button" | "submit";
  onClick?: () => void;
  describedBy?: string;
}) {
  return (
    <button
      type={type}
      onClick={busy ? undefined : onClick}
      disabled={!busy && disabled}
      aria-disabled={busy || undefined}
      aria-busy={busy || undefined}
      aria-describedby={describedBy}
      className={(busy ? "" : "control-disabled ") + className}
    >
      {busy ? (
        <>
          <StaticIcon icon={LoaderCircle} size={16} className="motion-spin" />
          {t("byok.checking")}
        </>
      ) : (
        children
      )}
    </button>
  );
}

function SavedStatus({ show }: { show: boolean }) {
  // `role="status"` co san tu dau ⇒ trinh doc man hinh doc khi chu xuat hien.
  return (
    <p role="status" className="text-sm font-medium text-success-text">
      {show && (
        <span className="motion-enter flex items-center gap-1.5">
          <StaticIcon icon={CircleCheck} size={16} />
          {t("settings.saved")}
        </span>
      )}
    </p>
  );
}

function TokenLine({ tokensIn, tokensOut, createdAt }: { tokensIn: number; tokensOut: number; createdAt?: string }) {
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted">
      {createdAt !== undefined && (
        <div className="flex gap-1">
          <dt>{t("apiKeys.addedAt")}</dt>
          <dd>
            <time dateTime={createdAt} className="tabular">
              {formatClockDate(createdAt)}
            </time>
          </dd>
        </div>
      )}
      <div className="flex gap-1">
        <dt>{t("byok.tokensIn")}</dt>
        <dd className="tabular font-medium text-foreground">{formatCount(tokensIn)}</dd>
      </div>
      <div className="flex gap-1">
        <dt>{t("byok.tokensOut")}</dt>
        <dd className="tabular font-medium text-foreground">{formatCount(tokensOut)}</dd>
      </div>
    </dl>
  );
}

function FieldError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} className="flex items-start gap-1.5 text-sm text-danger-text">
      <StaticIcon icon={CircleAlert} size={16} className="mt-0.5 shrink-0" />
      {children}
    </p>
  );
}

const focusSoon = (ref: { current: HTMLElement | null }) => requestAnimationFrame(() => ref.current?.focus());

/* =================================================================================== */

export function ByokPanel() {
  const keys = useResource(api.listProviderKeys);
  const endpoints = useResource(api.listByokEndpoints);
  const error = keys.error ?? endpoints.error;

  return (
    // Ban T-HD9 D / T-HD10: tieu de tab → noi dung 16 o desktop (cac tab khac 24) ⇒ `lg:-mt-2`.
    <div className="flex flex-col gap-8 lg:-mt-2">
      <div className="flex flex-col gap-1.5">
        <p className="text-muted">{t("apiKeys.intro")}</p>
        <p className="flex items-start gap-2 font-medium">
          <StaticIcon icon={Info} size={16} className="mt-0.75 shrink-0 text-muted" />
          {t("byok.freeNote")}
        </p>
      </div>
      {error && (
        <p role="alert" className="text-sm text-danger-text">
          {genericError(error)}
        </p>
      )}
      {keys.data !== null && <ProviderSection keys={keys.data.keys} providers={keys.data.byok_providers} onChanged={keys.reload} />}
      {endpoints.data !== null && (
        <EndpointSection
          endpoints={endpoints.data.endpoints}
          limit={endpoints.data.max_endpoints}
          onChanged={endpoints.reload}
        />
      )}
    </div>
  );
}

/* ---------- Khoi 1 — provider co san ---------- */

type KeyStatus = "verified" | "unverified" | "unreadable";
const STATUS: Record<KeyStatus, { icon: IconNode; className: string; labelKey: TextKey }> = {
  verified: { icon: CircleCheck, className: "text-success-text", labelKey: "byok.status.verified" },
  unverified: { icon: CircleDashed, className: "text-muted", labelKey: "byok.status.unverified" },
  unreadable: { icon: TriangleAlert, className: "text-warning-text", labelKey: "byok.status.unreadable" },
};

function statusOf(key: ProviderKey): KeyStatus {
  if (!key.usable) {
    return "unreadable";
  }
  return key.verified_at === null ? "unverified" : "verified";
}

function providerError(error: ApiError): string {
  switch (error.code) {
    case "PROVIDER_KEY_REJECTED":
      return t("apiKeys.rejected");
    case "SERVICE_UNAVAILABLE":
      return t("apiKeys.unavailable");
    default:
      return genericError(error);
  }
}

interface ProviderRow {
  provider: string;
  label: string;
  stored: ProviderKey | null;
}

function ProviderSection({
  keys,
  providers,
  onChanged,
}: {
  keys: ProviderKey[];
  providers: { provider: string; label: string }[];
  onChanged: () => Promise<void>;
}) {
  // Danh sach la `byok_providers` cua server (T-3.12), cong khoa da luu cua
  // provider khong con nhan khoa rieng (van xoa duoc).
  const stored = new Map(keys.map((k) => [k.provider, k]));
  const rows: ProviderRow[] = providers.map((p) => ({ ...p, stored: stored.get(p.provider) ?? null }));
  for (const k of keys) {
    if (!providers.some((p) => p.provider === k.provider)) {
      rows.push({ provider: k.provider, label: k.provider, stored: k });
    }
  }
  return (
    <section aria-labelledby="byok-providers" className="flex flex-col gap-3">
      <h3 id="byok-providers" className="text-lg font-semibold">
        {t("byok.providers.title")}
      </h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">{t("apiKeys.noProviders")}</p>
      ) : (
        <div className="flex flex-col gap-px overflow-hidden rounded-lg border border-border bg-divider">
          {rows.map((row) => (
            <ProviderKeyRow key={row.provider} row={row} onChanged={onChanged} />
          ))}
        </div>
      )}
    </section>
  );
}

function ProviderKeyRow({ row, onChanged }: { row: ProviderRow; onChanged: () => Promise<void> }) {
  const headingId = useId();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { stored } = row;
  const status = stored === null ? null : STATUS[statusOf(stored)];
  // Khong doc duoc nua ⇒ nhap lai TAI CHO (ban T-HD10 2b).
  const needsInput = stored === null || !stored.usable;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const plaintext = draft.trim();
    if (plaintext === "" || busy) {
      return;
    }
    // T-2.14 / §20: xoa o nhap TRUOC khi cho server — ban ro khong song qua lan gui nay.
    setDraft("");
    setBusy(true);
    setSaved(false);
    setError(null);
    try {
      await api.putProviderKey(row.provider, plaintext);
      setSaved(true);
      await onChanged();
    } catch (err) {
      setError(providerError(toApiError(err)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2 bg-surface-panel px-4 py-3">
      <div className="flex min-h-touch items-center gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <strong id={headingId} className="font-semibold">
            {row.label}
          </strong>
          {stored !== null && status !== null ? (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <code className="font-mono text-sm text-foreground" data-testid="masked-key">
                {stored.masked_key}
              </code>
              <span className={`inline-flex items-center gap-1 text-xs font-medium ${status.className}`}>
                <StaticIcon icon={status.icon} size={14} />
                {t(status.labelKey)}
              </span>
            </span>
          ) : (
            <span className="text-xs text-muted">{t("apiKeys.none")}</span>
          )}
        </div>
        <SavedStatus show={saved} />
        {stored !== null && (
          <ConfirmDelete
            describedBy={headingId}
            titleKey="byok.deleteKey.title"
            bodyKey="byok.deleteKey.body"
            confirmKey="apiKeys.delete"
            subject={row.label}
            detail={stored.masked_key}
            onConfirm={async () => {
              await api.deleteProviderKey(row.provider);
              setSaved(false);
              await onChanged();
            }}
          />
        )}
      </div>
      {stored !== null && (
        <TokenLine tokensIn={stored.prompt_tokens} tokensOut={stored.completion_tokens} createdAt={stored.created_at} />
      )}
      {needsInput && (
        <form onSubmit={(e) => void submit(e)} autoComplete="off" className="flex min-w-0 gap-2">
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            aria-labelledby={headingId}
            readOnly={busy}
            placeholder={t(stored === null ? "apiKeys.placeholder" : "byok.newKeyPlaceholder")}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setError(null);
            }}
            className="motion-control h-touch min-w-0 flex-1 rounded-md border border-border-strong bg-background px-3 font-mono text-foreground placeholder:text-muted focus-visible:border-ring"
          />
          <BusyButton type="submit" busy={busy} disabled={draft.trim() === ""} className={BTN_PRIMARY}>
            {t("apiKeys.saveKey")}
          </BusyButton>
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

/* ---------- Khoi 2 — endpoint tuy chinh ---------- */

function EndpointSection({
  endpoints,
  limit,
  onChanged,
}: {
  endpoints: ByokEndpoint[];
  limit: number;
  onChanged: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [saved, setSaved] = useState(false);
  const addRef = useRef<HTMLButtonElement>(null);
  const limitId = useId();
  // Tran do server gui (`BYOK_ENDPOINTS_MAX_PER_USER`, NQ-137 ①) — khong mot con so nao o FE (A3).
  const atMax = endpoints.length >= limit;
  const open = () => {
    if (!atMax) {
      setSaved(false);
      setAdding(true);
    }
  };
  const close = (didSave: boolean) => {
    setAdding(false);
    setSaved(didSave);
    focusSoon(addRef);
  };

  return (
    <section aria-labelledby="byok-endpoints" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex min-w-0 flex-col">
          <h3 id="byok-endpoints" className="text-lg font-semibold">
            {t("byok.endpoints.title")}
          </h3>
          <p className="text-sm text-muted">{t("byok.endpoints.hint")}</p>
        </div>
        {endpoints.length > 0 && (
          <p className="tabular flex gap-1 text-sm text-muted">
            <span className="sr-only">{t("byok.endpoints.countLabel")}</span>
            <span className="font-semibold text-foreground">{endpoints.length}</span>
            <span aria-hidden>/</span>
            <span>{limit}</span>
          </p>
        )}
      </div>

      {endpoints.map((ep) => (
        <EndpointCard
          key={ep.id}
          endpoint={ep}
          takenNames={endpoints.filter((x) => x.id !== ep.id).map((x) => x.label)}
          onChanged={onChanged}
        />
      ))}
      {endpoints.length > 0 && (
        <p className="flex items-start gap-2 text-sm text-muted">
          <StaticIcon icon={Lock} size={14} className="mt-0.75 shrink-0" />
          {t("byok.endpoints.changeNote")}
        </p>
      )}

      {adding ? (
        <AddEndpointForm
          takenNames={endpoints.map((x) => x.label)}
          onCancel={() => close(false)}
          onSaved={async () => {
            await onChanged();
            close(true);
          }}
        />
      ) : endpoints.length === 0 ? (
        <div className="flex flex-col items-center gap-2.5 rounded-lg border border-dashed border-border-strong px-6 py-7 text-center">
          <span className="grid size-touch place-items-center rounded-full bg-surface-hover text-muted">
            <StaticIcon icon={Plug} size={22} />
          </span>
          <h4 className="text-body font-semibold">{t("byok.empty.title")}</h4>
          <p className="max-w-md text-muted">{t("byok.empty.body")}</p>
          <button ref={addRef} type="button" onClick={open} className={`${BTN_SECONDARY} mt-1`}>
            <StaticIcon icon={Plus} size={16} />
            {t("byok.endpoints.add")}
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {/* Khoa vi dieu kien: aria-disabled (giu focus duoc) + ly do hien san, khong can tooltip. */}
          <button
            ref={addRef}
            type="button"
            aria-disabled={atMax || undefined}
            aria-describedby={atMax ? limitId : undefined}
            onClick={open}
            className={`control-disabled ${BTN_SECONDARY}`}
          >
            <StaticIcon icon={Plus} size={16} />
            {t("byok.endpoints.add")}
          </button>
          {atMax && (
            <p id={limitId} className="min-w-0 flex-[1_1_15rem] text-sm text-muted">
              {t("byok.endpoints.limitReached")}
            </p>
          )}
          <SavedStatus show={saved && !atMax} />
        </div>
      )}
    </section>
  );
}

function MaskedLine({ endpoint }: { endpoint: ByokEndpoint }) {
  return (
    <>
      <span className="text-foreground wrap-anywhere">{hostOf(endpoint.base_url)}</span>
      <span aria-hidden>·</span>
      <code className="font-mono">{endpoint.masked_key}</code>
    </>
  );
}

function EndpointCard({
  endpoint: ep,
  takenNames,
  onChanged,
}: {
  endpoint: ByokEndpoint;
  takenNames: string[];
  onChanged: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const editRef = useRef<HTMLButtonElement>(null);
  const headingId = useId();
  if (editing) {
    return (
      <EndpointEditor
        endpoint={ep}
        takenNames={takenNames}
        onDone={async (changed) => {
          if (changed) {
            await onChanged();
          }
          setEditing(false);
          focusSoon(editRef);
        }}
      />
    );
  }
  return (
    <article
      aria-labelledby={headingId}
      className="motion-enter flex flex-col gap-3 rounded-lg border border-border bg-surface-panel p-4"
    >
      <div className="flex items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <h4 id={headingId} className="text-body font-semibold wrap-anywhere">
            {ep.label}
          </h4>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-muted">
            <MaskedLine endpoint={ep} />
          </span>
        </div>
        <div className="-mt-1 -mr-2 flex gap-1">
          <button
            ref={editRef}
            type="button"
            aria-describedby={headingId}
            onClick={() => setEditing(true)}
            className={BTN_GHOST}
          >
            <StaticIcon icon={Pencil} size={16} />
            {t("byok.endpoints.edit")}
          </button>
          <ConfirmDelete
            describedBy={headingId}
            titleKey="byok.delete.title"
            bodyKey="byok.delete.body"
            confirmKey="byok.delete.confirm"
            subject={ep.label}
            detail={hostOf(ep.base_url)}
            onConfirm={async () => {
              await api.deleteByokEndpoint(ep.id);
              await onChanged();
            }}
          />
        </div>
      </div>
      <ul aria-label={t("byok.endpoints.models")} className="flex flex-wrap gap-1.5">
        {ep.models.map((m) => (
          <li
            key={m}
            title={m}
            className="inline-flex max-w-byok-chip rounded-full border border-border bg-background px-2.5 py-0.75 font-mono text-xs text-foreground"
          >
            <span className="truncate">{m}</span>
          </li>
        ))}
      </ul>
      <div className="border-t border-divider pt-2.5">
        <TokenLine tokensIn={ep.prompt_tokens} tokensOut={ep.completion_tokens} />
      </div>
    </article>
  );
}

/** Sua: chi ten va danh sach model. URL + khoa khong co o nao o day (§10.5). */
function EndpointEditor({
  endpoint: ep,
  takenNames,
  onDone,
}: {
  endpoint: ByokEndpoint;
  takenNames: string[];
  onDone: (changed: boolean) => Promise<void>;
}) {
  const nameId = useId();
  const nameErrId = useId();
  const [name, setName] = useState(ep.label);
  const [picked, setPicked] = useState<string[]>(ep.models);
  // `undefined` = dang tai; `null` = endpoint khong tra danh sach (hoac hoi
  // khong duoc) ⇒ go tay, model da luu van nam o do.
  const [available, setAvailable] = useState<string[] | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [serverTaken, setServerTaken] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.listByokEndpointModels(ep.id).then(
      (r) => live && setAvailable(r.models.length > 0 ? r.models : null),
      () => live && setAvailable(null),
    );
    return () => {
      live = false;
    };
  }, [ep.id]);

  const taken = serverTaken || takenNames.some((n) => fold(n.trim()) === fold(name.trim()));
  const dirty = name.trim() !== ep.label || picked.join("\n") !== ep.models.join("\n");
  const canSave = dirty && name.trim() !== "" && !taken && picked.length > 0 && !busy;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSave) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.updateByokEndpoint(ep.id, { label: name.trim(), models: picked });
      await onDone(true);
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.code === "BYOK_ENDPOINT_LABEL_TAKEN") {
        setServerTaken(true);
      } else {
        setError(genericError(apiError));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => void submit(e)}
      aria-label={t("byok.endpoints.editTitle")}
      className="flex flex-col gap-4 rounded-lg border border-border-strong bg-surface-panel p-4"
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor={nameId} className="text-sm font-semibold">
          {t("byok.form.name")}
        </label>
        <input
          id={nameId}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setServerTaken(false);
          }}
          aria-invalid={taken || undefined}
          aria-describedby={taken ? nameErrId : undefined}
          className={INPUT}
        />
        {taken && <FieldError id={nameErrId}>{t("byok.form.nameTaken")}</FieldError>}
      </div>
      <div className="flex flex-col gap-1 text-sm text-muted">
        <span className="flex flex-wrap gap-x-2">
          <MaskedLine endpoint={ep} />
        </span>
        <span className="flex items-start gap-2">
          <StaticIcon icon={Lock} size={14} className="mt-0.75 shrink-0" />
          {t("byok.endpoints.changeNote")}
        </span>
      </div>
      {available === undefined ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <StaticIcon icon={LoaderCircle} size={16} className="motion-spin" />
          {t("byok.checking")}
        </p>
      ) : (
        <ModelSelect
          available={available === null ? null : Array.from(new Set([...available, ...ep.models]))}
          picked={picked}
          onChange={setPicked}
        />
      )}
      {error !== null && (
        <p role="alert" className="text-sm text-danger-text">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3 border-t border-divider pt-4">
        <BusyButton type="submit" busy={busy} disabled={!canSave} className={`${BTN_PRIMARY} px-5.5`}>
          {t("settings.save")}
        </BusyButton>
        <button type="button" onClick={() => void onDone(false)} className={BTN_GHOST}>
          {t("byok.form.cancel")}
        </button>
      </div>
    </form>
  );
}

/* ---------- Form "Them endpoint" ---------- */

type TestError = "url_blocked" | "key_rejected" | "unreachable";
type Phase =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "ok"; models: string[] | null }
  | { kind: "error"; error: TestError }
  | { kind: "failed"; message: string };

/** Ma loi cua `probe` / `POST` → trang thai cua form (ban T-HD10 1c, 3b, 3c). */
function testPhase(error: ApiError): Phase {
  switch (error.code) {
    case "URL_UNSAFE":
      return { kind: "error", error: "url_blocked" };
    case "PROVIDER_KEY_REJECTED":
      return { kind: "error", error: "key_rejected" };
    case "SERVICE_UNAVAILABLE":
    case "HTTP_ERROR":
      return { kind: "error", error: "unreachable" };
    default:
      return { kind: "failed", message: genericError(error) };
  }
}

function AddEndpointForm({
  takenNames,
  onCancel,
  onSaved,
}: {
  takenNames: string[];
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  const id = useId();
  const ids = {
    title: `${id}t`,
    name: `${id}n`,
    nameMsg: `${id}nm`,
    url: `${id}u`,
    urlHint: `${id}uh`,
    urlErr: `${id}ue`,
    key: `${id}k`,
    keyErr: `${id}ke`,
    saveHint: `${id}sh`,
  };
  const nameRef = useRef<HTMLInputElement>(null);
  // C22 / A8: MOT khoa cho MOT lan soan form, giu qua moi lan Luu hong; form
  // go sau lan Luu thanh cong nen lan mo sau la khoa moi.
  const [idempotencyKey] = useState(newKey);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [urlTouched, setUrlTouched] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [picked, setPicked] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [serverTaken, setServerTaken] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  const nameTaken =
    serverTaken || (name.trim() !== "" && takenNames.some((n) => fold(n.trim()) === fold(name.trim())));
  const urlFormat = baseUrl.trim() === "" ? null : validateBaseUrl(baseUrl);
  const urlError =
    urlFormat !== null && urlTouched
      ? t(urlFormat)
      : phase.kind === "error" && phase.error === "url_blocked"
        ? t("byok.form.urlBlocked")
        : null;
  const keyError = phase.kind === "error" && phase.error === "key_rejected" ? t("byok.form.keyRejected") : null;
  const canTest = name.trim() !== "" && !nameTaken && baseUrl.trim() !== "" && urlFormat === null && apiKey.trim() !== "";
  const canSave = phase.kind === "ok" && picked.length > 0 && !nameTaken && !saving;

  // Doi URL hoac khoa ⇒ ket qua kiem cu het hieu luc, Luu tat lai. Doi ten thi khong.
  const invalidate = () => {
    if (phase.kind !== "idle") {
      setPhase({ kind: "idle" });
      setPicked([]);
    }
  };

  const test = async () => {
    if (!canTest) {
      return;
    }
    setPhase({ kind: "testing" });
    try {
      const r = await api.probeByokEndpoint(baseUrl.trim(), apiKey.trim());
      setPhase({ kind: "ok", models: r.models.length > 0 ? r.models : null });
    } catch (err) {
      setPhase(testPhase(toApiError(err)));
    }
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSave) {
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await api.createByokEndpoint(
        { label: name.trim(), base_url: baseUrl.trim(), key: apiKey.trim(), models: picked },
        idempotencyKey,
      );
      setApiKey("");
      await onSaved();
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.code === "BYOK_ENDPOINT_LABEL_TAKEN") {
        setServerTaken(true);
      } else if (apiError.code === "BYOK_ENDPOINT_LIMIT") {
        setSaveError(t("byok.endpoints.limitReached"));
      } else {
        // Server kiem lai truoc khi luu (§10.5): khoa / URL co the da hong tu luc Kiem tra.
        const next = testPhase(apiError);
        if (next.kind === "failed") {
          setSaveError(next.message);
        } else {
          setPhase(next);
          setPicked([]);
        }
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={(e) => void submit(e)}
      noValidate
      autoComplete="off"
      aria-labelledby={ids.title}
      className="motion-enter flex flex-col gap-5 rounded-lg border border-border bg-surface-panel p-5"
    >
      <h4 id={ids.title} className="text-body font-semibold">
        {t("byok.form.title")}
      </h4>

      <div className="flex flex-col gap-1.5">
        <label htmlFor={ids.name} className="text-sm font-semibold">
          {t("byok.form.name")}
        </label>
        <input
          ref={nameRef}
          id={ids.name}
          autoComplete="off"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setServerTaken(false);
          }}
          aria-invalid={nameTaken || undefined}
          aria-describedby={ids.nameMsg}
          className={INPUT}
        />
        {nameTaken ? (
          <FieldError id={ids.nameMsg}>{t("byok.form.nameTaken")}</FieldError>
        ) : (
          <p id={ids.nameMsg} className="text-sm text-muted">
            {t("byok.form.nameHint")}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor={ids.url} className="text-sm font-semibold">
          {t("byok.form.baseUrl")}
        </label>
        <input
          id={ids.url}
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder={t("byok.form.baseUrlPlaceholder")}
          value={baseUrl}
          onChange={(e) => {
            setBaseUrl(e.target.value);
            invalidate();
          }}
          onBlur={() => setUrlTouched(true)}
          aria-invalid={urlError !== null || undefined}
          aria-describedby={(urlError !== null ? `${ids.urlErr} ` : "") + ids.urlHint}
          className={INPUT}
        />
        {urlError !== null && <FieldError id={ids.urlErr}>{urlError}</FieldError>}
        <p id={ids.urlHint} className="text-sm text-muted">
          {t("byok.form.baseUrlHint")}
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor={ids.key} className="text-sm font-semibold">
          {t("byok.form.apiKey")}
        </label>
        <div className="relative flex">
          <input
            id={ids.key}
            type={showKey ? "text" : "password"}
            autoComplete="off"
            spellCheck={false}
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              invalidate();
            }}
            aria-invalid={keyError !== null || undefined}
            aria-describedby={keyError !== null ? ids.keyErr : undefined}
            className={`${INPUT} pr-13 font-mono`}
          />
          <button
            type="button"
            aria-label={t("byok.form.showKey")}
            aria-pressed={showKey}
            aria-controls={ids.key}
            onClick={() => setShowKey((s) => !s)}
            className="motion-control absolute inset-y-0 right-0 grid size-touch place-items-center rounded-md text-muted hover:text-foreground"
          >
            <StaticIcon icon={showKey ? EyeOff : Eye} size={18} />
          </button>
        </div>
        {keyError !== null && <FieldError id={ids.keyErr}>{keyError}</FieldError>}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5">
        <BusyButton
          busy={phase.kind === "testing"}
          disabled={!canTest}
          onClick={() => void test()}
          className={BTN_SECONDARY}
        >
          {t("byok.form.test")}
        </BusyButton>
        <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          {phase.kind === "ok" && (
            <span className="motion-enter flex items-center gap-1.5 font-medium text-success-text">
              <StaticIcon icon={CircleCheck} size={16} />
              {t("byok.form.connected")}
            </span>
          )}
          {phase.kind === "ok" && phase.models !== null && (
            <span className="flex gap-1 text-muted">
              <span>{t("byok.form.modelsFound")}</span>
              <span className="tabular font-semibold text-foreground">{phase.models.length}</span>
            </span>
          )}
          {phase.kind === "error" && phase.error === "unreachable" && (
            <span className="flex items-center gap-1.5 font-medium text-danger-text">
              <StaticIcon icon={CircleAlert} size={16} />
              {t("byok.form.unreachable")}
            </span>
          )}
          {phase.kind === "failed" && (
            <span className="flex items-center gap-1.5 font-medium text-danger-text">
              <StaticIcon icon={CircleAlert} size={16} />
              {phase.message}
            </span>
          )}
        </div>
      </div>

      {phase.kind === "ok" && <ModelSelect available={phase.models} picked={picked} onChange={setPicked} />}

      <div className="flex flex-wrap items-center gap-3 border-t border-divider pt-5">
        <BusyButton
          type="submit"
          busy={saving}
          disabled={!canSave}
          describedBy={canSave ? undefined : ids.saveHint}
          className={`${BTN_PRIMARY} px-5.5`}
        >
          {t("settings.save")}
        </BusyButton>
        <button type="button" onClick={onCancel} className={BTN_GHOST}>
          {t("byok.form.cancel")}
        </button>
        {saveError !== null && (
          <p role="alert" className="min-w-0 basis-full text-sm text-danger-text">
            {saveError}
          </p>
        )}
        {!canSave && !saving && (
          <p id={ids.saveHint} className="min-w-0 basis-full text-sm text-muted">
            {t("byok.form.saveHint")}
          </p>
        )}
      </div>
    </form>
  );
}

/** Chon model: danh sach checkbox (loc khi > 8) hoac go tay khi endpoint khong tra danh sach. */
function ModelSelect({
  available,
  picked,
  onChange,
}: {
  available: string[] | null;
  picked: string[];
  onChange: (next: string[]) => void;
}) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const shown = useMemo(() => {
    const list = available ?? [];
    const q = fold(query.trim());
    return q === "" ? list : list.filter((m) => fold(m).includes(q));
  }, [available, query]);
  const toggle = useCallback(
    (m: string) => onChange(picked.includes(m) ? picked.filter((x) => x !== m) : [...picked, m]),
    [onChange, picked],
  );
  const addTyped = () => {
    const m = draft.trim();
    if (m !== "" && !picked.includes(m)) {
      onChange([...picked, m]);
    }
    setDraft("");
  };

  if (available === null) {
    return (
      <div className="flex flex-col gap-2.5">
        <p className="text-sm text-muted">{t("byok.form.noList")}</p>
        <label htmlFor={id} className="text-sm font-semibold">
          {t("byok.form.modelName")}
        </label>
        <div className="flex gap-2">
          <input
            id={id}
            value={draft}
            placeholder={t("byok.form.modelNamePlaceholder")}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addTyped();
              }
            }}
            className={`${INPUT} flex-1 font-mono`}
          />
          <button
            type="button"
            onClick={addTyped}
            disabled={draft.trim() === ""}
            className={`control-disabled ${BTN_SECONDARY}`}
          >
            <StaticIcon icon={Plus} size={16} />
            {t("byok.form.addModel")}
          </button>
        </div>
        {picked.length > 0 && (
          <ul aria-label={t("byok.endpoints.models")} className="flex flex-wrap gap-1.5">
            {picked.map((m, i) => (
              <li
                key={m}
                className="inline-flex min-h-touch max-w-full items-center rounded-full border border-border-strong bg-background pl-3"
              >
                <span id={`${id}c${i}`} className="min-w-0 truncate font-mono text-sm">
                  {m}
                </span>
                <button
                  type="button"
                  aria-label={t("byok.form.removeModel")}
                  aria-describedby={`${id}c${i}`}
                  onClick={() => toggle(m)}
                  className="motion-control grid size-touch shrink-0 place-items-center rounded-full text-muted hover:bg-surface-hover hover:text-foreground"
                >
                  <StaticIcon icon={X} size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <fieldset className="flex min-w-0 flex-col gap-2.5">
      <legend className="mb-2.5 text-sm font-semibold">{t("byok.form.pickModels")}</legend>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        {available.length > FILTER_AFTER && (
          <div className="relative flex min-w-0 flex-[1_1_13.75rem]">
            <StaticIcon
              icon={Search}
              size={16}
              className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted"
            />
            <input
              type="search"
              aria-label={t("byok.form.filter")}
              placeholder={t("byok.form.filter")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className={`${INPUT} pl-10`}
            />
          </div>
        )}
        <p className="tabular flex gap-1 text-sm text-muted">
          <span>{t("byok.form.selectedPrefix")}</span>
          <span className="font-semibold text-foreground">{picked.length}</span>
        </p>
      </div>
      <div className="max-h-byok-list overflow-y-auto overscroll-contain rounded-md border border-border py-1">
        {shown.length === 0 && <p className="px-3 py-2.5 text-sm text-muted">{t("byok.form.filterEmpty")}</p>}
        {shown.map((m) => (
          <label
            key={m}
            className="group motion-control relative flex min-h-touch items-center gap-3 px-3 py-1.5 hover:bg-surface-hover"
          >
            <input type="checkbox" className="peer sr-only" checked={picked.includes(m)} onChange={() => toggle(m)} />
            <span
              aria-hidden
              className="grid size-4.5 shrink-0 place-items-center rounded-sm border-2 border-border-strong text-accent-foreground group-has-checked:border-accent group-has-checked:bg-accent peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ring"
            >
              <StaticIcon icon={Check} size={12} className="hidden group-has-checked:block" />
            </span>
            <span className="min-w-0 font-mono text-sm wrap-anywhere">{m}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/* ---------- Xac nhan xoa (Radix Dialog) — ban T-HD10 3g, 3h ---------- */

function ConfirmDelete({
  describedBy,
  titleKey,
  bodyKey,
  confirmKey,
  subject,
  detail,
  onConfirm,
}: {
  describedBy: string;
  titleKey: TextKey;
  bodyKey: TextKey;
  confirmKey: TextKey;
  subject: string;
  detail: string;
  onConfirm: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      setOpen(false);
    } catch (err) {
      setError(genericError(toApiError(err)));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        setError(null);
      }}
    >
      <Dialog.Trigger asChild>
        <button type="button" aria-describedby={describedBy} className={BTN_DANGER_GHOST}>
          <StaticIcon icon={Trash2} size={16} />
          {t("apiKeys.delete")}
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="motion-scrim fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className="motion-panel fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-dialog -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface-panel p-6 text-foreground shadow-popover">
          <Dialog.Title className="text-lg font-semibold">{t(titleKey)}</Dialog.Title>
          <Dialog.Description className="mt-2 text-muted">{t(bodyKey)}</Dialog.Description>
          <p className="mt-4 flex flex-col rounded-md bg-background px-3 py-2.5">
            <strong className="font-semibold wrap-anywhere">{subject}</strong>
            <span className="font-mono text-sm text-muted wrap-anywhere">{detail}</span>
          </p>
          {error !== null && (
            <p role="alert" className="mt-3 text-sm text-danger-text">
              {error}
            </p>
          )}
          <div className="mt-6 flex flex-wrap justify-end gap-2">
            <Dialog.Close asChild>
              <button type="button" className={BTN_SECONDARY}>
                {t("byok.form.cancel")}
              </button>
            </Dialog.Close>
            <BusyButton
              busy={busy}
              onClick={() => void confirm()}
              className={`${BTN} bg-danger px-4.5 text-danger-foreground hover:bg-danger-hover`}
            >
              {t(confirmKey)}
            </BusyButton>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
