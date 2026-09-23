/**
 * Trang thai CAY hoi thoai phia client — §8 (§23 ghi `tree.ts` canh `sse.ts`).
 *
 * KH tham chieu: §8.2, §8.3, C11, C13, C14 · CLAUDE.md A2 · B-60/NQ-33, NQ-35.
 *
 * File nay khong biet React va khong goi mang. No la mot cuc du lieu bat bien
 * cong may ham thuan tuy — nho vay dieu huong anh em kiem duoc bang cach goi
 * ham, khong phai bang cach bam nut.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BA LUAT                                                               ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * **1. A2 — cai giu o day la mot DUONG DI, khong phai "moi message".**
 * `path` di tu goc xuong `active_leaf_id`, dung nhu `GET /conversations/{id}`
 * tra ve. Khong co cho nao trong FE giu ca cay: cac nhanh khac song trong
 * Postgres va chi duoc hoi toi khi nguoi dung bam `‹ n/m ›`. Gom ca cay vao
 * bo nho roi tu chon nhanh chinh la C11 o phia client.
 *
 * **2. C13 — FE KHONG BAO GIO tu dem anh em.** `sibling_index`/`sibling_count`
 * do SQL tinh (LATERAL trong `get_path`, §8.3) va di theo tung node. O day
 * khong co mot phep `+1`/`length` nao tren so anh em, tru dung mot cho:
 * `displayIndex()` doi 0-based sang so nguoi doc thay. Mot lan tu dem la mot
 * lan FE va DB noi hai so khac nhau ma khong test nao do.
 *
 * **3. Chu dang bay KHONG nam trong `path`.** Worker chi ghi `content` xuong
 * Postgres luc KET THUC (§7.2 ③), nen giua luot sinh, `path[i].content` la
 * chuoi rong — dung nhu vay, khong phai loi. Phan chu dang chay giu rieng o
 * `inFlight`, khoa theo `message_id`. Nho tach hai cho, mot lan `GET
 * /conversations/{id}` chay ve giua luc stream KHONG xoa mat phan da chay tren
 * man hinh; gop chung lai thi moi lan lam tuoi duong di la mot lan chu nhap
 * nhay roi bien mat.
 */

import type { SiblingsOut, ConversationDetail, MessageOut } from "./api";

/** Phan chu cua MOT message dang chay, chua co trong Postgres. */
export interface StreamingText {
  content: string;
  reasoning: string;
}

export interface TreeState {
  conversationId: string | null;
  activeLeafId: string | null;
  /** Goc truoc, la sau (§8.3 sap theo `depth`, khong theo `created_at`). */
  path: MessageOut[];
  /** Khoa la `message_id`. Xem luat 3. */
  inFlight: Record<string, StreamingText>;
}

const EMPTY_TEXT: StreamingText = { content: "", reasoning: "" };

export function emptyTree(): TreeState {
  return { conversationId: null, activeLeafId: null, path: [], inFlight: {} };
}

/**
 * Thay duong di bang cai vua doc tu server, GIU nguyen phan chu dang bay.
 *
 * Doi hoi thoai thi `inFlight` bi don sach: khoa la `message_id` nen khong the
 * dung nhau, nhung giu lai chu cua mot hoi thoai da roi khoi man hinh la giu
 * mot cai ro chi lon len.
 */
export function loadConversation(tree: TreeState, detail: ConversationDetail): TreeState {
  const conversationChanged = tree.conversationId !== detail.id;
  return {
    conversationId: detail.id,
    activeLeafId: detail.active_leaf_id,
    path: detail.path,
    inFlight: conversationChanged ? {} : tree.inFlight,
  };
}

/**
 * Event `start` — XOA phan chu cu cua message do roi bat dau lai.
 *
 * Duong dung lai tu Postgres (T-1.7) cung phat `start` truoc khi phat lai toan
 * bo noi dung. Khong xoa o day thi mot lan F5 giua luc stream se noi ban phat
 * lai vao duoi ban da co — chu bi lap tu dau toi cho dut, dung trieu chung C3
 * nhung do loi cua client.
 */
export function startGeneration(tree: TreeState, messageId: string): TreeState {
  return { ...tree, inFlight: { ...tree.inFlight, [messageId]: { ...EMPTY_TEXT } } };
}

function appendTo(
  tree: TreeState,
  messageId: string,
  field: keyof StreamingText,
  piece: string,
): TreeState {
  const current = tree.inFlight[messageId] ?? EMPTY_TEXT;
  return {
    ...tree,
    inFlight: { ...tree.inFlight, [messageId]: { ...current, [field]: current[field] + piece } },
  };
}

