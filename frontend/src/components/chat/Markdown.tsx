import { createContext, memo, useContext, useMemo } from "react";
import ReactMarkdown, { type Components, type ExtraProps, type Options } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import type { PathArtifact } from "../../lib/api";
import { t } from "../../lib/i18n";
import { ArtifactCard } from "./BubbleExtras";
import { CodeBlock } from "./CodeBlock";
import { SANITIZE_SCHEMA, safeUrl } from "./markdownPolicy";
import { splitStreamingTail } from "./streamingTail";

/**
 * Renderer markdown cua bong bong assistant — T-3.5.
 *
 * KH tham chieu: §20 (dong XSS), §7.4 · ban T-HD3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  DAY LA CHO DUY NHAT CHU CUA MODEL TRO THANH DOM                       ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Chinh sach nam o `markdownPolicy.ts`, khong o day, va no co ba lop. Dieu
 * quan trong ve file nay: **khong co mot `dangerouslySetInnerHTML` nao**, va
 * khong co duong nao de co mot cai — `react-markdown` dung cay phan tu React
 * tu hast, `Prism.tokenize()` tra ve cay token chu khong tra ve HTML.
 *
 * `components` thay `<pre>` bang `CodeBlock`: neu de mac dinh, khoi code se
 * la mot `<pre>` tran, khong nhan ngon ngu, khong so dong, khong nut Copy.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  HIEU NANG — 309 delta / 3,768 s (T-1.14)                            │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * `memo` o day khong de tranh phan tich lai chu dang doi — chu doi that nen
 * khong tranh duoc. No de chan nhung lan dung lai KHONG phai vi chu: mot
 * message da xong nam phia tren trong `path` bi dung lai moi khi `inFlight`
 * cua message dang chay doi.
 *
 * Con tro nhap nhay la `::after` cua phan tu CUOI (tien ich `caret-tail`),
 * khong phai mot phan tu React: no phai nam TRONG dong chu cuoi, ma dong chu
 * cuoi la mot `<p>` do `react-markdown` dung — khong co cho nao chen mot
 * `<span>` vao do ma khong tu di do cay hast. Hoat anh chay tren pseudo-
 * element, khong tren phan tu dang doi noi dung, nen no khong khoi dong lai
 * moi delta — dung tinh than quy tac 1 cua ban T-HD3.
 */

