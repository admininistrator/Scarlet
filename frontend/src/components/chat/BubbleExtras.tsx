import { AppWindow, ChartColumn, Check, CircleAlert, FileCode, FileText, Image, LoaderCircle, type IconNode } from "lucide";
import { useState } from "react";

import { t, type TextKey } from "../../lib/i18n";
import { StaticIcon } from "../ui/Icon";
import { formatBytes } from "./Attachments";
import { safeUrl } from "./markdownPolicy";

/**
 * Bon thanh phan cua bong bong — dung o T-S.15 (§7b.2, NQ-121).
 *
 * KH tham chieu: §24.2b·S12, S15 (P4–P7) · ban T-HD3-v2 muc 3e, 3h ·
 * tasks.md T-S.15 (Cam bay ②).
 *
 * | `data-planned` | Thanh phan                               | Ai se gan |
 * |----------------|------------------------------------------|-----------|
 * | —              | Chip "Dang tim web…" + chip nguon        | GAN o T-6.7c |
 * | —              | Chip "Dang chay code…"                   | GAN o T-7.9 |
 * | —              | The artifact                             | GAN o T-5.3 |
 * | —              | Anh / tep trong bong bong nguoi dung     | GAN o T-4.7 |
 *
 * Chip cong cu va nguon GAN o T-6.7c vao `MessageItem`, TREN chu tra loi (ban
 * ve 3e); bieu tuong nguon la o chu cai (Q-P6-7, favicon that — B-381).
 * `ArtifactCard` gan o T-5.3 (`Markdown`: thay khoi da thanh artifact, hoac
 * duoi chu khi khong khop khoi nao — B-363). `UserAttachments` da gan o
 * T-4.7 (tep TREN chu cua nguoi dung).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  DU LIEU THAT KHONG TIN DUOC — LOC NGAY TU BAY GIO (Cam bay ②)         ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Tieu de trang web do trang web dat; ten tep do nguoi dung dat; URL nguon do
 * mot model — da doc noi dung web — dua ra (§20 dong "Prompt injection").
 * Nen:
 *
 * - **Chu** (tieu de, ten tep) di vao JSX nhu CHU — React tu thoat, khong bao
 *   gio `dangerouslySetInnerHTML` — VA qua `plainText()`: bo ky tu dieu khien
 *   va ky tu dao chieu (`U+202E`…). `hoa-don‮fdp.exe` hien la
 *   "hoa-donexe.pdf" neu de nguyen — mot ten tep gia dang.
 * - **Link nguon** qua `sourceHref()`: `safeUrl` cua bien XSS (T-3.5) roi CHI
 *   `http:`/`https:` tuyet doi. `javascript:`/`data:`/tuong doi ⇒ chip van
 *   hien nhung KHONG la link.
 * - **Anh** (favicon, thumbnail) qua `sameOriginSrc()`: chi URL cung origin
 *   voi Scarlet. Ban ve 3e: *"Favicon that la anh 16 px tu may chu Scarlet
 *   (khong goi thang ra ngoai)"* — mot `<img src>` tro ra ngoai la mot lan
 *   trinh duyet tu GET, dung duong ro ri ma T-3.5 da loai `img` khoi markdown
 *   (B-235). URL la ⇒ o chu cai du phong (favicon) / icon anh (thumbnail).
 */

// ─────────────────────────── bo loc dung chung ───────────────────────────

/**
 * Ky tu dieu khien C0/C1 va ky tu dinh dang dao chieu (bidi): LRM/RLM, ALM,
 * LRE…RLO (`U+202A–U+202E`), LRI…PDI (`U+2066–U+2069`).
 */
const UNSAFE_CHARS = /[\u0000-\u001f\u007f-\u009f؜‎‏‪-‮⁦-⁩]/g;

/** Chu tho de hien: bo ky tu nguy hiem, gop khoang trang, cat hai dau. */
export function plainText(raw: string): string {
  return raw.replace(UNSAFE_CHARS, "").replace(/\s+/g, " ").trim();
}

/** URL mo trong tab moi, hoac `null` khi khong phai `http(s)` tuyet doi. */
export function sourceHref(raw: string): string | null {
  const url = safeUrl(raw);
  if (url === "") {
    return null;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    // Khong co giao thuc (duong dan tuong doi) — khong phai mot nguon web.
    return null;
  }
}

/** `src` cua anh neu no nam tren CHINH origin cua Scarlet, khong thi `null`. */
export function sameOriginSrc(raw: string | undefined): string | null {
  if (raw === undefined || safeUrl(raw) === "") {
    return null;
  }
  try {
    const parsed = new URL(raw, window.location.origin);
    return parsed.origin === window.location.origin ? parsed.href : null;
  } catch {
    return null;
  }
}

