/**
 * Lop goi HTTP cua FE — §18 (khung loi), §18.2 (chat), §18.3 (models).
 *
 * KH tham chieu: §18, §18.2, §18.3, §11.4, §11.2 · CLAUDE.md A3, A8 ·
 * NQ-33, NQ-36 · tasks.md T-3.1c, B-128.
 *
 * File nay la cho DUY NHAT trong FE biet duong dan `/api/v1/...` trong nhu the
 * nao. Component khong duoc noi chuoi URL: mot duong dan viet sai trong JSX
 * chay thanh 404 luc nguoi dung bam nut, khong phai luc build.
 *
 * ── Danh tinh: KHONG co mot dong nao trong file nay ─────────────────────────
 *
 * Cookie phien `scarlet_session` mang access JWT (§11.2, NQ-36) co co
 * `HttpOnly`, tuc JS KHONG dat duoc va KHONG doc duoc no — trinh duyet tu gui
 * kem moi request same-origin. Vi vay lop goi HTTP nay khong biet gi ve danh
 * tinh: no chi phai nho `credentials: "same-origin"` o duoi.
 *
 * Toi T-3.1b, ben canh cookie phien con mot cho tam cua Phase 1 ma chinh file
 * nay dat va doc bang `document.cookie` (NQ-24/NQ-33). T-3.1c xoa no cung ca
 * o nhap `user_id` cua man chat — B-128, B-186. Mot trinh duyet nay chi con
 * MOT danh tinh, va
 * cau hoi "toi la ai" chi con mot cau tra loi: `GET /auth/me`.
 *
 * Loi ich ky thuat cua duong cookie van nguyen ven cho `EventSource`: no
 * KHONG dat duoc header tuy chon, ma §7.4 + Phu luc F doi dung `EventSource`
 * native de trinh duyet tu gui `Last-Event-ID`. Cookie di duoc ca hai duong —
 * `fetch` same-origin lan `EventSource`.
 */

// A3: base URL tu bien moi truong Vite, khong literal. Mac dinh "/api/v1" —
// cung origin voi nginx (Phu luc D).
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

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
  DANG_SINH: "GENERATION_IN_PROGRESS",
  SAI_MAT_KHAU: "INVALID_CREDENTIALS",
  TAI_KHOAN_BI_KHOA: "ACCOUNT_DISABLED",
  DOI_QUAN_TRI: "ADMIN_REQUIRED",

  // T-3.1b — sau ma loi cua sau man auth. Tat ca deu la ma ma NGUOI DUNG phai
  // doc duoc mot cau khac nhau, khong phai ma de log: `message` cua backend
  // viet bang tieng Viet khong dau (`mat khau qua pho bien, hay chon mat khau
  // khac`) nen no khong dat len man hinh duoc.
  TURNSTILE_HONG: "TURNSTILE_FAILED",
  MAT_KHAU_QUA_NGAN: "PASSWORD_TOO_SHORT",
  MAT_KHAU_QUA_YEU: "PASSWORD_TOO_WEAK",
  TOKEN_HONG: "TOKEN_INVALID",
  QUA_NHIEU_LAN: "RATE_LIMITED",
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

// ─────────────────── kieu cua §11.2 (auth) va §16.3 (admin) ──────────────────

/** Nam trang thai cua §11.1. */
export type TrangThaiUser =
  | "pending_email"
  | "pending_approval"
  | "active"
  | "rejected"
  | "suspended";

export type VaiTroUser = "user" | "admin";

/** `NguoiDungRa` cua backend — hinh dang chung cua `/login`, `/refresh`, `/me`. */
export interface NguoiDungRa {
  id: string;
  email: string;
  display_name: string | null;
  status: TrangThaiUser;
  role: VaiTroUser;
  tier_name: string;
}

/**
 * Response CO DINH cua ba duong chong do (§11.5): `register`,
 * `resend-verification`, `forgot-password`.
 *
 * FE **khong** duoc doc `message` de re nhanh, va cung khong nen hien no:
 * backend tra mot cau tieng Viet khong dau, va ca diem cua §11.5 la ca hai
 * nhanh (email co that / khong) tra ve **cung mot chuoi**. Man hinh tu viet
 * cau cua no tu `vi.json`.
 */
export interface ThongBaoRa {
  message: string;
}

/**
 * `POST /auth/verify-email` — ba ket cuc, ba man hinh khac nhau.
 *
 * `verified` la lan bam DAU (tai khoan vua sang `pending_approval`);
 * `already_verified` la lan bam thu hai — UC-01 dong 5 doi no di thang toi
 * `/dang-nhap` chu khong phai mot loi. Hai chuoi tach nhau tu T-3.1b, xem
 * docstring `VerifyEmailResponse.status` cua backend.
 */