const COMPONENTS: Components = {
  /*
    `pre` chu khong `code`: bat o `pre` thi lay duoc ca khoi mot lan, va thanh
    phan `code` ben trong khong bao gio duoc dung nen no chi con phuc vu code
    NOI DONG — khong con phai doan "inline hay khong" nhu ban react-markdown
    cu bat lam.
  */
  pre(props) {
    const child = props.node === undefined ? null : preCode(props.node);
    if (child !== null) {
      const className = child.properties?.className;
      const names = Array.isArray(className) ? className.map(String) : [];
      const language = names.map((n) => /^language-([\w+#-]+)$/.exec(n)?.[1]).find((n) => n !== undefined) ?? "";
      return <CodeBlock language={language} code={codeText(child)} open={false} />;
    }
    return <pre className="my-3 overflow-x-auto rounded-md bg-surface-code p-3 text-sm">{props.children}</pre>;
  },

  code: (props) => (
    <code className="rounded-sm bg-surface-code px-1.5 py-px font-mono text-sm">{props.children}</code>
  ),

  a: (props) => (
    /*
      `target="_blank"` + `rel` day du: mot lien ket do model sinh ra thi
      khong co ly do gi de no cuop mat tab dang co hoi thoai, va `noopener`
      cat duong `window.opener`.
    */
    <a href={props.href} title={props.title} target="_blank" rel="noopener noreferrer nofollow">
      {props.children}
    </a>
  ),

  /*
    T-S.19a (ban Tin nhan v3, `ChatStream.tsx` `markdownComponents`): khong
    bong bong nen moi khoi nam thang tren nen luong. Tieu de: h2 17/24, h3
    15/26 — `#` va `##` cung co h2 (ban ve: khong h1 trong tin nhan), the HTML
    van lui mot bac vi nhan "Scarlet tra loi" la `<h3>`.
  */
  p: (props) => <p className="my-3 text-body first:mt-0 last:mb-0">{props.children}</p>,
  h1: (props) => <h2 className="mt-6 mb-2 text-lg font-semibold first:mt-0">{props.children}</h2>,
  h2: (props) => <h3 className="mt-6 mb-2 text-lg font-semibold first:mt-0">{props.children}</h3>,
  h3: (props) => <h4 className="mt-5 mb-1.5 text-body font-semibold first:mt-0">{props.children}</h4>,
  h4: (props) => <h5 className="mt-5 mb-1.5 text-body font-semibold first:mt-0">{props.children}</h5>,
  h5: (props) => <h6 className="mt-5 mb-1.5 text-body font-semibold first:mt-0">{props.children}</h6>,
  h6: (props) => <h6 className="mt-5 mb-1.5 text-body font-semibold first:mt-0">{props.children}</h6>,
  ul: (props) => <ul className="my-3 list-disc pl-5 text-body marker:text-muted">{props.children}</ul>,
  ol: (props) => <ol className="my-3 list-decimal pl-5 text-body marker:text-muted">{props.children}</ol>,
  li: (props) => <li className="my-1 pl-1">{props.children}</li>,
  blockquote: (props) => (
    <blockquote className="my-3 border-l-3 border-border-strong pl-4 text-muted">{props.children}</blockquote>
  ),
  hr: () => <hr className="my-6 border-0 border-t border-divider" />,
  /*
    Bang cuon ngang TRONG khoi cua no. Khong co `overflow-x` o day thi mot
    bang 8 cot lam CA TRANG cuon ngang o 375 px. v3: bang la khoi DUY NHAT co
    nen rieng (`scroll-frame` = nen panel + bong mep phai), vi cot can mep.
  */
  // B-255 (T-8.2): vung cuon nhan tieu diem + co ten — loi `TableScroll`.
  table: (props) => (
    <div
      tabIndex={0}
      role="region"
      aria-label={t("markdown.tableRegion")}
      className="scroll-frame my-3 rounded-lg border border-border"
    >
      <table className="w-full border-collapse text-base">{props.children}</table>
    </div>
  ),
  th: (props) => (
    <th className="border-b border-border px-3 py-2 text-left text-sm font-semibold whitespace-nowrap">
      {props.children}
    </th>
  ),
  td: (props) => <td className="border-t border-divider px-3 py-2 align-top">{props.children}</td>,

  // Cho dat the artifact (`rehypeArtifacts`). Markdown khong tu sinh `div` (khong `rehype-raw`).
  div: (props) => {
    const id = props.node?.properties?.[SLOT];
    return typeof id === "string" ? <ArtifactSlot id={id} /> : <div>{props.children}</div>;
  },
};

// ───────────────────── khoi da thanh artifact ⇒ the (T-5.3, Q-P5-7) ─────────────────────

/** Kieu hast qua `react-markdown` — goi `hast` khong phai phu thuoc truc tiep. */
type Element = NonNullable<ExtraProps["node"]>;
type Root = { children: Element["children"] };
type Plugins = NonNullable<Options["rehypePlugins"]>;

/** `code` con cua mot `pre`, hoac `null`. */
function preCode(pre: Element): Element | null {
  const child = pre.children[0];
  return child !== undefined && child.type === "element" && child.tagName === "code" ? child : null;
}

/** Than khoi = `code.value` cua mdast: to-hast them DUNG mot `\n` cuoi, bo no di. */
function codeText(code: Element): string {
  return code.children
    .map((n) => (n.type === "text" ? n.value : ""))
    .join("")
    .replace(/\n$/, "");
}

/** Thuoc tinh hast cua cho dat the: `div[data-artifact=<id>]`. */
const SLOT = "dataArtifact";

const slot = (id: string): Element => ({ type: "element", tagName: "div", properties: { [SLOT]: id }, children: [] });

/**
 * Plugin rehype, chay SAU `rehypeSanitize` tren CUNG cay hast ma `pre` ben tren
 * ve — mot phan tich, nen "khoi nao da thanh the" va "the nao con thua" khong
 * the lech nhau.
 *
 * - `pre > code` co than trung TUNG BYTE voi `content` cua mot artifact cua
 *   chinh message nay ⇒ cho dat the. Backend la nguon duy nhat quyet khoi nao
 *   la artifact (luat ③ cua phase): FE khong dem dong, khong doc ngon ngu.
 * - Moi artifact dat mot lan, theo thu tu: hai khoi giong het ⇒ hai the.
 * - Artifact khong khop khoi nao ⇒ the o CUOI, duoi chu (B-363: markdown long
 *   sai ma ham tach Python va mdast hieu khac; ban nguoi dung sua o T-5.2b;
 *   the vua toi qua event, `content` chua ve). Mat the la mat artifact.
 */
function rehypeArtifacts(artifacts: readonly PathArtifact[]) {
  return (tree: Root) => {
    const placed = new Set<string>();
    const walk = (parent: Root | Element): void => {
      parent.children.forEach((node, index) => {
        if (node.type !== "element") {
          return;
        }
        const code = node.tagName === "pre" ? preCode(node) : null;
        if (code === null) {
          walk(node);
          return;
        }
        const value = codeText(code);
        const match = artifacts.find((a) => !placed.has(a.id) && a.content === value);
        if (match !== undefined) {
          placed.add(match.id);
          parent.children[index] = slot(match.id);
        }
      });
    };
    walk(tree);
    for (const artifact of artifacts) {
      if (!placed.has(artifact.id)) {
        tree.children.push(slot(artifact.id));
      }
    }
  };
}

const ArtifactSlots = createContext<{
  artifacts: readonly PathArtifact[];
  onOpen: (artifact: PathArtifact) => void;
} | null>(null);

function ArtifactSlot({ id }: { id: string }) {
  const slots = useContext(ArtifactSlots);
  const artifact = slots?.artifacts.find((a) => a.id === id);
  if (slots === null || artifact === undefined) {
    return null;
  }
  return <ArtifactCard artifact={artifact} onOpen={() => slots.onOpen(artifact)} />;
}

const REHYPE_PLUGINS: Plugins = [[rehypeSanitize, SANITIZE_SCHEMA]];
const NO_ARTIFACTS: readonly PathArtifact[] = [];
const NO_OPEN = () => {};

/** Khoi chu tho cho phan markdown chua dong — ban T-HD3 hinh 2d. */
function PartialBlock({ text }: { text: string }) {
  return (
    <div className="my-3 rounded-md border border-border bg-background p-3 font-mono text-sm break-words whitespace-pre-wrap text-muted">
      {text}
      <span aria-hidden="true" className="caret-stream ml-0.5" />
    </div>
  );
}

export const Markdown = memo(function Markdown({
  text,
  streaming,
  artifacts = NO_ARTIFACTS,
  onOpenArtifact = NO_OPEN,
}: {
  text: string;
  /** Chu con dang chay — bat phan tach "dang do" va con tro nhap nhay. */
  streaming: boolean;
  /**
   * T-5.3 — artifact cua CHINH message nay (duong di + event). Phai on dinh giua
   * cac lan render: mang moi la phan tich lai ca message (`memo`).
   */
  artifacts?: readonly PathArtifact[];
  onOpenArtifact?: (artifact: PathArtifact) => void;
}) {
  const { body, tail } = useMemo(() => splitStreamingTail(text, streaming), [text, streaming]);
  const rehypePlugins = useMemo(
    (): Plugins => (artifacts.length === 0 ? REHYPE_PLUGINS : [...REHYPE_PLUGINS, [rehypeArtifacts, artifacts]]),
    [artifacts],
  );
  const slots = useMemo(() => ({ artifacts, onOpen: onOpenArtifact }), [artifacts, onOpenArtifact]);

  return (
    <div className={streaming && tail === null ? "caret-tail" : undefined}>
      {body !== "" && (
        <ArtifactSlots value={slots}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={rehypePlugins}
            urlTransform={safeUrl}
            components={COMPONENTS}
          >
            {body}
          </ReactMarkdown>
        </ArtifactSlots>
      )}
      {tail?.kind === "code" && <CodeBlock language={tail.language} code={tail.code} open />}
      {tail?.kind === "raw" && <PartialBlock text={tail.text} />}
    </div>
  );
});
