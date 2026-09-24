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
interface ErrorEnvelope {
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
export const ERROR_CODES = {
  UNAUTHENTICATED: "UNAUTHENTICATED",
  GENERATING: "GENERATION_IN_PROGRESS",
  /**
   * `409` cua §11.4 — mot request KHAC mang cung `Idempotency-Key` con dang
   * chay. **Khac** `GENERATING` o tren: cai kia noi ve mot MESSAGE dang sinh
   * (409 cua `retry`), cai nay noi ve mot KHOA dang bi giu. Hai ma, hai cau
   * tra loi cho nguoi dung — xem `backend/app/core/errors.py`.
   */
  KEY_IN_USE: "IN_PROGRESS",
  WRONG_PASSWORD: "INVALID_CREDENTIALS",
  ACCOUNT_DISABLED: "ACCOUNT_DISABLED",
  ADMIN_REQUIRED: "ADMIN_REQUIRED",

  // T-3.1b — sau ma loi cua sau man auth. Tat ca deu la ma ma NGUOI DUNG phai
  // doc duoc mot cau khac nhau, khong phai ma de log: `message` cua backend
  // viet bang tieng Viet khong dau (`mat khau qua pho bien, hay chon mat khau
  // khac`) nen no khong dat len man hinh duoc.
  TURNSTILE_FAILED: "TURNSTILE_FAILED",
  PASSWORD_TOO_SHORT: "PASSWORD_TOO_SHORT",
  PASSWORD_TOO_WEAK: "PASSWORD_TOO_WEAK",
  TOKEN_INVALID: "TOKEN_INVALID",
  TOO_MANY_ATTEMPTS: "RATE_LIMITED",

  /**
   * T-3.11 — `429` cua cua chan §10.2 (UC-07 dong 3). `details` mang
   * `limit_type` + `retry_after`, nhung FE KHONG doc chung o day: thanh quota
   * doc lai `/auth/me` de chi co MOT nguon cho thoi diem hoan lai.
   */
  QUOTA_EXCEEDED: "QUOTA_EXCEEDED",
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
    throw await parseError(res);
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
async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as Partial<ErrorEnvelope>;
    if (body.error?.code) {
      return new ApiError(res.status, body.error.code, body.error.message, body.error.details);
    }
  } catch {
    // khong phai JSON — roi xuong duong lui
  }
  return new ApiError(res.status, "HTTP_ERROR", `HTTP ${res.status} ${res.statusText}`);
}

// ─────────────────────────── kieu tra ve cua §18.2 ───────────────────────────

export type Role = "system" | "user" | "assistant" | "tool";
export type MessageStatus = "queued" | "streaming" | "completed" | "failed" | "cancelled";

/**
 * Hai gia tri cua enum `message_feedback` (§18.2, T-3.7a).
 *
 * `null` = **chua ai bam gi**, va no khong phai mot nhan thu ba: cot trong
 * Postgres la `NULL`, va cung `null` ay la cach GO mot danh gia da bam. Mot
 * nhan `"none"` se cho hai cach viet cung mot su that.
 */
export type Feedback = "like" | "dislike";

/** Mot node tren duong di hien tai — `PathMessage` cua backend. */
export interface MessageOut {
  id: string;
  parent_id: string | null;
  role: Role;
  status: MessageStatus;
  content: string;
  reasoning: string | null;
  model_id: string | null;
  finish_reason: string | null;
  error_code: string | null;
  created_at: string;
  /** Dem tu 0 (B-60, NQ-33). `‹ n/m ›` hien `sibling_index + 1`. */
  sibling_index: number;
  sibling_count: number;
  /**
   * Like/Dislike da luu (§18.2, T-3.7a). Hai nut duoi cau tra loi ve trang
   * thai cua chung **tu day**, khong tu mot ban sao trong state cua FE — F5
   * phai ra dung thu vua bam, va duong duy nhat bao dam dieu do la doc lai tu
   * server.
   *
   * KHONG co `feedback_reason` di kem: backend co y khong cho no di theo duong
   * di (mot truong tu do 2000 ky tu tren bang ma moi lan mo hoi thoai deu keo
   * ca hang ve). Xem B-244.
   */
  feedback: Feedback | null;
}

