import { CircleAlert, CodeXml, Download, File, FileText, Link2Off, RotateCcw, type IconNode } from "lucide";
import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import { PATHS } from "../../app/paths";
import {
  ApiError,
  api,
  type PublicArtifact,
  type PublicAttachment,
  type PublicMessage,
  type PublicShare,
} from "../../lib/api";
import { DISPLAY_LOCALE, t } from "../../lib/i18n";
import { Markdown } from "../chat/Markdown";
import { StaticIcon } from "../ui/Icon";

/**
 * Trang chia se cong khai `/s/:token` — T-8.2, ban T-HD12 (`PublicSharePage.tsx`).
 *
 * KH tham chieu: UC-11 dong 2 + 4, §16.1, ADR-14, R15, §20 · NQ-95, NQ-149
 * (Q-P8-5, Q-P8-6).
 *
 * Nguoi xem co the KHONG co tai khoan: route nam ngoai `StatusGate` /
 * `SignedInOnly`, `Layout` van hoi `/auth/me` va `401` o do la im lang.
 *
 * ── Ba dieu khong duoc lam o trang nay ────────────────────────────────────
 *
 *   1. Render `content` ngoai `Markdown` (ba lop sanitize, NQ-95): day la trang
 *      dau tien NGUOI LA chay JS cua Scarlet tren origin chinh — noi cookie
 *      phien cua nguoi xem da dang nhap dang song.
 *   2. Chay artifact (Q-P8-6): chi ma tinh trong `<pre>`, khong `iframe`, khong
 *      origin phu. Render that ⇒ B-414.
 *   3. Giu URL ky lau (B-406 ②): `url` song `PRESIGN_TTL_S`, vao lai trang la
 *      nap lai JSON.
 *
 * Noindex hai lop (Q-P8-5): Nginx gan `X-Robots-Tag` cho `/s/`, trang gan them
 * `<meta name="robots">` khi vao route va go khi roi.
 *
 * Nut "Chat tiep" cua ban ve la viec cua T-8.3.
 */

type ShareState =
  | { status: "loading" }
  | { status: "ready"; share: PublicShare }
  | { status: "notFound" }
  | { status: "error" };

const SHARE_NOT_FOUND = "SHARE_NOT_FOUND";

const dateFormat = new Intl.DateTimeFormat(DISPLAY_LOCALE, { dateStyle: "long" });

const secondaryButton =
  "motion-press inline-flex min-h-touch shrink-0 items-center justify-center gap-2 rounded-md border border-border-strong px-4 text-base font-medium text-foreground hover:bg-surface-hover";
const column = "mx-auto w-full max-w-measure";

/** `<meta name="robots">` trong luc o route; go khi roi (lop thu hai cua noindex). */
function useNoindex() {
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);
}

function usePublicShare(token: string) {
  const [state, setState] = useState<ShareState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    setState({ status: "loading" });
    api.getShare(token).then(
      (share) => alive && setState({ status: "ready", share }),
      (e: unknown) => {
        if (alive) {
          setState(e instanceof ApiError && e.code === SHARE_NOT_FOUND ? { status: "notFound" } : { status: "error" });
        }
      },
    );
    return () => {
      alive = false;
    };
  }, [token, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}