// ───────────────────── chip trang thai cong cu (T-6.7c, T-7.9) ─────────────────────

export type ToolKind = "webSearch" | "fetchUrl" | "codeRun";
/**
 * Mot chip. `id` = `call_id` (hoac vi tri tren duong di) — hai lan tim web
 * trong mot luot la hai chip. `error` la CAU da dich (`toolErrorText`).
 */
export type ToolStatus = { kind: ToolKind; running: boolean; id?: string; error?: string };

const TOOL_TEXT: Record<ToolKind, { running: TextKey; done: TextKey }> = {
  webSearch: { running: "chat.tool.searchingWeb", done: "chat.tool.searchedWeb" },
  fetchUrl: { running: "chat.tool.readingLink", done: "chat.tool.readLink" },
  codeRun: { running: "chat.tool.runningCode", done: "chat.tool.ranCode" },
};

/**
 * Ten tool cua registry (§13.5) ⇒ loai chip. Ten la ⇒ chip tim web.
 *
 * `load_skill` ⇒ `null`, KHONG chip (B-405 ④, T-7.9): no chi nap huong dan
 * vao context — khong co gi cho nguoi dung xem, va model goi lai no moi luot
 * can skill (C30) ⇒ mot chip "Da doc skill" o gan nhu moi cau tra loi P7 la
 * nhieu. Viec that (chay code, ra tep) da co chip `codeRun` + the tep.
 */
export function toolKind(name: string): ToolKind | null {
  switch (name) {
    case "load_skill":
      return null;
    case "run_code":
      return "codeRun";
    case "fetch_url":
      return "fetchUrl";
    default:
      return "webSearch";
  }
}

/**
 * `reason` (ma co dinh cua `ssrf.py` / `fetcher` / registry / `SearchError`)
 * ⇒ cau cho chip loi (UC-08 dong 3, 5). Ma la ⇒ cau chung. `Object.hasOwn`:
 * ma la du lieu tu stream — "constructor" khong duoc thanh mot ham.
 */
const TOOL_ERROR_TEXT: Readonly<Record<string, TextKey>> = {
  address: "chat.tool.error.internal",
  dns: "chat.tool.error.internal",
  scheme: "chat.tool.error.blocked",
  port: "chat.tool.error.blocked",
  userinfo: "chat.tool.error.blocked",
  host: "chat.tool.error.blocked",
  timeout: "chat.tool.error.timeout",
  web_quota: "chat.tool.error.webQuota",
  not_configured: "chat.tool.error.searchUnavailable",
  unauthorized: "chat.tool.error.searchUnavailable",
  rate_limited: "chat.tool.error.searchUnavailable",
  upstream: "chat.tool.error.searchUnavailable",
  too_large: "chat.tool.error.tooLarge",
  unsupported_type: "chat.tool.error.unsupportedType",
  // `run_code` (registry T-7.7a / T-7.8, `sandbox`). `timeout` dung chung o tren.
  exit_nonzero: "chat.tool.error.codeFailed",
  no_exec_permission: "chat.tool.error.noExec",
  sandbox_unavailable: "chat.tool.error.sandboxUnavailable",
  too_many_files: "chat.tool.error.outputRejected",
  output_too_large: "chat.tool.error.outputRejected",
};

export function toolErrorText(reason: string | null): string {
  if (reason !== null && Object.hasOwn(TOOL_ERROR_TEXT, reason)) {
    return t(TOOL_ERROR_TEXT[reason]);
  }
  return t(reason !== null && /^http_\d{3}$/.test(reason) ? "chat.tool.error.http" : "chat.tool.error.generic");
}

/**
 * Chip "Dang tim web…" / "Dang chay code…" — ban ve 3e. Vong quay la icon
 * `loader-circle` trong MOT span rieng mang `.motion-spin`; chu dung yen. Nam
 * ngoai phan chu dang chay nen 300 lan re-render khong cham toi no. Khong bam
 * duoc.
 *
 * B-314 ③ (chot o T-6.7c): quay → `check` la HAI phan tu, khong bien hinh —
 * theo ma component (`MessageBubble.tsx` `ToolChip`). Chip loi (ban ve khong
 * ve — B-396): `circle-alert` + cau theo `reason`, chu `danger-text`.
 */