export interface ConversationOut {
  id: string;
  title: string | null;
  default_model: string | null;
  system_prompt_override: string | null;
  active_leaf_id: string | null;
  pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationOut {
  /** Goc truoc, la sau. Rong khi `active_leaf_id` la NULL. */
  path: MessageOut[];
}

export interface ConversationList {
  items: ConversationOut[];
  next_cursor: string | null;
}

/**
 * `QuotaWarning` cua backend — UC-07 dong 1, trong body `202` (T-2.11).
 *
 * NGUON THU HAI cua cung con so ma `QuotaWindow` cua `/auth/me` mang (T-3.11):
 * cung nam truong dau, cung luat tien-la-chuoi. Khong co `retry_after` vi mot
 * `202` nghia la luot nay da qua cua chan — chua co gi de cho.
 *
 * `null` khi con tren nguong, va LUON `null` cho luot BYOK (§10.5): luot ay
 * khong tru quota nen khong co gi de canh bao.
 */
export interface QuotaWarning {
  limit_type: LimitType;
  limit_usd: string;
  spent_usd: string;
  remaining_usd: string;
  remaining_pct: number;
}

export interface CreateMessageOut {
  user_message_id: string;
  assistant_message_id: string;
  /** Duong dan TUONG DOI, da co san tien to `/api/v1`. Khong noi BASE_URL. */
  stream_url: string;
  /** C14 — `parent_id` client gui khac la hien tai, tuc vua mo mot nhanh. */
  branched: boolean;
  quota_warning: QuotaWarning | null;
}

export interface RetryOut {
  assistant_message_id: string;
  stream_url: string;
  model_id: string;
  quota_warning: QuotaWarning | null;
}

/**
 * `POST /messages/{id}/feedback` — trang thai SAU khi ghi (§18.2, T-3.7a).
 *
 * `feedback_reason` co mat o day va CHI o day: `MessageOut` khong mang no (xem
 * docstring cua truong `feedback`), nen ai vua go mot ly do thi nhan lai
 * nguyen van trong chinh response nay — va khong o dau khac (B-244).
 */
export interface FeedbackOut {
  message_id: string;
  feedback: Feedback | null;
  feedback_reason: string | null;
}

export interface EditMessageOut {
  /** Message MOI, khong phai id tren duong dan — xem `EditMessageResponse`. */
  user_message_id: string;
  assistant_message_id: string;
  stream_url: string;
  quota_warning: QuotaWarning | null;
}

export interface SiblingsOut {
  message_id: string;
  parent_id: string | null;
  sibling_index: number;
  sibling_count: number;
  items: MessageOut[];
}

export interface CancelOut {
  message_id: string;
  status: MessageStatus;
  cancel_requested: boolean;
}

export interface ModelOut {
  id: string;
  display_name: string;
  /** Ten HANG de hien (`DeepSeek`, `Google AI`) — khong dung de so voi thu gi. */
  provider: string;
  /**
   * Khoa provider trong catalog (`deepseek`) — dung chuoi ma
   * `ProviderKey.provider` mang. B-257: so khoa BYOK voi `provider` (nhan) o
   * tren thi khong bao gio khop.
   *
   * `null` cho model di qua duong trung gian (T-S.3, NQ-119/NQ-123): ten duong
   * di khong toi nguoi dung, va khong khoa BYOK nao so duoc voi no.
   */
  provider_id: string | null;
  capabilities: string[];
  context_window: number;
  max_output: number;
  default: boolean;
  badge: string | null;
  /**
   * §18.3 — `false` = provider cua model nay khong tra loi luc do gan nhat.
   *
   * Model VAN nam trong danh sach (UC-05 dong 2 doi "hien xam", khong doi
   * "bien mat"), nen moi cho duyet mang nay phai tu quyet dinh lam gi voi no.
   */
  available: boolean;
  /**
   * Cau tieng Viet hien NGUYEN VAN trong tooltip. `null` khi `available`.
   *
   * Khong dich va khong cat: do dai khong doan truoc duoc (ban T-HD4 do mot
   * cau 150+ ky tu), nen cho hien no phai tu xuong dong.
   */
  unavailable_reason: string | null;
}

/** `PUT /settings` — §18.4, B-206/NQ-79. Cung hinh dang voi body gui di. */
export interface SettingsOut {
  default_model: string | null;
}

// ─────────────────── kieu cua §11.2 (auth) va §16.3 (admin) ──────────────────

/** Nam trang thai cua §11.1. */
export type UserStatus =
  | "pending_email"
  | "pending_approval"
  | "active"
  | "rejected"
  | "suspended";

export type UserRole = "user" | "admin";

/** `UserOut` cua backend — hinh dang chung cua `/login`, `/refresh`, `/me`. */
export interface UserOut {
  id: string;
  email: string;
  display_name: string | null;
  status: UserStatus;
  role: UserRole;
  tier_name: string;
  /**
   * Model mac dinh cua nguoi nay (§18.4, B-206) — `null` = chua chon, FE roi
   * ve `default: true` cua catalog. Nam o lop CHUNG vi no la mot cot cua hang
   * `users`, tuc ca ba duong deu tra.
   */
  default_model: string | null;
}

/** Hai gia tri cua `limit_type` (§10.3, UC-07) — `5h` va `weekly`. */
export type LimitType = "5h" | "weekly";

/**
 * Mot cua so truot cua §10.3 — `WindowSnapshot` cua backend.
 *
 * Bon con so tien la CHUOI, khong `number`: backend tra `Decimal` va pydantic
 * tuan tu hoa no thanh chuoi — cung luat da dua `cost_usd` tu Postgres toi FE
 * o `UsageAmount`. Doi sang so mot lan de HIEN, khong de cong.
 */
export interface QuotaWindow {
  limit_type: LimitType;
  limit_usd: string;
  spent_usd: string;
  remaining_usd: string;
  /** Lam tron XUONG — con so hien ra khong bao gio lac quan hon su that. */
  remaining_pct: number;
  /** Giay cho toi khi duoi tran lai, hoac `null`. Cung don vi voi `Retry-After`. */
  retry_after: number | null;
}

/**
 * `ProfileOut` — rieng `GET /auth/me`, rong hon `UserOut` dung hai truong.
 *
 * B-213/NQ-81: ba task cua Phase 3 doc BA nhom khac nhau cua CUNG mot
 * response — T-3.4 lay `message_max_chars`, T-3.6 lay `default_model`, T-3.11
 * lay `quota`. Hinh dang day du duoc khai MOT lan o day chu khong moi task
 * them mot manh, vi `request<T>()` **ep kieu** response chu khong kiem no:
 * mot truong thieu trong interface khong sinh loi nao, no chi im lang bien
 * mat truoc khi component kip doc.
 */
export interface ProfileOut extends UserOut {
  /**
   * `null` = khong do duoc luc nay (Redis khong tra loi), **khong** phai
   * "khong co han muc". FE an thanh quota di chu dung ve mot thanh rong.
   */
  quota: QuotaWindow[] | null;
  /** Tran do dai mot message, tinh bang ky tu (B-205, NQ-78) — A3: khong literal o FE. */
  message_max_chars: number;
  /**
   * T-3.11 — nguong "con <= N%" cua UC-07 dong 1. Cung bien `.env` voi
   * `quota_warning` cua `202`, nen thanh quota khong co nguong rieng de lech.
   */
  quota_warn_remaining_pct: number;
}

/**
 * Mot khoa BYOK da luu — `ProviderKeyOut` cua backend (§10.5, T-2.14).
 *
 * T-3.11 chi doc `provider` + `usable`: hai truong du de biet model dang chon
 * co di bang tien cua chinh nguoi dung hay khong (Cam bay ① — BYOK van gui
 * duoc khi het quota system key).
 */
export interface ProviderKey {
  provider: string;
  masked_key: string;
  verified_at: string | null;
  created_at: string;
  usable: boolean;
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
export interface NoticeOut {
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
export interface VerifyEmailOut {
  status: "verified" | "already_verified" | "expired";
}

export interface ResetPasswordOut {
  status: "reset";
}

/** Ba nut cua man "Duyet user" (§16.3) — khop `hanh_dong` cua backend. */
export type UserAction = "approve" | "reject" | "suspend";

/** Mot hang cua bang "Nguoi dung" (§16.3). KHONG co truong nao suy ra mat khau. */
export interface AdminUserOut {
  id: string;
  email: string;
  display_name: string | null;
  status: UserStatus;
  role: UserRole;
  tier_name: string;
  limit_override_json: Record<string, unknown> | null;
  email_verified_at: string | null;
  approved_at: string | null;
  approved_by: string | null;
  last_login_at: string | null;
  created_at: string;
}

/**
 * Mot hang cua DANH SACH `GET /admin/users` — `AdminUserOut` + hai cot NQ-66
 * (T-3.12). Chi danh sach co hai cot nay: `approve`/`PATCH` tra mot hang vua
 * doi, khong chay cau gom nhom nao.
 */
export interface AdminUserListItem extends AdminUserOut {
  /** Hoi thoai chua xoa mem. `0` khi chua co — khong bao gio `null`. */
  conversation_count: number;
  /**
   * Tien HE THONG trong cua so quota dai — CHUOI sau chu so thap phan
   * (`"0.300000"`), cung tap ma quota 7 ngay cua nguoi ay cong.
   */
  spend_7d_usd: string;
}

export interface AdminUserListOut {
  users: AdminUserListItem[];
}

/** Body cua `PATCH /admin/users/{id}` — vang mat khac `null` (model_fields_set). */
export interface AdminUserPatch {
  tier_name?: string;
  /** `null` = xoa het ghi de, quay ve dung han muc cua tier. */
  limit_override?: Record<string, unknown> | null;
}

/** Mot hang `tiers` — `TierOut` (§10.4). Tien la CHUOI. */
export interface TierRow {
  name: string;
  limit_5h_usd: string;
  limit_7d_usd: string;
  can_execute_skills: boolean;
  can_use_web: boolean;
  web_searches_per_day: number;
  max_upload_mb: number;
  max_attachments: number;
  allowed_model_tags: string[];
  /** Doc duoc, KHONG sua duoc (B-152) — man hinh khong ve cong tac cho no. */
  is_default: boolean;
}

export interface TierList {
  tiers: TierRow[];
  /**
   * `TIER_CACHE_TTL_S` — doi tier/han muc co hieu luc trong TOI DA ngan nay
   * giay (NQ-51). Con so cua cau "Co hieu luc trong vong N giay" den tu day,
   * khong chep tay vao `vi.json` (A3).
   */
  limits_cache_ttl_s: number;
}

/** Tam truong sua duoc cua mot tier — bang dung `OVERRIDABLE_FIELDS`. */
export type TierPatch = Partial<Omit<TierRow, "name" | "is_default">>;

/** Mot muc kiem cua `run_checks()` — `CheckResult` cua backend. */
export interface HealthCheck {
  ok: boolean;
  latency_ms: number;
  /** Ly do hong. Tu B-193 khong bao gio rong khi `ok=false`, nhung FE van phong. */
  error: string | null;
}

/** `GET /admin/system` (§16.3, T-2.20 + B-192). */
export interface SystemStatus {
  version: string;
  /** `null` = khong hoi duoc Redis — KHONG phai "hang doi rong". */
  queue_depth: number | null;
  /** Ten khoa tieng Viet khong dau CO Y (NQ-70 ②) — doc dung ten ay. */
  streams_dang_chay: number | null;
  health: Record<string, HealthCheck>;
  /** Luc `health` duoc DO — co the cu toi `ADMIN_HEALTH_CACHE_TTL_S` giay. */
  health_checked_at: string;
}

/** `GET /health/deep` (§18.6) — cong khai, tra `503` khi ha tang loi da hong. */
export interface DeepHealth {
  status: "ok" | "degraded" | "down";
  checks: Record<string, HealthCheck>;
}

/** Sau gia tri cua `audit_logs.action` — `AuditAction` cua backend. */
export type AuditActionName =
  | "user.approve"
  | "user.reject"
  | "user.suspend"
  | "user.update"
  | "tier.update"
  | "catalog.reload";

/** Mot dong so — "ai, luc nao, lam gi, voi ai" (§16.3, B-191). */
export interface AuditEntry {
  id: number;
  created_at: string;
  actor_id: string | null;
  actor_email: string | null;
  actor_display_name: string | null;
  action: AuditActionName;
  /** Ten BANG (`users`, `tiers`, `catalog`) — xem `TARGET_*` cua backend. */
  target_type: string | null;
  target_id: string | null;
  /** B-191 — `null` khi dich khong phai nguoi, hoac nguoi ay da xoa. */
  target_email: string | null;
  target_display_name: string | null;
  details: Record<string, unknown> | null;
  ip: string | null;
}

export interface AuditPage {
  items: AuditEntry[];
  /** Gui lai vao `?before_id=` de lay trang ke; `null` = het. */
  next_cursor: number | null;
}

/** Mot provider nhan khoa rieng — o chon cua trang Cai dat (T-3.12). */
export interface ByokProvider {
  /** KHOA catalog (`deepseek`) — thu `PUT /settings/keys/{provider}` nhan. */
  provider: string;
  label: string;
}

export interface ProviderKeyList {
  keys: ProviderKey[];
  byok_providers: ByokProvider[];
}

/**
 * `cost_usd` la CHUOI, khong phai `number`.
 *
 * Backend tra `Decimal` va pydantic tuan tu hoa no thanh chuoi — doc thang
 * vao mot `number` la lam tron mot con so tien ngay tai bien vao cua FE. Cho
 * duy nhat duoc phep doi sang so la ham dinh dang, va no doi mot lan de HIEN,
 * khong de cong.
 */
export interface UsageAmount {
  cost_usd: string;
  prompt_tokens: number;
  completion_tokens: number;
  events: number;
}

/**
 * Hai cot tach rieng cua C16 — khong bao gio co truong `tong`.
 *
 * Hinh dang nay chep dung `MeteredSplit` cua backend, ke ca cho no thieu: mot phep
 * cong `metered + unmetered` o FE se dung lai chinh con so ma §9.5 cam tron.
 */
export interface MeteredSplit {
  metered: UsageAmount;
  unmetered: UsageAmount;
}

export interface CostRow extends MeteredSplit {
  key: string;
  label: string | null;
}

/** `system` = tien cua nguoi van hanh, `byok` = tien cua nguoi dung (§10.5). */
export type KeySource = "system" | "byok";

export interface CostsOut {
  since: string;
  until: string;
  /** Bo loc dang ap cho `totals`/`by_day`/`by_user`/`by_model`. `null` = moi nguon. */
  key_source: KeySource | null;
  totals: MeteredSplit;
  by_day: CostRow[];
  by_user: CostRow[];
  by_model: CostRow[];
  /** LUON du ca hai nguon, ke ca khi `key_source` khac `null` — xem `admin_usage`. */
  by_key_source: CostRow[];
}

export interface ReloadCatalogOut {
  models: number;
  version: number;
}

// ────────────────────────────── cac loi goi ──────────────────────────────

export const api = {
  listModels: () => request<ModelOut[]>("/models"),

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
  listConversations: (updatedBefore?: string | null) =>
    request<ConversationList>(
      updatedBefore === undefined || updatedBefore === null
        ? "/conversations"
        : `/conversations?${new URLSearchParams({ updated_before: updatedBefore }).toString()}`,
    ),

  createConversation: (body: { title?: string | null; default_model?: string | null } = {}) =>
    request<ConversationOut>("/conversations", { method: "POST", body: JSON.stringify(body) }),

  getConversation: (id: string) => request<ConversationDetail>(`/conversations/${id}`),

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
   * Tra ve **ca duong di** (`ConversationDetail`) chu khong chi metadata, vi
   * `active_leaf_id` la mot trong bon truong — xem docstring cua handler.
   */
  updateConversation: (
    id: string,
    overrides: {
      active_leaf_id?: string | null;
      title?: string | null;
      pinned?: boolean;
      default_model?: string | null;
    },
  ) =>
    request<ConversationDetail>(`/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(overrides),
    }),

  /**
   * §18.2 — xoa **MEM** (C12): hoi thoai bien khoi moi truy van mac dinh, cay
   * message ben duoi van nguyen trong Postgres toi luot purge.
   *
   * Tra `204` (khong body), nen `request` tra `undefined` — dung nhanh 204 da
   * co san o tren. Xoa lan thu hai la `404` chu khong `204`.
   */
  deleteConversation: (id: string) =>
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
  sendMessage: (
    conversationId: string,
    body: { content: string; parent_id?: string | null; model_id?: string | null },
    idempotencyKey: string,
  ) =>
    request<CreateMessageOut>(`/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),

  cancel: (messageId: string) => request<CancelOut>(`/messages/${messageId}/cancel`, { method: "POST" }),

  /**
   * §8.2 — sinh lai mot cau tra loi thanh ANH EM cua no. `202` + `stream_url`.
   *
   * `idempotencyKey` la tham so **bat buoc** tu NQ-93/B-231: route nay nay
   * nam trong `IDEMPOTENCY_REQUIRED_ROUTES`, thieu header ⇒ `400`. Cung ly le
   * `sendMessage`: moi lan bam sinh mot `assistant_message_id` moi nen bam hai
   * lan la hai hoa don, va lop `_job_id` cua B-92 khong do duoc chieu nay.
   *
   * Khoa do NGUOI GOI cam, khong sinh tai cho (C22) — sinh o day nghia la hai
   * lan bam nhanh mang hai khoa khac nhau, tuc luat §11.4 vo dung dung luc no
   * can chay. Chu so huu khoa la `useChat.retry`.
   *
   * `model_id` vang mat ⇒ backend dung lai `messages.model_id` cua chinh cau
   * tra loi dang thu lai (xem `_pick_model`), tuc nut "Thu lai" tron. Nut
   * "Doi model & thu lai" la cho duy nhat truyen mot `model_id` khac.
   */
  retry: (
    messageId: string,
    body: { model_id?: string | null },
    idempotencyKey: string,
  ) =>
    request<RetryOut>(`/messages/${messageId}/retry`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),

  /**
   * §18.2 — Like/Dislike tren mot cau tra loi (T-3.7a).
   *
   * `gia` la `null` de **go** danh gia, va no phai di trong body mot cach
   * tuong minh: backend khai `value` la truong BAT BUOC ke ca khi gia tri la
   * `null`, nen mot body rong la `422` chu khong phai mot lan go am tham.
   *
   * `reason` chi gui khi co chu: `{value: null, reason: "..."}` la `422` (mot ly
   * do khong kem danh gia la mot hang khong doc duoc), va `reason` vang mat
   * doc thanh `NULL` chu khong phai "giu nguyen cai cu".
   *
   * KHONG co `Idempotency-Key`: day la mot `UPDATE` hai cot tren mot hang da
   * co, bam hai lan ra dung mot trang thai — cung ly le `api/v1/__init__.py`
   * dung cho moi POST cua `/admin/*` (A8 noi ve POST **tao tai nguyen**).
   */
  sendFeedback: (messageId: string, value: Feedback | null, reason?: string) =>
    request<FeedbackOut>(`/messages/${messageId}/feedback`, {
      method: "POST",
      body: JSON.stringify(
        reason === undefined || reason === "" ? { value: value } : { value: value, reason: reason },
      ),
    }),

  editQuestion: (messageId: string, content: string) =>
    request<EditMessageOut>(`/messages/${messageId}`, {
      method: "PATCH",
      body: JSON.stringify({ content }),
    }),

  siblings: (messageId: string) => request<SiblingsOut>(`/messages/${messageId}/siblings`),

  // ───────────────────────────── §11.2 — phien ──────────────────────────────
  //
  // Khong mot loi goi nao duoi day cham toi JWT: ca access token lan refresh
  // token deu nam trong cookie `HttpOnly` do server dat (NQ-36), tuc JS cua
  // trang KHONG doc duoc chung — va do la ca diem cua NQ-36. FE chi biet "da
  // dang nhap hay chua" qua `me()`, khong qua mot bien trong bo nho.

  /**
   * §11.6 — `turnstile_token` la `null` khi widget tat (`VITE_TURNSTILE_SITE_KEY`
   * rong). Gui `null` chu khong bo han truong: backend doc no bang mot truong
   * tuy chon o tang schema nhung BAT BUOC o tang luat khi `TURNSTILE_SECRET` co
   * gia tri, va hai hinh dang body khac nhau cho cung mot form la mot cho de
   * lech them.
   */
  register: (email: string, password: string, turnstileToken: string | null) =>
    request<NoticeOut>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, turnstile_token: turnstileToken }),
    }),

  verifyEmail: (token: string) =>
    request<VerifyEmailOut>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  /** Han muc 3/gio (§18.1) — nut goi no phai noi ra dieu do khi bi tu choi. */
  resendVerification: (email: string) =>
    request<NoticeOut>("/auth/resend-verification", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  forgotPassword: (email: string, turnstileToken: string | null) =>
    request<NoticeOut>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email, turnstile_token: turnstileToken }),
    }),

  /** KHONG dang nhap ai ca (NQ-44) — no con xoa hai cookie phien dang co. */
  resetPassword: (token: string, password: string) =>
    request<ResetPasswordOut>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    }),

  login: (email: string, password: string) =>
    request<UserOut>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  logout: () => request<{ status: string }>("/auth/logout", { method: "POST" }),

  /**
   * §18.1 — *"User + tier + quota con lai + trang thai"*. Tra `ProfileOut`, tuc
   * rong hon `/login` va `/refresh` dung hai truong (B-213).
   */
  me: () => request<ProfileOut>("/auth/me"),

  // ──────────────────────────── §16.3 — quan tri ────────────────────────────
  //
  // Bay loi goi nay deu di qua `require_admin` o phia server (§16.3: *"moi
  // endpoint /api/v1/admin/* kiem lai quyen phia server"*). Viec FE co hien
  // nut hay khong KHONG phai mot lop bao ve, va man `/admin` co dua ai do vao
  // duoc thi cung khong doi duoc cau tra loi cua bay endpoint nay.

  adminListUsers: (status?: UserStatus) =>
    request<AdminUserListOut>(
      status === undefined ? "/admin/users" : `/admin/users?status=${status}`,
    ),

  adminChangeStatus: (userId: string, action: UserAction) =>
    request<AdminUserOut>(`/admin/users/${userId}/${action}`, { method: "POST" }),

  /**
   * `nguon === null` la "moi nguon" — xem `CostsOut.key_source`.
   *
   * T-3.12 them `since` (ISO): man "Chi phi" hoi 7 hoac 30 ngay. Vang mat thi
   * server dung `QUOTA_WINDOW_LONG_S` (7 ngay). Cua so dai qua
   * `ADMIN_USAGE_MAX_WINDOW_DAYS` la `400` (B-175).
   */
  adminCosts: (keySource: KeySource | null, since?: string) => {
    const params = new URLSearchParams();
    if (keySource !== null) {
      params.set("key_source", keySource);
    }
    if (since !== undefined) {
      params.set("since", since);
    }
    const query = params.toString();
    return request<CostsOut>(query === "" ? "/admin/usage" : `/admin/usage?${query}`);
  },

  adminReloadCatalog: () =>
    request<ReloadCatalogOut>("/admin/catalog/reload", { method: "POST" }),

  // ── T-3.12 — bon endpoint cua T-2.20 + `PATCH /admin/users/{id}` ────────

  adminUpdateUser: (userId: string, patch: AdminUserPatch) =>
    request<AdminUserOut>(`/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  adminListTiers: () => request<TierList>("/admin/tiers"),

  adminUpdateTier: (name: string, patch: TierPatch) =>
    request<TierRow>(`/admin/tiers/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  adminSystem: () => request<SystemStatus>("/admin/system"),

  /** Mot TRANG so, moi nhat truoc. `beforeId` = `next_cursor` cua trang truoc. */
  adminAuditLogs: (beforeId?: number | null) =>
    request<AuditPage>(
      beforeId === undefined || beforeId === null
        ? "/admin/audit-logs"
        : `/admin/audit-logs?${new URLSearchParams({ before_id: String(beforeId) }).toString()}`,
    ),

  /**
   * `GET /health/deep` — duong lui cua man "He thong" khi chinh API quan tri
   * khong tra loi (B-190: Redis chet ⇒ `require_app_access` tra `503` truoc
   * khi `/admin/system` kip chay, C21). Endpoint nay cong khai va tra `503`
   * KEM than day du khi mot ha tang loi da hong — nen `503` o day la mot cau
   * tra loi doc duoc, khong phai mot loi. Moi ma khac van la loi.
   */
  healthDeep: async (): Promise<DeepHealth> => {
    const res = await fetch(`${BASE_URL}/health/deep`, { credentials: "same-origin" });
    if (res.ok || res.status === 503) {
      try {
        return (await res.json()) as DeepHealth;
      } catch {
        // 503 cua Nginx la HTML — roi xuong nhanh loi.
      }
    }
    throw await parseError(res);
  },

  // ────────────────────── §18.4 — cai dat ca nhan (T-3.0) ───────────────────

  /**
   * Ghi model mac dinh CUA CHINH MINH (§18.4, UC-05 dong 4, B-206).
   *
   * Khong co tham so `userId`: duong dan khong mang `{id}` va body khong co
   * truong nao tro sang nguoi khac — server lay danh tinh tu cookie phien.
   *
   * `null` = BO CHON, tuc quay ve bac thang mac dinh (§9.2). Do la mot y
   * dinh co that chu khong phai "khong gui gi", nen kieu o day la
   * `string | null` chu khong `string | undefined`.
   *
   * `400 MODEL_UNKNOWN` khi model khong con trong catalog hoac da tat:
   * backend validate luc GHI chu khong luc doc (Cam bay ③ cua T-3.0), nen
   * ben goi phai do duoc ca nhanh nay.
   *
   * KHONG co `getCaiDat()` di kem: ve `GET` cua §18.4 co y chua dung
   * (`default_model` da di ra trong `GET /auth/me`) — xem docstring cua
   * `backend/app/api/v1/settings.py`.
   */
  updateSettings: (defaultModel: string | null) =>
    request<SettingsOut>("/settings", {
      method: "PUT",
      body: JSON.stringify({ default_model: defaultModel }),
    }),

  /**
   * §10.5 — khoa BYOK cua CHINH MINH, chi phan che (T-2.14). T-3.12: kem
   * `byok_providers` (moi provider catalog nhan khoa rieng).
   */
  listProviderKeys: () => request<ProviderKeyList>("/settings/keys"),

  /**
   * Them / thay khoa BYOK (§10.5). Ban ro di MOT lan, trong body nay; server
   * kiem voi provider roi chi tra ban che (`sk-...4f2a`). Ben goi phai xoa o
   * nhap ngay sau khi goi — thanh cong hay khong.
   */
  putProviderKey: (provider: string, key: string) =>
    request<ProviderKey>(`/settings/keys/${encodeURIComponent(provider)}`, {
      method: "PUT",
      body: JSON.stringify({ key }),
    }),

  deleteProviderKey: (provider: string) =>
    request<void>(`/settings/keys/${encodeURIComponent(provider)}`, { method: "DELETE" }),
};