export function ShareScreen() {
  const { token = "" } = useParams();
  const { state, retry } = usePublicShare(token);
  useNoindex();

  useEffect(() => {
    const before = document.title;
    const brand = t("publicShare.brand");
    document.title = state.status === "ready" ? `${state.share.title ?? t("sidebar.untitled")} – ${brand}` : brand;
    return () => {
      document.title = before;
    };
  }, [state]);

  return (
    <div className="min-h-full bg-background text-foreground">
      <a
        href="#share-main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface-panel focus:px-3 focus:py-2.5 focus:shadow-popover"
      >
        {t("a11y.skipToContent")}
      </a>
      <header className="sticky top-0 z-30 border-b border-border bg-background">
        <div className="flex h-header items-center gap-3 px-gutter sm:px-gutter-lg">
          <Link to={PATHS.home} className="inline-flex min-h-touch items-center rounded-md text-xl font-bold text-foreground">
            {t("publicShare.brand")}
          </Link>
        </div>
      </header>

      <main id="share-main" tabIndex={-1} className="px-gutter pt-8 pb-16 outline-none sm:px-gutter-lg sm:pt-12">
        {state.status === "ready" ? (
          <ShareBody share={state.share} />
        ) : state.status === "loading" ? (
          <LoadingBody />
        ) : state.status === "notFound" ? (
          <StateBody icon={Link2Off} title={t("publicShare.notFoundTitle")} hint={t("publicShare.notFoundHint")}>
            <Link to={PATHS.home} className={secondaryButton}>
              {t("publicShare.goHome")}
            </Link>
          </StateBody>
        ) : (
          <StateBody icon={CircleAlert} title={t("publicShare.errorTitle")} hint={t("publicShare.errorHint")} isAlert>
            <button type="button" onClick={retry} className={secondaryButton}>
              <StaticIcon icon={RotateCcw} size={18} />
              {t("publicShare.retry")}
            </button>
          </StateBody>
        )}
      </main>
    </div>
  );
}

/* ---------------- noi dung ---------------- */