export function ToolChips({ tools }: { tools: readonly ToolStatus[] }) {
  if (tools.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {tools.map((tool) => (
        <span
          key={tool.id ?? tool.kind}
          role="status"
          className={`inline-flex min-h-chip max-w-full items-center gap-2 rounded-full border border-border bg-background pr-3 pl-2.5 text-sm ${
            tool.running ? "text-foreground" : tool.error === undefined ? "text-muted" : "text-danger-text"
          }`}
        >
          {tool.running ? (
            <span aria-hidden="true" className="motion-spin grid size-4 place-items-center text-accent-text">
              <StaticIcon icon={LoaderCircle} size={16} />
            </span>
          ) : (
            <StaticIcon icon={tool.error === undefined ? Check : CircleAlert} size={16} className="shrink-0" />
          )}
          <span className="min-w-0">
            {tool.error ?? t(tool.running ? TOOL_TEXT[tool.kind].running : TOOL_TEXT[tool.kind].done)}
          </span>
        </span>
      ))}
    </div>
  );
}

// ─────────────────────────── chip nguon (T-6.7) ───────────────────────────

export type Source = { url: string; title: string; faviconUrl?: string };

/**
 * Hang chip nguon — ban ve 3e. Chip VE cao 32 (`h-chip`), vung bam la the
 * `<a>` cao 44 (`min-h-touch`) bao quanh, nen hang xuong dong khong can khoang
 * cach doc. Rong toi da 192 (`max-w-source-chip`), ten dai cat bang "…"; ten
 * day du o `title` va `aria-label`. Mo tab moi, `rel="noopener noreferrer"`.
 */