export interface XacThucEmailRa {
  status: "verified" | "already_verified" | "expired";
}

export interface DatLaiMatKhauRa {
  status: "reset";
}

/** Ba nut cua man "Duyet user" (§16.3) — khop `hanh_dong` cua backend. */
export type HanhDongUser = "approve" | "reject" | "suspend";

/** Mot hang cua bang "Nguoi dung" (§16.3). KHONG co truong nao suy ra mat khau. */
export interface AdminUserRa {
  id: string;
  email: string;
  display_name: string | null;
  status: TrangThaiUser;
  role: VaiTroUser;
  tier_name: string;
  limit_override_json: Record<string, unknown> | null;
  email_verified_at: string | null;
  approved_at: string | null;
  approved_by: string | null;
  last_login_at: string | null;
  created_at: string;
}

export interface AdminUserListRa {
  users: AdminUserRa[];
}

/**
 * `cost_usd` la CHUOI, khong phai `number`.
 *
 * Backend tra `Decimal` va pydantic tuan tu hoa no thanh chuoi — doc thang
 * vao mot `number` la lam tron mot con so tien ngay tai bien vao cua FE. Cho
 * duy nhat duoc phep doi sang so la ham dinh dang, va no doi mot lan de HIEN,
 * khong de cong.
 */
export interface SoTien {
  cost_usd: string;
  prompt_tokens: number;
  completion_tokens: number;
  events: number;
}

/**
 * Hai cot tach rieng cua C16 — khong bao gio co truong `tong`.
 *
 * Hinh dang nay chep dung `HaiCot` cua backend, ke ca cho no thieu: mot phep
 * cong `metered + unmetered` o FE se dung lai chinh con so ma §9.5 cam tron.
 */
export interface HaiCot {
  metered: SoTien;
  unmetered: SoTien;
}

export interface HangChiPhi extends HaiCot {
  key: string;
  label: string | null;
}

/** `system` = tien cua nguoi van hanh, `byok` = tien cua nguoi dung (§10.5). */
export type NguonKhoa = "system" | "byok";

export interface ChiPhiRa {
  since: string;
  until: string;
  /** Bo loc dang ap cho `totals`/`by_day`/`by_user`/`by_model`. `null` = moi nguon. */
  key_source: NguonKhoa | null;
  totals: HaiCot;
  by_day: HangChiPhi[];
  by_user: HangChiPhi[];
  by_model: HangChiPhi[];
  /** LUON du ca hai nguon, ke ca khi `key_source` khac `null` — xem `admin_usage`. */
  by_key_source: HangChiPhi[];
}

export interface NapCatalogRa {
  models: number;
  version: number;
}

// ────────────────────────────── cac loi goi ──────────────────────────────