/** Event `delta` — noi vao cuoi. */
export function appendDelta(tree: TreeState, messageId: string, piece: string): TreeState {
  return appendTo(tree, messageId, "content", piece);
}

/**
 * Event `reasoning` — noi vao mot cho KHAC.
 *
 * §7.4 giao cho FE hai cho hien thi khac nhau, va `reasoning` khong bao gio
 * duoc nhap vao `content`: no khong quay lai ngu canh luot sau (B-33).
 */
export function appendReasoning(tree: TreeState, messageId: string, piece: string): TreeState {
  return appendTo(tree, messageId, "reasoning", piece);
}

/**
 * Chu de hien cho mot node: phan dang bay neu co, khong thi lay tu Postgres.
 *
 * Uu tien phan dang bay vi no luon moi hon hoac bang: giua luot sinh, cot
 * `content` con rong; sau `done` thi hai ban giong nhau.
 */
export function content(tree: TreeState, node: MessageOut): string {
  return tree.inFlight[node.id]?.content || node.content;
}

export function reasoningOf(tree: TreeState, node: MessageOut): string {
  return tree.inFlight[node.id]?.reasoning || node.reasoning || "";
}

export function isLast(tree: TreeState): MessageOut | null {
  return tree.path.length === 0 ? null : tree.path[tree.path.length - 1];
}

/** Trang thai ma luot sinh con chua khep lai — dung chu cua backend. */
const OPEN_STATUSES: ReadonlySet<string> = new Set(["queued", "streaming"]);

/**
 * Message dang can mot ket noi SSE, hoac `null`.
 *
 * Day la toan bo logic "mo lai tab thi phai lam gi": duong di doc tu Postgres
 * noi ro la cuoi con `queued`/`streaming` hay khong, va FE khong phai doan.
 * Do cung la ly do M3 (F5 giua luc stream) chay duoc ma khong can luu gi o
 * `localStorage` — su that nam o server.
 */
export function canStream(tree: TreeState): MessageOut | null {
  const leaf = isLast(tree);
  if (leaf === null || leaf.role !== "assistant" || !OPEN_STATUSES.has(leaf.status)) {
    return null;
  }
  return leaf;
}

export function findNode(tree: TreeState, messageId: string): MessageOut | null {
  return tree.path.find((node) => node.id === messageId) ?? null;
}

// ──────────────────────────── dieu huong anh em ────────────────────────────

/**
 * So hien tren `‹ n/m ›`. **DAY LA CHO DUY NHAT cong 1** (B-60, NQ-33).
 *
 * `sibling_index` dem tu 0 o ca bon cho dung no: `PathNode` (T-1.2), `GET
 * /conversations/{id}` (B-93), `GET /messages/{id}/siblings` (T-1.13) va file
 * nay. Rai phep cong nay trong JSX la mo duong cho mot cho quen, va mot cho
 * quen thi man hinh hien `‹ 1/2 ›` cho ca hai nhanh — khong test nao do.
 */
export function displayIndex(node: MessageOut): number {
  return node.sibling_index + 1;
}

export function hasSiblings(node: MessageOut): boolean {
  return node.sibling_count > 1;
}

export function canGoBack(node: MessageOut): boolean {
  return node.sibling_index > 0;
}

export function canGoForward(node: MessageOut): boolean {
  return node.sibling_index < node.sibling_count - 1;
}

/**
 * Id cua anh em ke ben theo huong `-1`/`+1`, hoac `null` neu da o dau/cuoi.
 *
 * Doc tu `items` CUA SERVER va lay theo `sibling_index` cua chinh no, khong
 * theo vi tri trong mang: hai nguon do trung nhau hom nay, nhung mot ngay nao
 * do `items` bi loc (message xoa mem) thi vi tri mang se lech — va lech mot
 * nhanh thi khong co gi bao.
 *
 * **NQ-35:** id tra ve day duoc dung nguyen cho `PATCH { active_leaf_id }`.
 * Khi nga (a) cua B-109 duoc hien thuc, server tu di tiep xuong la sau nhat
 * cua nhanh nay va ham nay KHONG phai sua mot dong.
 */
export function adjacentSiblingId(siblings: SiblingsOut, direction: -1 | 1): string | null {
  const target = siblings.sibling_index + direction;
  if (target < 0 || target >= siblings.sibling_count) {
    return null;
  }
  return siblings.items.find((node) => node.sibling_index === target)?.id ?? null;
}