export function SourceList({ sources }: { sources: readonly Source[] }) {
  if (sources.length === 0) {
    return null;
  }
  return (
    <ul aria-label={t("chat.sources")} className="mt-0.5 flex flex-wrap gap-x-1.5">
      {sources.map((source, index) => {
        const title = plainText(source.title);
        const href = sourceHref(source.url);
        const chip = (
          <span className="motion-control inline-flex h-chip max-w-source-chip min-w-0 items-center gap-1.5 rounded-full border border-border bg-background pr-2.5 pl-1.5 group-hover:border-border-strong">
            <Favicon src={source.faviconUrl} title={title} href={href} />
            <span className="truncate text-xs group-hover:underline">{title}</span>
          </span>
        );
        return (
          <li key={`${index}:${source.url}`} className="flex max-w-full min-w-0">
            {href === null ? (
              <span title={title} className="inline-flex min-h-touch min-w-0 items-center text-foreground">
                {chip}
              </span>
            ) : (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                title={title}
                aria-label={title}
                className="group inline-flex min-h-touch min-w-0 items-center text-foreground no-underline"
              >
                {chip}
              </a>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Favicon 16 px tu may chu Scarlet; loi hoac URL la ⇒ o chu cai du phong. */
function Favicon({ src, title, href }: { src: string | undefined; title: string; href: string | null }) {
  const [failed, setFailed] = useState(false);
  const safeSrc = sameOriginSrc(src);
  if (safeSrc !== null && !failed) {
    return (
      <img
        src={safeSrc}
        alt=""
        onError={() => setFailed(true)}
        className="size-favicon shrink-0 rounded-sm"
      />
    );
  }
  const letter = (title.charAt(0) || (href === null ? "" : new URL(href).hostname.charAt(0))).toUpperCase();
  return (
    <span
      aria-hidden="true"
      className="grid size-favicon shrink-0 place-items-center rounded-sm bg-surface-code text-[0.625rem] font-bold text-muted"
    >
      {letter}
    </span>
  );
}

// ─────────────────────────── the artifact (T-5.3) ───────────────────────────

export type ArtifactKind = "code" | "document" | "html" | "chart";
/**
 * Phan cua artifact ma the can — tap con cua `PathArtifact` (T-5.2a). `kind` la
 * chu cua DDL (bay gia tri), `version` la SO tu may chu (§14.2) — "v3" khong
 * phai chuoi dich. `language` / `content` vang mat khi the moi chi biet event.
 */
export type ArtifactSummary = {
  kind: string;
  title: string;
  version: number;
  language?: string | null;
  content?: string | null;
};

/**
 * Bay `kind` cua DDL (Phu luc A) ⇒ bon loai cua the — MOT bang (T-5.3 Cam bay ①).
 * `file` (con tro MinIO cua skill, P7) la tai lieu. Chu la ⇒ `code`.
 */
export const CARD_KIND: Readonly<Record<string, ArtifactKind>> = {
  html: "html",
  react: "html",
  svg: "chart",
  mermaid: "chart",
  markdown: "document",
  file: "document",
  code: "code",
};

/** `Object.hasOwn`: `kind` la du lieu cua model — "constructor" khong duoc thanh mot ham. */
export function cardKind(kind: string): ArtifactKind {
  return Object.hasOwn(CARD_KIND, kind) ? CARD_KIND[kind] : "code";
}

/** Tieu de da loc; rong ⇒ nhan suy ra "ngon ngu · N dong" (T-5.3). */
export function artifactLabel(artifact: ArtifactSummary): string {
  const title = plainText(artifact.title);
  if (title !== "") {
    return title;
  }
  const language = plainText(artifact.language ?? "");
  const parts = [language === "" ? t(ARTIFACT_TYPE[cardKind(artifact.kind)]) : language];
  if (artifact.content !== null && artifact.content !== undefined) {
    parts.push(`${artifact.content.split("\n").length} ${t("artifact.lines")}`);
  }
  return parts.join(" · ");
}

const ARTIFACT_ICON: Record<ArtifactKind, IconNode> = {
  code: FileCode,
  document: FileText,
  html: AppWindow,
  chart: ChartColumn,
};

const ARTIFACT_TYPE: Record<ArtifactKind, TextKey> = {
  code: "artifact.type.code",
  document: "artifact.type.document",
  html: "artifact.type.html",
  chart: "artifact.type.chart",
};

/**
 * The artifact trong bong bong — ban ve 3e. Rong toi da 480 (`max-w-artifact`),
 * co theo bong bong o 375 px: tieu de cat "…", nut "Mo" KHONG co. Ca the
 * khong bam duoc — chi nut "Mo" (T-5.3: mo panel phai voi artifact nay).
 */
export function ArtifactCard({ artifact, onOpen }: { artifact: ArtifactSummary; onOpen: () => void }) {
  const kind = cardKind(artifact.kind);
  const label = artifactLabel(artifact);
  return (
    // `data-artifact-card`: Doc to bo the nay (`speakableText`, T-8.4).
    <div
      data-artifact-card
      className="mt-3 flex max-w-artifact items-center gap-3 rounded-lg border border-border bg-background py-2 pr-2 pl-2.5"
    >
      <span
        aria-hidden="true"
        className="grid size-artifact-icon shrink-0 place-items-center rounded-md bg-accent-subtle text-accent-text"
      >
        <StaticIcon icon={ARTIFACT_ICON[kind]} size={20} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-base font-semibold">{label}</span>
          <span className="shrink-0 rounded-sm border border-border-strong px-1.5 font-mono text-2xs text-muted">
            v{artifact.version}
          </span>
        </span>
        <span className="text-xs text-muted">{t(ARTIFACT_TYPE[kind])}</span>
      </span>
      <button
        type="button"
        // Nhieu the tren mot man hinh: ten truy cap mang tieu de, chu hien van la "Mo".
        aria-label={`${t("artifact.open")} ${label}`}
        onClick={onOpen}
        className="motion-press min-h-touch shrink-0 rounded-md border border-border-strong bg-surface-panel px-4 text-base font-medium text-foreground hover:bg-surface-hover"
      >
        {t("artifact.open")}
      </button>
    </div>
  );
}

// ──────────────────── tep dinh kem trong bong bong nguoi dung (gan o T-4.7) ────────────────────

export type SentAttachment = {
  id: string;
  kind: "image" | "file";
  name: string;
  bytes: number;
  /** Anh thu nho do may chu Scarlet phuc vu (P4). Vang mat / la ⇒ icon. */
  thumbnailUrl?: string;
};

/**
 * Anh / tep trong bong bong nguoi dung — ban ve 3e. Anh la thumbnail 96 × 96
 * (`size-thumb`, `object-cover`), `alt` = ten tep. Chip tep dung lai hinh cua
 * khay dinh kem o o nhap (cao 56, toi da 240) nhung KHONG co nut xoa — tep da
 * gui roi. Hom nay chua bam duoc; ngay co xem truoc anh thi thumbnail thanh nut.
 */
export function UserAttachments({ items }: { items: readonly SentAttachment[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <ul aria-label={t("chat.attachments")} className="flex flex-wrap justify-end gap-2">
      {items.map((item) => {
        const name = plainText(item.name);
        if (item.kind === "image") {
          const src = sameOriginSrc(item.thumbnailUrl);
          return (
            <li
              key={item.id}
              className="grid size-thumb shrink-0 place-items-center overflow-hidden rounded-md border border-border bg-surface-code text-muted"
            >
              {src === null ? (
                <StaticIcon icon={Image} size={22} label={name} />
              ) : (
                <img src={src} alt={name} className="size-full object-cover" />
              )}
            </li>
          );
        }
        return (
          <li
            key={item.id}
            className="flex h-attachment max-w-60 min-w-0 items-center gap-2.5 rounded-md border border-border bg-background pr-3.5 pl-2.5"
          >
            <span
              aria-hidden="true"
              className="grid size-8 shrink-0 place-items-center rounded-sm bg-danger-subtle text-danger-text"
            >
              <StaticIcon icon={FileText} size={18} />
            </span>
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-medium">{name}</span>
              <span className="tabular text-xs text-muted">{formatBytes(item.bytes)}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
