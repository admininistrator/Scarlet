import { useCallback, useEffect, useId, useState, type FormEvent, type ReactNode } from "react";

import { useSession } from "../../app/Layout";
import { toApiError, useResource } from "../../features/admin/useResource";
import { ApiError, api, type ByokProvider, type ProviderKey } from "../../lib/api";
import { t, type TextKey } from "../../lib/i18n";
import { formatDateTime } from "../admin/format";
import { useTheme, type Theme } from "../ui/ThemeToggle";

/**
 * Trang Cai dat ca nhan — §18.4, T-3.12.
 *
 * KH tham chieu: §18.4, §10.5, §20, UC-05 · tasks.md T-0.10 (theme), T-2.14
 * (BYOK), T-3.0 (`PUT /settings`, NQ-79), T-3.12 · B-216 (de mo, nguoi dung
 * chot 2026-09-23).
 *
 * Ba manh, ca ba da co backend — trang nay chi dung man hinh:
 *
 *   - **Giao dien** — `localStorage` (T-0.10), cung `useTheme()` voi nut o
 *     header: doi o day thi nut kia doi theo.
 *   - **Model mac dinh** — `PUT /settings` qua `useSessionState.changeDefaultModel`,
 *     tuc `GET /auth/me` noi cung mot cau sau F5 (UC-05 dong 4).
 *   - **Khoa rieng (BYOK)** — `/settings/keys*` (§10.5, T-2.14).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BAN RO CUA KHOA DI MOT CHIEU, MOT LAN (§20, T-2.14)                   ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * O nhap la `type="password"`, `autoComplete="off"`, va bi XOA ngay sau khi
 * gui — thanh cong hay that bai. Thu duy nhat hien lai la `masked_key` server
 * tra (`sk-...4f2a`). Khong co nut "hien khoa", khong co ban sao trong state
 * nao song lau hon mot lan gui.
 *
 * ── Ai vao duoc (B-216) ────────────────────────────────────────────────────
 *
 * Moi tai khoan DA DANG NHAP (`SignedInOnly`), khong boc `StatusGate`: backend
 * mo `/settings` cho cot "Xem UI" cua §11.1. B-216 (nguoi `pending_approval`
 * co BYOK van bi day ve `/cho-duyet` o man chat) van mo — nguoi dung chot de
 * mo, khong xu ly o task nay.
 */

