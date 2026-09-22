import "./prismManual";
import Prism from "prismjs";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-python";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-typescript";

/**
 * To mau cu phap — T-3.5, theo o "To mau cu phap — de xuat" cua ban T-HD3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  HAI RANG BUOC, CA HAI DEU DEN TU MOT PHEP DO                          ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * T-1.14 do duoc **309 delta trong 3,768 s** cho mot cau dai. Ca ba thu vien
 * to mau (Prism, highlight.js, Shiki) deu nhan vao MOT chuoi va tra ve ca
 * khoi — khong cai nao co API "to them phan moi". Nen:
 *
 *   1. **Khong to mau khoi dang mo.** Khoi code chua co hang ``` dong thi hien
 *      don sac; to mot lan duy nhat khi hang dong ve. `CodeBlock` quyet dinh
 *      viec nay bang co `open`, khong phai file nay.
 *   2. **Ket qua phai la du lieu thuan, de `useMemo` giu lai duoc.** Vi vay
 *      ham nay tra ve mot MANG, khong phai HTML va khong phai JSX: mot khoi
 *      da dong nam tren mot message dang chay se duoc to dung mot lan roi
 *      dung lai o cache cua `useMemo` suot 300 delta con lai.
 *
 * Va mot rang buoc cua §20: `Prism.highlight()` tra ve CHUOI HTML, dung no la
 * bat buoc phai co `dangerouslySetInnerHTML`. `Prism.tokenize()` tra ve cay
 * token, tu do dung thang ra phan tu React — day la ly do file nay dung ham
 * thu hai chu khong phai ham thu nhat.
 *
 * Gia da do (de xuat T-HD3): loi ~2 KB gzip + 5 ngon ngu ~1–3 KB moi thu.
 */

/** Sau lop mau, dung sau lop dinh nghia trong `theme.css`. */
const CLASS_BY_TOKEN: Readonly<Record<string, string>> = {
  // tim
  keyword: "tk-keyword",
  boolean: "tk-keyword",
  atrule: "tk-keyword",
  important: "tk-keyword",
  tag: "tk-keyword",
  selector: "tk-keyword",
  "class-name": "tk-keyword",
  // luc
  string: "tk-string",
  char: "tk-string",
  "attr-value": "tk-string",
  "template-string": "tk-string",
  regex: "tk-string",
  url: "tk-string",
  // ho phach
  number: "tk-number",
  constant: "tk-number",
  symbol: "tk-number",
  unit: "tk-number",
  // lam
  function: "tk-function",
  builtin: "tk-function",
  "attr-name": "tk-function",
  property: "tk-function",
  variable: "tk-function",
  parameter: "tk-function",
  // chu thich
  comment: "tk-comment",
  prolog: "tk-comment",
  cdata: "tk-comment",
  shebang: "tk-comment",
  doctype: "tk-comment",
  // dau cau
  punctuation: "tk-punct",
  operator: "tk-punct",
};

/**
 * Ten ngon ngu nguoi ta that su go sau hang ``` → khoa cua `Prism.languages`.
 *
 * Nam ngon ngu duoc nap tuong minh o dau file, cong `markup`/`css`/`clike`/
 * `javascript` ma ban `prismjs` mac dinh da co san. Ngon ngu khong co trong
 * bang nay khong phai loi: khoi code hien don sac, van du nhan va so dong.
 */
const LANGUAGE_ALIAS: Readonly<Record<string, string>> = {
  ts: "typescript",
  typescript: "typescript",
  tsx: "typescript",
  js: "javascript",
  javascript: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  json: "json",
  jsonc: "json",
  py: "python",
  python: "python",
  sh: "bash",
  shell: "bash",
  bash: "bash",
  zsh: "bash",
  console: "bash",
  sql: "sql",
  postgres: "sql",
  psql: "sql",
  html: "markup",
  xml: "markup",
  svg: "markup",
  css: "css",
};

/** Mot doan chu lien tuc mang cung mot lop mau. */
export interface CodePiece {
  readonly text: string;
  /** `null` = khong co lop nao, dung mau chu thuong. */
  readonly cls: string | null;
}

export type CodeLine = readonly CodePiece[];

/** Ngon ngu co duoc to mau khong — `CodeBlock` dung de chon nhan hien thi. */
export function isHighlightable(language: string): boolean {
  return grammarFor(language) !== null;
}

function grammarFor(language: string): Prism.Grammar | null {
  const key = LANGUAGE_ALIAS[language.trim().toLowerCase()];
  if (key === undefined) {
    return null;
  }
  return Prism.languages[key] ?? null;
}

function classOf(token: Prism.Token): string | null {
  const names = [token.type, ...(Array.isArray(token.alias) ? token.alias : token.alias ? [token.alias] : [])];
  for (const name of names) {
    const cls = CLASS_BY_TOKEN[name];
    if (cls !== undefined) {
      return cls;
    }
  }
  return null;
}

function flatten(nodes: Array<string | Prism.Token>, inherited: string | null, out: CodePiece[]): void {
  for (const node of nodes) {
    if (typeof node === "string") {
      if (node !== "") {
        out.push({ text: node, cls: inherited });
      }
      continue;
    }
    const cls = classOf(node) ?? inherited;
    const content = node.content;
    if (typeof content === "string") {
      if (content !== "") {
        out.push({ text: content, cls });
      }
    } else if (Array.isArray(content)) {
      flatten(content, cls, out);
    } else {
      flatten([content], cls, out);
    }
  }
}

/** Cat mot day doan thanh tung DONG — `\n` khong bao gio nam trong mot doan. */
function splitLines(pieces: readonly CodePiece[]): CodeLine[] {
  const lines: CodePiece[][] = [[]];
  for (const piece of pieces) {
    const parts = piece.text.split("\n");
    parts.forEach((part, i) => {
      if (i > 0) {
        lines.push([]);
      }
      if (part !== "") {
        lines[lines.length - 1].push({ text: part, cls: piece.cls });
      }
    });
  }
  return lines;
}

/** Khong to mau: moi dong la mot doan chu tran. */
export function plainLines(code: string): CodeLine[] {
  return code.split("\n").map((line) => (line === "" ? [] : [{ text: line, cls: null }]));
}

/**
 * To mau mot khoi code DA DONG. Ngon ngu la, hoac Prism nem, thi roi ve
 * `plainLines` — mot khoi code khong mau van doc duoc, mot man hinh trang thi
 * khong.
 */
export function highlightLines(code: string, language: string): CodeLine[] {
  const grammar = grammarFor(language);
  if (grammar === null) {
    return plainLines(code);
  }
  try {
    const pieces: CodePiece[] = [];
    flatten(Prism.tokenize(code, grammar), null, pieces);
    return splitLines(pieces);
  } catch {
    return plainLines(code);
  }
}
