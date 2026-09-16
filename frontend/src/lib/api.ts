/**
 * Lop goi HTTP cua FE — §18 (khung loi), §18.2 (chat), §18.3 (models).
 *
 * KH tham chieu: §18, §18.2, §18.3, §11.4 · CLAUDE.md A3, A8 · NQ-33.
 *
 * File nay la cho DUY NHAT trong FE biet duong dan `/api/v1/...` trong nhu the
 * nao. Component khong duoc noi chuoi URL: mot duong dan viet sai trong JSX
 * chay thanh 404 luc nguoi dung bam nut, khong phai luc build.
 *
 * ── Danh tinh cua Phase 1 ───────────────────────────────────────────────────
 *
 * `get_current_user_id` (backend, `app/core/deps.py`) doc header `X-User-Id`
 * roi cookie `scarlet_dev_user`. FE dung COOKIE, va day la ly do ky thuat chu
 * khong phai so thich: `EventSource` KHONG dat duoc header tuy chon, ma §7.4 +
 * Phu luc F doi dung `EventSource` native de trinh duyet tu gui
 * `Last-Event-ID`. Cookie di duoc ca hai duong — `fetch` same-origin lan
 * `EventSource` — nen o day khong co mot dong nao gan header danh tinh.
 *
 * Xem NQ-33. Ca hai dau deu la CHO TAM, T-2.3 thay ca hai.
 */

// A3: base URL tu bien moi truong Vite, khong literal. Mac dinh "/api/v1" —
// cung origin voi nginx (Phu luc D).
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

/**
 * Ban sao duy nhat cua `app/core/deps.py::DEV_USER_COOKIE`.
 *
 * Hai dau cua mot soi day, cung loai voi `stream:{id}` giua producer va
 * consumer. Doi mot ben ma quen ben kia thi FE im lang truot ve `401`, nen ca
 * hai cho deu tro ve nhau bang chu thich.
 */
export const TEN_COOKIE_DEV = "scarlet_dev_user";

/** Doc `user_id` tam dang dung, hoac `null`. */
export function docDanhTinhDev(): string | null {
  const mau = new RegExp(`(?:^|; )${TEN_COOKIE_DEV}=([^;]*)`);
  const khop = mau.exec(document.cookie);
  return khop ? decodeURIComponent(khop[1]) : null;
}

/**
 * Dat cookie danh tinh tam.
 *
 * `Secure` chi them khi trang dang o https: ca stack di qua Nginx TLS (R2),
 * nhung neu ai do mo thang `http://localhost:5173` cua Vite thi mot cookie
 * `Secure` se bi trinh duyet vut di **khong bao loi** — va trieu chung se doc
 * thanh "API luon 401".
 */