function Section({ title, children }: { title: string; children: ReactNode }) {
  const headingId = useId();
  return (
    <section
      aria-labelledby={headingId}
      className="flex min-w-0 flex-col gap-4 rounded-lg border border-border bg-surface-panel p-4 sm:p-5"
    >
      <h3 id={headingId} className="text-xl font-semibold text-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

export function SettingsScreen() {
  return (
    <main className="mx-auto flex w-full max-w-measure min-w-0 flex-col gap-6 px-gutter py-6 lg:px-gutter-lg">
      <h2 className="text-2xl font-semibold text-foreground">{t("settings.title")}</h2>
      <ThemeSection />
      <DefaultModelSection />
      <ByokSection />
    </main>
  );
}

const THEMES: readonly Theme[] = ["light", "dark"];
const THEME_LABEL: Record<Theme, TextKey> = { light: "theme.light", dark: "theme.dark" };

function ThemeSection() {
  const [theme, setTheme] = useTheme();
  return (
    <Section title={t("settings.theme.title")}>
      <div
        role="radiogroup"
        aria-label={t("settings.theme.title")}
        className="flex self-start rounded-md border border-border-strong p-0.5"
      >
        {THEMES.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={theme === option}
            onClick={() => setTheme(option)}
            className={
              theme === option
                ? "motion-press min-h-touch rounded-sm bg-foreground px-4 text-sm font-semibold text-background"
                : "motion-press min-h-touch rounded-sm px-4 text-sm text-foreground hover:bg-surface-hover"
            }
          >
            {t(THEME_LABEL[option])}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted">{t("settings.theme.hint")}</p>
    </Section>
  );
}

function DefaultModelSection() {
  const session = useSession();
  const models = useResource(api.listModels);
  const current = session.profile?.default_model ?? null;
  const [value, setValue] = useState<string>(current ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const selectId = useId();

  // `hoSo` ve SAU lan render dau (Layout hoi `/auth/me` luc mount).
  useEffect(() => {
    setValue(current ?? "");
  }, [current]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      await session.changeDefaultModel(value === "" ? null : value);
      setMessage({ ok: true, text: t("settings.model.saved") });
    } catch (err) {
      const error = toApiError(err);
      setMessage({
        ok: false,
        text:
          error.code === "MODEL_UNKNOWN"
            ? t("settings.model.unknown")
            : `${t("settings.error")}: ${error.code}`,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section title={t("settings.model.title")}>
      <form onSubmit={(e) => void save(e)} className="flex flex-col gap-3">
        <label htmlFor={selectId} className="text-sm font-medium text-foreground">
          {t("settings.model.label")}
        </label>
        <div className="flex flex-wrap gap-2">
          <select
            id={selectId}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setMessage(null);
            }}
            className="motion-control min-h-touch min-w-0 flex-1 rounded-md border border-border-strong bg-background px-3 text-base text-foreground"
          >
            <option value="">{t("settings.model.catalogDefault")}</option>
            {(models.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name} — {m.provider}
                {m.available ? "" : ` (${t("settings.model.unavailable")})`}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={saving || value === (current ?? "")}
            className="motion-press min-h-touch rounded-md bg-accent px-4 text-base font-semibold text-accent-foreground hover:bg-accent-hover disabled:opacity-50"
          >
            {saving ? t("admin.saving") : t("admin.save")}
          </button>
        </div>
        <p role="status" className={message?.ok === false ? "min-h-5 text-sm text-danger-text" : "min-h-5 text-sm text-success-text"}>
          {message?.text}
        </p>
      </form>
    </Section>
  );
}

function keyErrorText(error: ApiError): string {
  switch (error.code) {
    case "PROVIDER_KEY_REJECTED":
      return t("settings.byok.rejected");
    case "SERVICE_UNAVAILABLE":
      return t("settings.byok.unavailable");
    default:
      return `${t("settings.error")}: ${error.code}`;
  }
}

function ByokSection() {
  const loadKeys = useCallback(() => api.listProviderKeys(), []);
  const keys = useResource(loadKeys);
  const providers: ByokProvider[] = keys.data?.byok_providers ?? [];
  const [provider, setProvider] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const providerId = useId();
  const secretId = useId();

  useEffect(() => {
    if (provider === "" && providers.length > 0) {
      setProvider(providers[0].provider);
    }
  }, [provider, providers]);

  const labelOf = (key: string) => providers.find((p) => p.provider === key)?.label ?? key;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const plaintext = secret;
    // Xoa o nhap TRUOC khi cho server — ban ro khong song qua lan gui nay.
    setSecret("");
    setBusy(true);
    setMessage(null);
    try {
      await api.putProviderKey(provider, plaintext);
      setMessage({ ok: true, text: t("settings.byok.saved") });
      await keys.reload();
    } catch (err) {
      setMessage({ ok: false, text: keyErrorText(toApiError(err)) });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (key: ProviderKey) => {
    setBusy(true);
    setMessage(null);
    try {
      await api.deleteProviderKey(key.provider);
      setMessage({ ok: true, text: t("settings.byok.deleted") });
    } catch (err) {
      setMessage({ ok: false, text: keyErrorText(toApiError(err)) });
    } finally {
      await keys.reload();
      setBusy(false);
    }
  };

  return (
    <Section title={t("settings.byok.title")}>
      <p className="text-sm text-muted">{t("settings.byok.intro")}</p>

      {keys.error && (
        <p role="alert" className="text-sm text-danger-text">
          {`${t("settings.error")}: ${keys.error.code}`}
        </p>
      )}

      {keys.data !== null &&
        (keys.data.keys.length === 0 ? (
          <p className="text-sm text-muted">{t("settings.byok.none")}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
            {keys.data.keys.map((k) => (
              <li key={k.provider} className="flex min-w-0 flex-wrap items-center gap-3 px-3 py-2">
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="text-base font-semibold text-foreground">{labelOf(k.provider)}</span>
                  <span className="font-mono text-sm text-foreground" data-testid="masked-key">
                    {k.masked_key}
                  </span>
                  <span className="text-xs text-muted">
                    {!k.usable
                      ? t("settings.byok.unusable")
                      : k.verified_at !== null
                        ? `${t("settings.byok.verifiedAt")} ${formatDateTime(k.verified_at)}`
                        : t("settings.byok.unverified")}
                  </span>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void remove(k)}
                  aria-label={`${t("settings.byok.delete")} — ${labelOf(k.provider)}`}
                  className="motion-press min-h-touch rounded-md border border-border-strong px-3 text-base font-medium text-danger-text hover:bg-surface-hover disabled:opacity-50"
                >
                  {t("settings.byok.delete")}
                </button>
              </li>
            ))}
          </ul>
        ))}

      {keys.data !== null && providers.length === 0 ? (
        <p className="text-sm text-muted">{t("settings.byok.noProviders")}</p>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-3" autoComplete="off">
          <div className="flex flex-col gap-1.5">
            <label htmlFor={providerId} className="text-sm font-medium text-foreground">
              {t("settings.byok.provider")}
            </label>
            <select
              id={providerId}
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="motion-control min-h-touch rounded-md border border-border-strong bg-background px-3 text-base text-foreground"
            >
              {providers.map((p) => (
                <option key={p.provider} value={p.provider}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={secretId} className="text-sm font-medium text-foreground">
              {t("settings.byok.key")}
            </label>
            <input
              id={secretId}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              className="motion-control min-h-touch rounded-md border border-border-strong bg-background px-3 font-mono text-base text-foreground"
            />
          </div>
          <button
            type="submit"
            disabled={busy || provider === "" || secret.trim() === ""}
            className="motion-press min-h-touch self-start rounded-md bg-accent px-4 text-base font-semibold text-accent-foreground hover:bg-accent-hover disabled:opacity-50"
          >
            {busy ? t("settings.byok.saving") : t("settings.byok.save")}
          </button>
        </form>
      )}

      <p
        role="status"
        className={message?.ok === false ? "min-h-5 text-sm text-danger-text" : "min-h-5 text-sm text-success-text"}
      >
        {message?.text}
      </p>
    </Section>
  );
}