export const api = {
  danhSachModel: () => request<ModelRa[]>("/models"),

  /**
   * §18.2 — mot TRANG cua sidebar. `updatedBefore` la `next_cursor` cua trang
   * truoc; bo trong de lay trang dau.
   *
   * Con tro di qua `URLSearchParams` chu khong noi chuoi: `next_cursor` la mot
   * `datetime` pydantic tuan tu hoa (`2026-09-22T01:02:03.456789+00:00`), va
   * dau `+` cua mui gio la mot KY TU CO NGHIA trong query string — noi thang
   * vao URL thi server doc duoc mot dau cach va tra `422`.
   *
   * KHONG co tham so `limit`: kich thuoc trang la cau hinh cua server
   * (`CONVERSATION_PAGE_SIZE`, A3). FE gui mot con so o day la chep mot han
   * muc sang phia khong so huu no.
   */
  danhSachHoiThoai: (updatedBefore?: string | null) =>
    request<DanhSachHoiThoai>(
      updatedBefore === undefined || updatedBefore === null
        ? "/conversations"
        : `/conversations?${new URLSearchParams({ updated_before: updatedBefore }).toString()}`,
    ),

  taoHoiThoai: (body: { title?: string | null; default_model?: string | null } = {}) =>
    request<HoiThoaiRa>("/conversations", { method: "POST", body: JSON.stringify(body) }),

  docHoiThoai: (id: string) => request<HoiThoaiChiTiet>(`/conversations/${id}`),

  /**
   * §18.2 — BON truong: tieu de, model mac dinh, ghim, va con tro nhanh.
   *
   * `SuaHoiThoai` doc `model_fields_set` o phia server, nen **vang mat khac
   * `null`**: khong gui `title` la "dung dung toi tieu de", gui `title: null`
   * la "xoa tieu de". Hai nghia khac nhau phai di bang hai body khac nhau —
   * do la ly do kieu duoi day dung `?:` chu khong dat gia tri mac dinh.
   *
   * `pinned` **khong** nhan `null` (cot `NOT NULL` — server tra `400`), nen
   * kieu o day la `boolean` chu khong `boolean | null`: mot lan `pinned: null`
   * phai la loi luc `tsc` chay, khong phai mot `400` luc nguoi dung bam nut.
   *
   * Tra ve **ca duong di** (`HoiThoaiChiTiet`) chu khong chi metadata, vi
   * `active_leaf_id` la mot trong bon truong — xem docstring cua handler.
   */
  suaHoiThoai: (
    id: string,
    thayDoi: {
      active_leaf_id?: string | null;
      title?: string | null;
      pinned?: boolean;
      default_model?: string | null;
    },
  ) =>
    request<HoiThoaiChiTiet>(`/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(thayDoi),
    }),

  /**
   * §18.2 — xoa **MEM** (C12): hoi thoai bien khoi moi truy van mac dinh, cay
   * message ben duoi van nguyen trong Postgres toi luot purge.
   *
   * Tra `204` (khong body), nen `request` tra `undefined` — dung nhanh 204 da
   * co san o tren. Xoa lan thu hai la `404` chu khong `204`.
   */
  xoaHoiThoai: (id: string) =>
    request<void>(`/conversations/${id}`, { method: "DELETE" }),

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

  // ───────────────────────────── §11.2 — phien ──────────────────────────────
  //
  // Khong mot loi goi nao duoi day cham toi JWT: ca access token lan refresh
  // token deu nam trong cookie `HttpOnly` do server dat (NQ-36), tuc JS cua
  // trang KHONG doc duoc chung — va do la ca diem cua NQ-36. FE chi biet "da
  // dang nhap hay chua" qua `toiLaAi()`, khong qua mot bien trong bo nho.

  /**
   * §11.6 — `turnstile_token` la `null` khi widget tat (`VITE_TURNSTILE_SITE_KEY`
   * rong). Gui `null` chu khong bo han truong: backend doc no bang mot truong
   * tuy chon o tang schema nhung BAT BUOC o tang luat khi `TURNSTILE_SECRET` co
   * gia tri, va hai hinh dang body khac nhau cho cung mot form la mot cho de
   * lech them.
   */
  dangKy: (email: string, password: string, turnstileToken: string | null) =>
    request<ThongBaoRa>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, turnstile_token: turnstileToken }),
    }),

  xacThucEmail: (token: string) =>
    request<XacThucEmailRa>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  /** Han muc 3/gio (§18.1) — nut goi no phai noi ra dieu do khi bi tu choi. */
  guiLaiXacThuc: (email: string) =>
    request<ThongBaoRa>("/auth/resend-verification", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  quenMatKhau: (email: string, turnstileToken: string | null) =>
    request<ThongBaoRa>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email, turnstile_token: turnstileToken }),
    }),

  /** KHONG dang nhap ai ca (NQ-44) — no con xoa hai cookie phien dang co. */
  datLaiMatKhau: (token: string, password: string) =>
    request<DatLaiMatKhauRa>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),

  dangNhap: (email: string, password: string) =>
    request<NguoiDungRa>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  dangXuat: () => request<{ status: string }>("/auth/logout", { method: "POST" }),

  toiLaAi: () => request<NguoiDungRa>("/auth/me"),

  // ──────────────────────────── §16.3 — quan tri ────────────────────────────
  //
  // Bay loi goi nay deu di qua `require_admin` o phia server (§16.3: *"moi
  // endpoint /api/v1/admin/* kiem lai quyen phia server"*). Viec FE co hien
  // nut hay khong KHONG phai mot lop bao ve, va man `/admin` co dua ai do vao
  // duoc thi cung khong doi duoc cau tra loi cua bay endpoint nay.

  quanTriDanhSachUser: (trangThai?: TrangThaiUser) =>
    request<AdminUserListRa>(
      trangThai === undefined ? "/admin/users" : `/admin/users?status=${trangThai}`,
    ),

  quanTriDoiTrangThai: (userId: string, hanhDong: HanhDongUser) =>
    request<AdminUserRa>(`/admin/users/${userId}/${hanhDong}`, { method: "POST" }),

  /** `nguon === null` la "moi nguon" — xem `ChiPhiRa.key_source`. */
  quanTriChiPhi: (nguon: NguonKhoa | null) =>
    request<ChiPhiRa>(nguon === null ? "/admin/usage" : `/admin/usage?key_source=${nguon}`),

  quanTriNapCatalog: () =>
    request<NapCatalogRa>("/admin/catalog/reload", { method: "POST" }),
};