export function datDanhTinhDev(userId: string): void {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${TEN_COOKIE_DEV}=${encodeURIComponent(userId)}; path=/; SameSite=Lax${secure}`;
}

/** Khung loi duy nhat cua §18: `{ "error": { code, message, details } }`. */
interface KhungLoi {
  error: { code: string; message: string; details?: unknown };
}

/**
 * Loi HTTP mang theo `code` cua §18.
 *
 * `code` chu khong phai `message` la thu FE duoc phep phan nhanh: mot cau
 * tieng Viet thi khong so sanh duoc, va do la toan bo ly do `core/errors.py`
 * ra doi (B-86). `status` van giu vi co nhung ca FE chi can biet ma HTTP
 * (vi du 409 cua retry khi luot sinh con dang chay).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Ma loi FE co phan nhanh theo. Chuoi khop `ApiErrorCode` cua backend. */
export const MA_LOI = {
  CHUA_XAC_THUC: "UNAUTHENTICATED",
  AUTH_CHUA_CO: "AUTH_NOT_IMPLEMENTED",
  DANG_SINH: "GENERATION_IN_PROGRESS",
} as const;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    // Cookie danh tinh phai di kem. Same-origin la mac dinh cua fetch, nhung
    // viet ro de mot lan doi `VITE_API_BASE_URL` sang host khac khong lam
    // danh tinh bien mat trong im lang.
    credentials: "same-origin",
    headers:
      init?.body === undefined
        ? init?.headers
        : { "Content-Type": "application/json", ...init?.headers },
  });

  if (!res.ok) {
    throw await docLoi(res);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

/**
 * Doc khung loi §18 tu response.
 *
 * Co duong lui vi khong phai moi loi deu di qua `core/errors.py`: Nginx tra
 * `502`/`504` bang HTML cua chinh no, va mot `res.json()` that bai o do se
 * nem `SyntaxError` — tuc loi that bi thay bang mot loi khac han.
 */
async function docLoi(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as Partial<KhungLoi>;
    if (body.error?.code) {
      return new ApiError(res.status, body.error.code, body.error.message, body.error.details);
    }
  } catch {
    // khong phai JSON — roi xuong duong lui
  }
  return new ApiError(res.status, "HTTP_ERROR", `HTTP ${res.status} ${res.statusText}`);
}

// ─────────────────────────── kieu tra ve cua §18.2 ───────────────────────────

export type VaiTro = "system" | "user" | "assistant" | "tool";
export type TrangThaiMessage = "queued" | "streaming" | "completed" | "failed" | "cancelled";

/** Mot node tren duong di hien tai — `MessageTrenDuongDi` cua backend. */
export interface MessageRa {
  id: string;
  parent_id: string | null;
  role: VaiTro;
  status: TrangThaiMessage;
  content: string;
  reasoning: string | null;
  model_id: string | null;
  finish_reason: string | null;
  error_code: string | null;
  created_at: string;
  /** Dem tu 0 (B-60, NQ-33). `‹ n/m ›` hien `sibling_index + 1`. */
  sibling_index: number;
  sibling_count: number;
}

export interface HoiThoaiRa {
  id: string;
  title: string | null;
  default_model: string | null;
  system_prompt_override: string | null;
  active_leaf_id: string | null;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface HoiThoaiChiTiet extends HoiThoaiRa {
  /** Goc truoc, la sau. Rong khi `active_leaf_id` la NULL. */
  path: MessageRa[];
}

export interface DanhSachHoiThoai {
  items: HoiThoaiRa[];
  next_cursor: string | null;
}

export interface TaoMessageRa {
  user_message_id: string;
  assistant_message_id: string;
  /** Duong dan TUONG DOI, da co san tien to `/api/v1`. Khong noi BASE_URL. */
  stream_url: string;
  /** C14 — `parent_id` client gui khac la hien tai, tuc vua mo mot nhanh. */
  branched: boolean;
}

export interface ThuLaiRa {
  assistant_message_id: string;
  stream_url: string;
  model_id: string;
}

export interface SuaMessageRa {
  /** Message MOI, khong phai id tren duong dan — xem `SuaMessageResponse`. */
  user_message_id: string;
  assistant_message_id: string;
  stream_url: string;
}

export interface AnhEmRa {
  message_id: string;
  parent_id: string | null;
  sibling_index: number;
  sibling_count: number;
  items: MessageRa[];
}

export interface HuyRa {
  message_id: string;
  status: TrangThaiMessage;
  cancel_requested: boolean;
}

export interface ModelRa {
  id: string;
  display_name: string;
  provider: string;
  capabilities: string[];
  context_window: number;
  max_output: number;
  default: boolean;
  badge: string | null;
}

// ────────────────────────────── cac loi goi ──────────────────────────────

export const api = {
  danhSachModel: () => request<ModelRa[]>("/models"),

  danhSachHoiThoai: () => request<DanhSachHoiThoai>("/conversations"),

  taoHoiThoai: (body: { title?: string | null; default_model?: string | null } = {}) =>
    request<HoiThoaiRa>("/conversations", { method: "POST", body: JSON.stringify(body) }),

  docHoiThoai: (id: string) => request<HoiThoaiChiTiet>(`/conversations/${id}`),

  /** §8.2 — chuyen nhanh la mot `PATCH` dat `active_leaf_id`, khong xoa gi. */
  suaHoiThoai: (id: string, thayDoi: { active_leaf_id?: string | null; title?: string | null }) =>
    request<HoiThoaiChiTiet>(`/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(thayDoi),
    }),

  /**
   * §7.2 ① — tra `202` roi thoi. Khong sinh mot chu nao o day (A1).
   *
   * `Idempotency-Key` (A8, §11.4) do NGUOI GOI truyen vao chu khong sinh tai
   * cho: mot lan bam nut hai lan (hoac mot lan bam roi mang rot) phai dung
   * DUNG mot khoa, nen khoa thuoc ve thao tac cua nguoi dung chu khong thuoc
   * ve loi goi HTTP. Sinh o day nghia la moi lan thu lai la mot khoa moi, va
   * middleware cua T-2.8 se vo dung truoc ca khi no ra doi (C22).
   */
  guiTinNhan: (
    conversationId: string,
    body: { content: string; parent_id?: string | null; model_id?: string | null },
    idempotencyKey: string,
  ) =>
    request<TaoMessageRa>(`/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),

  huy: (messageId: string) => request<HuyRa>(`/messages/${messageId}/cancel`, { method: "POST" }),

  thuLai: (messageId: string, body: { model_id?: string | null } = {}) =>
    request<ThuLaiRa>(`/messages/${messageId}/retry`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  suaCauHoi: (messageId: string, content: string) =>
    request<SuaMessageRa>(`/messages/${messageId}`, {
      method: "PATCH",
      body: JSON.stringify({ content }),
    }),

  anhEm: (messageId: string) => request<AnhEmRa>(`/messages/${messageId}/siblings`),
};
