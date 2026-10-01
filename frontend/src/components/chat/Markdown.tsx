import { memo, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

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
    const node = props.node;
    const child = node?.children?.[0];
    if (child !== undefined && child.type === "element" && child.tagName === "code") {
      const className = child.properties?.className;
      const names = Array.isArray(className) ? className.map(String) : [];
      const language = names.map((n) => /^language-([\w+#-]+)$/.exec(n)?.[1]).find((n) => n !== undefined) ?? "";
      const code = child.children
        .map((n) => (n.type === "text" ? n.value : ""))
        .join("")
        .replace(/\n$/, "");
      return <CodeBlock language={language} code={code} open={false} />;
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
  table: (props) => (
    <div className="scroll-frame my-3 rounded-lg border border-border">
      <table className="w-full border-collapse text-base">{props.children}</table>
    </div>
  ),
  th: (props) => (
    <th className="border-b border-border px-3 py-2 text-left text-sm font-semibold whitespace-nowrap">
      {props.children}
    </th>
  ),
  td: (props) => <td className="border-t border-divider px-3 py-2 align-top">{props.children}</td>,
};

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
}: {
  text: string;
  /** Chu con dang chay — bat phan tach "dang do" va con tro nhap nhay. */
  streaming: boolean;
}) {
  const { body, tail } = useMemo(() => splitStreamingTail(text, streaming), [text, streaming]);

  return (
    <div className={streaming && tail === null ? "caret-tail" : undefined}>
      {body !== "" && (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[[rehypeSanitize, SANITIZE_SCHEMA]]}
          urlTransform={safeUrl}
          components={COMPONENTS}
        >
          {body}
        </ReactMarkdown>
      )}
      {tail?.kind === "code" && <CodeBlock language={tail.language} code={tail.code} open />}
      {tail?.kind === "raw" && <PartialBlock text={tail.text} />}
    </div>
  );
});