function ShareBody({ share }: { share: PublicShare }) {
  return (
    <div className={`${column} flex flex-col`}>
      <h1 className="m-0 text-2xl font-bold text-pretty">{share.title ?? t("sidebar.untitled")}</h1>
      <p className="mt-2 mb-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
        <span>
          {t("publicShare.sharedOn")} <time dateTime={share.shared_at}>{dateFormat.format(new Date(share.shared_at))}</time>
        </span>
        <span aria-hidden="true">·</span>
        <span>{t("publicShare.readOnly")}</span>
      </p>

      <ol className="m-0 mt-10 flex list-none flex-col gap-turn p-0">
        {share.messages.filter(hasBody).map((m, i) => (
          <li key={`${m.created_at}-${i}`} className="flex flex-col gap-6">
            {m.role === "user" ? <UserTurn message={m} /> : <AssistantTurn message={m} />}
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * B-416 ③: snapshot giu ca message `cancelled` khong chu (builder chi bo
 * `failed` rong) ⇒ bo qua luc ve, khong de mot bong bong rong.
 */
const hasBody = (m: PublicMessage) => m.content.trim() !== "" || m.attachments.length > 0 || m.artifacts.length > 0;

function UserTurn({ message }: { message: PublicMessage }) {
  return (
    <article data-share-message="user" className="flex w-full max-w-bubble-user flex-col gap-3 self-end">
      <h2 className="sr-only">{t("publicShare.roleUser")}</h2>
      {message.attachments.length > 0 ? <Attachments items={message.attachments} /> : null}
      <div className="min-w-0 rounded-bubble bg-surface-user px-4 py-3 text-body break-words text-foreground">
        <Markdown text={message.content} streaming={false} />
      </div>
    </article>
  );
}

function AssistantTurn({ message }: { message: PublicMessage }) {
  return (
    <article data-share-message="assistant" className="flex min-w-0 flex-col gap-3">
      <h2 className="sr-only">{t("publicShare.roleAssistant")}</h2>
      {message.model_display_name ? (
        <span className="inline-flex self-start rounded-full border border-border px-2.5 py-0.5 text-xs text-muted">
          {message.model_display_name}
        </span>
      ) : null}
      <div className="min-w-0 text-body break-words text-foreground">
        <Markdown text={message.content} streaming={false} />
      </div>
      {message.attachments.length > 0 ? <Attachments items={message.attachments} /> : null}
      {message.artifacts.map((a, i) => (
        <ArtifactBlock key={i} artifact={a} />
      ))}
    </article>
  );
}

function Attachments({ items }: { items: PublicAttachment[] }) {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
      {items.map((a, i) =>
        a.kind === "image" ? (
          <li key={a.key} className="max-w-full">
            <img
              src={a.url}
              alt={a.name}
              width={a.width ?? undefined}
              height={a.height ?? undefined}
              loading="lazy"
              className="block h-auto max-h-96 w-auto max-w-full rounded-lg border border-border"
            />
          </li>
        ) : (
          // Tai lieu: CHI ten (Q-P8-4) — khong link, khong tai.
          <li
            key={`${a.name}-${i}`}
            className="inline-flex min-h-touch max-w-full min-w-0 items-center gap-2.5 rounded-lg border border-border bg-surface-panel px-3 py-2"
          >
            <StaticIcon icon={FileText} size={18} className="shrink-0 text-muted" />
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-medium text-foreground">{a.name}</span>
              <span className="text-xs text-muted">{t("publicShare.fileNameOnly")}</span>
            </span>
          </li>
        ),
      )}
    </ul>
  );
}

function ArtifactBlock({ artifact }: { artifact: PublicArtifact }) {
  const codeId = useId();
  if (artifact.kind === "file") {
    return (
      <div className="flex min-w-0 items-center gap-3 rounded-lg border border-border bg-surface-panel py-2 pr-2 pl-3">
        <StaticIcon icon={File} size={18} className="shrink-0 text-muted" />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium text-foreground">{artifact.title}</span>
          <span className="text-xs text-muted">{t("artifact.panel.kind.file")}</span>
        </span>
        <a href={artifact.url} download className={secondaryButton}>
          <StaticIcon icon={Download} size={18} />
          {t("artifact.panel.download")}
        </a>
      </div>
    );
  }
  return (
    <figure className="m-0 flex min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-surface-code">
      <figcaption className="flex min-h-touch flex-wrap items-center gap-x-3 gap-y-0.5 border-b border-border px-3 py-2">
        <StaticIcon icon={CodeXml} size={16} className="shrink-0 text-muted" />
        <span id={codeId} className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
          {artifact.title || t(`artifact.panel.kind.${artifact.kind}` as const)}
        </span>
        <span className="text-xs text-muted">{t("publicShare.codeOnly")}</span>
      </figcaption>
      {/* Cuon TRONG khoi ⇒ trang khong cuon ngang o 375; tabIndex de cuon bang phim. */}
      <pre
        tabIndex={0}
        role="region"
        aria-labelledby={codeId}
        className="m-0 max-h-share-code overflow-auto p-4 font-mono text-sm leading-relaxed text-foreground"
      >
        <code>{artifact.content}</code>
      </pre>
    </figure>
  );
}

/* ---------------- trang thai ---------------- */

function LoadingBody() {
  return (
    <div className={`${column} flex flex-col`}>
      <p role="status" className="sr-only">
        {t("publicShare.loading")}
      </p>
      <div aria-hidden="true" className="motion-pulse flex flex-col">
        <div className="h-8 w-3/5 rounded-md bg-surface-code" />
        <div className="mt-3 h-4 w-2/5 rounded-md bg-surface-code" />
        <div className="mt-10 h-16 w-full max-w-bubble-user self-end rounded-bubble bg-surface-code" />
        <div className="mt-6 flex flex-col gap-2.5">
          <div className="h-4 w-full rounded-md bg-surface-code" />
          <div className="h-4 w-11/12 rounded-md bg-surface-code" />
          <div className="h-4 w-4/5 rounded-md bg-surface-code" />
          <div className="h-4 w-1/2 rounded-md bg-surface-code" />
        </div>
      </div>
    </div>
  );
}

function StateBody({
  icon,
  title,
  hint,
  isAlert,
  children,
}: {
  icon: IconNode;
  title: string;
  hint: string;
  isAlert?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      role={isAlert ? "alert" : undefined}
      className="motion-enter mx-auto flex w-full max-w-dialog flex-col items-center gap-3 pt-12 text-center"
    >
      <span className="grid size-12 place-items-center rounded-full bg-surface-hover text-muted">
        <StaticIcon icon={icon} size={24} />
      </span>
      <h1 className="m-0 text-xl font-semibold text-pretty">{title}</h1>
      <p className="m-0 text-base leading-relaxed text-muted text-pretty">{hint}</p>
      <div className="mt-3">{children}</div>
    </div>
  );
}
