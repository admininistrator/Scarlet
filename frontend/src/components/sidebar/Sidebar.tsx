import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { ApiError, api, type HoiThoaiRa } from "../../lib/api";
import { t } from "../../lib/i18n";

/**
 * Sidebar hoi thoai — T-3.3.
 *
 * KH tham chieu: §18.2, §17.4 · tasks.md T-3.3 · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BA CAU PHAI NOI RA TREN MAN HINH, KHONG GIAU TRONG DOCSTRING          ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * **1. Tim kiem chi chay tren PHAN DA TAI.** Khong co endpoint tim toan van
 * nao (B-09 chua lam), nen o tim o day loc mang trong bo nho — no khong goi
 * mang mot lan nao. Mot nguoi go ten mot hoi thoai cu ma khong thay gi se
 * ket luan "hoi thoai bi mat" chu khong ket luan "no nam o trang sau", nen
 * cau ay phai nam canh o tim (`sidebar.timKiemGhiChu`).
 *
 * **2. Ghim cung chi noi trong PHAN DA TAI.** Backend sap xep
 * `ORDER BY updated_at DESC, id DESC` — doc duoc o
 * `app/db/repositories/conversations.py`, khong mot chu `pinned` nao. Sidebar
 * day ghim len dau o `sortConversations()` duoi day, tuc mot hoi thoai ghim
 * tu thang truoc nam o trang 3 se **vang mat** o dau danh sach cho toi khi
 * nguoi dung bam "Tai them". Xem Cam bay ① cua T-3.3: nga con lai la them
 * `pinned DESC` vao `ORDER BY` cua backend, va no keo theo mot con tro phan
 * trang khac han — do la mot thay doi hop dong backend, khong thuoc task nay.
 *
 * **3. "Xoa" la xoa MEM.** `DELETE /conversations/{id}` dat `deleted_at`, cay
 * message ben duoi khong bi dung toi (C12), va ban ghi con nam tren may chu
 * toi luot purge. Chu tren man hinh phai noi dung thu no lam
 * (`sidebar.xoaGhiChu`) — con so ngay cu the (`PURGE_AFTER_DAYS`) khong duoc
 * chep vao day: no la mot han muc sống trong `.env` va khong endpoint nao tra
 * no ra cho FE (A3).
 *
 * ── Con tro phan trang den TU RESPONSE, khong suy ra tu danh sach ─────────
 *
 * `next_cursor` la `updated_at` cua dong cuoi trang **theo thu tu cua
 * server**. Sidebar sap xep lai theo thu tu cua rieng no (ghim len dau), nen
 * `items[items.length - 1].updated_at` sau khi sap xep KHONG con la con tro
 * dung. Vi vay con tro song trong mot state rieng (`cursor`) chu khong duoc
 * tinh lai tu `items`.
 *
 * ── Vi sao van phai chong trung theo `id` ────────────────────────────────
 *
 * Con tro la `updated_at` trong khi `ORDER BY` la `(updated_at, id)` — Cam
 * bay ② cua T-3.3. Phia server, `< cursor` co the **bo sot** mot hang trung
 * `updated_at`; no khong sinh ra ban sao. Nhung con mot duong khac co that:
 * `updated_at` doi moi lan nguoi dung gui tin nhan, nen mot hoi thoai o trang
 * 1 luc dau co the tut xuong (hoac nhay len) giua hai lan goi, va luc do
 * trang 2 tra ve dung no lan nua. `mergePages()` chong trung theo `id` de DoD
 * *"khong hoi thoai nao xuat hien hai lan sau hai trang"* dung ke ca trong ca
 * ay.
 */

/** Khoa `localStorage` nho trang thai an/hien. Cung khuon `ThemeToggle`. */
const STORAGE_KEY = "scarlet-sidebar";
const STORED_OPEN = "open";
const STORED_CLOSED = "closed";

/** Ky tu khong-chu-khong-so dung de cat tu khi so khop khong dau. */
const DIACRITIC = /\p{Diacritic}/gu;

export interface SidebarProps {
  /** Hoi thoai dang mo o man chat, hoac `null` khi chua mo cai nao. */
  openConversationId: string | null;
  /** Nguoi dung bam mot hang — man chat mo hoi thoai ay. */
  onSelect: (conversationId: string) => void;
  /** Hoi thoai **dang mo** vua bi xoa: man chat phai roi khoi no. */
  onOpenConversationDeleted: () => void;
}

// ───────────────────────────── ham thuan ──────────────────────────────────
//
// Bon ham duoi day khong cham React va khong cham mang, nen chung kiem duoc
// truc tiep — do la ly do chung `export`.

/**
 * Ghim truoc, roi `updated_at` giam dan, roi `id` giam dan.
 *
 * Hai khoa sau chep dung `ORDER BY` cua server (`updated_at DESC, id DESC`)
 * de hai trang noi vao nhau khong tao ra mot thu tu thu ba. Khoa dau
 * (`pinned`) la phan **chi FE biet** — xem cau 2 o dau file.
 */
export function sortConversations(items: readonly HoiThoaiRa[]): HoiThoaiRa[] {
  return [...items].sort((a, b) => {
    if (a.pinned !== b.pinned) {
      return a.pinned ? -1 : 1;
    }
    if (a.updated_at !== b.updated_at) {
      return a.updated_at < b.updated_at ? 1 : -1;
    }
    return a.id < b.id ? 1 : -1;
  });
}

/** Noi trang moi vao trang cu, **mot hoi thoai mot lan**, ban moi thang. */
export function mergePages(
  current: readonly HoiThoaiRa[],
  incoming: readonly HoiThoaiRa[],
): HoiThoaiRa[] {
  const byId = new Map<string, HoiThoaiRa>();
  for (const item of current) {
    byId.set(item.id, item);
  }
  for (const item of incoming) {
    byId.set(item.id, item);
  }
  return [...byId.values()];
}

/** Tieu de de hien: `null` (chua ai dat ten) co mot cau rieng, khong de trong. */
export function conversationLabel(item: HoiThoaiRa): string {
  const title = item.title?.trim() ?? "";
  return title === "" ? t("sidebar.chuaDatTen") : title;
}

/**
 * So khop KHONG phan biet hoa/thuong va KHONG phan biet dau.
 *
 * Bo dau la co y chu khong phai tien the: nguoi dung go "han muc" phai tim
 * duoc "Han mưc quota". `normalize("NFD")` tach dau ra thanh ky tu rieng roi
 * `\p{Diacritic}` xoa chung — ca "đ" cua tieng Viet **khong** tach duoc theo
 * loi nay, nen no duoc doi tay truoc.
 */
export function matchesQuery(item: HoiThoaiRa, query: string): boolean {
  const needle = foldVietnamese(query);
  if (needle === "") {
    return true;
  }
  return foldVietnamese(conversationLabel(item)).includes(needle);
}

function foldVietnamese(text: string): string {
  return text
    .normalize("NFD")
    .replace(DIACRITIC, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .trim();
}

/**
 * Trang thai an/hien da luu. Thieu hoac doc khong duoc ⇒ **mo**.
 *
 * `try/catch` khong phai thua: che do rieng tu nem `SecurityError` ngay o
 * `getItem` — cung cai bay `ThemeToggle` da ghi tu T-0.10.
 */
export function storedSidebarOpen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== STORED_CLOSED;
  } catch {
    return true;
  }
}

/** `ApiError` mang `code` cua §18; thu khac chi con `message`. */
function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}

/** Bo `path` khoi response cua `PATCH` — danh sach chi can metadata. */
function metaOf(detail: HoiThoaiRa): HoiThoaiRa {
  return {
    id: detail.id,
    title: detail.title,
    default_model: detail.default_model,
    system_prompt_override: detail.system_prompt_override,
    active_leaf_id: detail.active_leaf_id,
    pinned: detail.pinned,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  };
}

// ───────────────────────────── component ──────────────────────────────────

export function Sidebar({
  openConversationId,
  onSelect,
  onOpenConversationDeleted,
}: SidebarProps) {
  const searchId = useId();

  const [open, setOpen] = useState<boolean>(storedSidebarOpen);
  const [items, setItems] = useState<HoiThoaiRa[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [renaming, setRenaming] = useState<{ id: string; draft: string } | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  /**
   * Danh sach giu them o mot `ref` — cung ly le luat 4 cua `useChat`.
   *
   * Hieu ung "hoi thoai dang mo khong nam trong danh sach ⇒ nap lai trang 1"
   * phai doc danh sach **moi nhat**, nhung neu `items` nam trong mang phu
   * thuoc cua no thi moi lan nap xong lai chay lai chinh no.
   */
  const itemsRef = useRef<HoiThoaiRa[]>([]);
  const applyItems = useCallback((change: (previous: HoiThoaiRa[]) => HoiThoaiRa[]) => {
    const next = sortConversations(change(itemsRef.current));
    itemsRef.current = next;
    setItems(next);
  }, []);

  const loadFirstPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.danhSachHoiThoai();
      applyItems(() => mergePages([], page.items));
      setCursor(page.next_cursor);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [applyItems]);

  /**
   * Nap trang dau luc mount, va nap LAI khi man chat mo mot hoi thoai chua co
   * trong danh sach — do dung la ca "vua bam Hoi thoai moi".
   *
   * Bam mot hang **da co** trong danh sach thi khong goi mang: neu goi, moi
   * lan chon mot hoi thoai la mot lan mat cac trang da tai them.
   */
  useEffect(() => {
    if (
      openConversationId !== null &&
      itemsRef.current.some((item) => item.id === openConversationId)
    ) {
      return;
    }
    void loadFirstPage();
  }, [openConversationId, loadFirstPage]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, open ? STORED_OPEN : STORED_CLOSED);
    } catch {
      // che do rieng tu co the chan localStorage — bo qua, khong lam vo app
    }
  }, [open]);

  /** `next_cursor === null` nghia la HET; khong goi them mot lan nao. */
  const loadMore = useCallback(async () => {
    if (cursor === null || loading) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const page = await api.danhSachHoiThoai(cursor);
      applyItems((previous) => mergePages(previous, page.items));
      setCursor(page.next_cursor);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [applyItems, cursor, loading]);

  const togglePin = useCallback(
    async (item: HoiThoaiRa) => {
      setBusyId(item.id);
      setError(null);
      try {
        const detail = await api.suaHoiThoai(item.id, { pinned: !item.pinned });
        applyItems((previous) => mergePages(previous, [metaOf(detail)]));
      } catch (e) {
        setError(errorText(e));
      } finally {
        setBusyId(null);
      }
    },
    [applyItems],
  );

  const submitRename = useCallback(async () => {
    if (renaming === null) {
      return;
    }
    const { id, draft } = renaming;
    const trimmed = draft.trim();
    setBusyId(id);
    setError(null);
    try {
      // Rong ⇒ `null`, tuc XOA tieu de. `""` va `null` la hai thu khac nhau o
      // phia server, va mot tieu de rong chi de lai mot hang khong doc duoc.
      const detail = await api.suaHoiThoai(id, { title: trimmed === "" ? null : trimmed });
      applyItems((previous) => mergePages(previous, [metaOf(detail)]));
      setRenaming(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusyId(null);
    }
  }, [applyItems, renaming]);

  const remove = useCallback(
    async (id: string) => {
      setBusyId(id);
      setError(null);
      try {
        await api.xoaHoiThoai(id);
        // Bo khoi danh sach NGAY, khong doi mot lan `GET /conversations` nua:
        // server da xac nhan bang `204`, va mot vong mang thu hai chi de lam
        // bien mat mot hang la mot khoang thoi gian nguoi dung nhin thay.
        applyItems((previous) => previous.filter((item) => item.id !== id));
        setConfirming(null);
        if (id === openConversationId) {
          onOpenConversationDeleted();
        }
      } catch (e) {
        setError(errorText(e));
      } finally {
        setBusyId(null);
      }
    },
    [applyItems, onOpenConversationDeleted, openConversationId],
  );

  const visible = useMemo(
    () => items.filter((item) => matchesQuery(item, query)),
    [items, query],
  );

  if (!open) {
    return (
      <nav
        aria-label={t("sidebar.tieuDe")}
        className="flex shrink-0 flex-col border-r border-border bg-surface-sidebar p-2"
      >
        <button
          type="button"
          aria-expanded={false}
          aria-label={t("sidebar.mo")}
          onClick={() => setOpen(true)}
          className="motion-control min-h-touch min-w-touch rounded-md text-base text-foreground hover:bg-surface-hover"
        >
          <span aria-hidden="true">›</span>
        </button>
      </nav>
    );
  }

  return (
    <nav
      aria-label={t("sidebar.tieuDe")}
      className="flex w-sidebar shrink-0 flex-col border-r border-border bg-surface-sidebar"
    >
      <div className="flex items-center justify-between gap-2 border-b border-border p-2">
        <h2 className="px-1 text-lg font-medium">{t("sidebar.tieuDe")}</h2>
        <button
          type="button"
          aria-expanded={true}
          aria-label={t("sidebar.dong")}
          onClick={() => setOpen(false)}
          className="motion-control min-h-touch min-w-touch rounded-md text-base text-foreground hover:bg-surface-hover"
        >
          <span aria-hidden="true">‹</span>
        </button>
      </div>

      <div className="flex flex-col gap-1 border-b border-border p-2">
        <label htmlFor={searchId} className="text-xs text-muted">
          {t("sidebar.timKiem")}
        </label>
        <input
          id={searchId}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="motion-control min-h-touch rounded-md border border-border-strong bg-background px-2 text-base text-foreground"
        />
        <p className="text-xs text-muted">{t("sidebar.timKiemGhiChu")}</p>
      </div>

      {error !== null && (
        <p className="border-b border-border px-2 py-2 text-xs text-danger-text">{error}</p>
      )}

      <ul className="flex-1 overflow-y-auto">
        {visible.map((item) => (
          <ConversationRow
            key={item.id}
            item={item}
            selected={item.id === openConversationId}
            busy={busyId === item.id}
            renamingDraft={renaming?.id === item.id ? renaming.draft : null}
            confirmingDelete={confirming === item.id}
            onSelect={() => onSelect(item.id)}
            onTogglePin={() => void togglePin(item)}
            onStartRename={() => setRenaming({ id: item.id, draft: item.title ?? "" })}
            onChangeRenameDraft={(draft) => setRenaming({ id: item.id, draft })}
            onSubmitRename={() => void submitRename()}
            onCancelRename={() => setRenaming(null)}
            onAskDelete={() => setConfirming(item.id)}
            onCancelDelete={() => setConfirming(null)}
            onConfirmDelete={() => void remove(item.id)}
          />
        ))}
      </ul>

      <div className="flex flex-col gap-2 border-t border-border p-2">
        {items.length === 0 && !loading && (
          <p className="text-xs text-muted">{t("sidebar.trong")}</p>
        )}
        {items.length > 0 && visible.length === 0 && (
          <p className="text-xs text-muted">{t("sidebar.khongCoKetQua")}</p>
        )}
        <p className="text-xs text-muted">{t("sidebar.ghimGhiChu")}</p>
        {loading && <p className="text-xs text-muted">{t("sidebar.dangTai")}</p>}
        {cursor === null ? (
          items.length > 0 && <p className="text-xs text-muted">{t("sidebar.hetDuLieu")}</p>
        ) : (
          <button
            type="button"
            disabled={loading}
            onClick={() => void loadMore()}
            className="motion-control min-h-touch rounded-md border border-border px-3 text-base text-foreground hover:bg-surface-hover disabled:opacity-50"
          >
            {t("sidebar.taiThem")}
          </button>
        )}
      </div>
    </nav>
  );
}

interface ConversationRowProps {
  item: HoiThoaiRa;
  selected: boolean;
  busy: boolean;
  /** `null` = hang nay khong o che do doi ten. */
  renamingDraft: string | null;
  confirmingDelete: boolean;
  onSelect: () => void;
  onTogglePin: () => void;
  onStartRename: () => void;
  onChangeRenameDraft: (draft: string) => void;
  onSubmitRename: () => void;
  onCancelRename: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

/**
 * Mot hang cua sidebar.
 *
 * Nut chon hoi thoai va ba nut thao tac la ANH EM chu khong long nhau: mot
 * `<button>` trong mot `<button>` la HTML khong hop le, va trinh duyet se tu
 * tach chung ra theo cach khong ai doan duoc.
 */
function ConversationRow({
  item,
  selected,
  busy,
  renamingDraft,
  confirmingDelete,
  onSelect,
  onTogglePin,
  onStartRename,
  onChangeRenameDraft,
  onSubmitRename,
  onCancelRename,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: ConversationRowProps) {
  const label = conversationLabel(item);

  return (
    <li
      className={`motion-control border-b border-border px-2 py-1 ${
        selected ? "bg-accent-subtle" : "hover:bg-surface-hover"
      }`}
    >
      {renamingDraft === null ? (
        <button
          type="button"
          onClick={onSelect}
          aria-current={selected ? "page" : undefined}
          className="flex min-h-touch w-full flex-col items-start justify-center gap-0.5 rounded-md px-1 text-left"
        >
          <span className="flex w-full items-center gap-2">
            {item.pinned && (
              <span className="text-2xs font-semibold tracking-wide text-accent-text uppercase">
                {t("sidebar.daGhim")}
              </span>
            )}
            <span className="min-w-0 flex-1 truncate text-base text-foreground">{label}</span>
          </span>
          <span className="text-xs text-muted">
            {new Date(item.updated_at).toLocaleString()}
          </span>
        </button>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmitRename();
          }}
          className="flex flex-col gap-1 py-1"
        >
          <label className="text-xs text-muted">
            {t("sidebar.tenMoi")}
            <input
              autoFocus
              value={renamingDraft}
              onChange={(e) => onChangeRenameDraft(e.target.value)}
              className="motion-control mt-1 min-h-touch w-full rounded-md border border-border-strong bg-background px-2 text-base text-foreground"
            />
          </label>
          <div className="flex gap-1">
            <button
              type="submit"
              disabled={busy}
              className="motion-control min-h-touch rounded-md bg-accent px-3 text-base font-semibold text-accent-foreground hover:bg-accent-hover active:bg-accent-active disabled:opacity-50"
            >
              {t("sidebar.luu")}
            </button>
            <button
              type="button"
              onClick={onCancelRename}
              className="motion-control min-h-touch rounded-md border border-border px-3 text-base text-foreground hover:bg-surface-hover"
            >
              {t("sidebar.thoi")}
            </button>
          </div>
        </form>
      )}

      {confirmingDelete ? (
        <div className="motion-panel flex flex-col gap-1 rounded-md bg-danger-subtle p-2">
          <p className="text-sm font-semibold text-danger-text">{t("sidebar.xacNhanXoa")}</p>
          <p className="text-xs text-muted">{t("sidebar.xoaGhiChu")}</p>
          <div className="flex gap-1">
            <button
              type="button"
              disabled={busy}
              onClick={onConfirmDelete}
              className="motion-control min-h-touch rounded-md bg-danger px-3 text-base font-semibold text-danger-foreground hover:bg-danger-hover disabled:opacity-50"
            >
              {t("sidebar.xoaThat")}
            </button>
            <button
              type="button"
              onClick={onCancelDelete}
              className="motion-control min-h-touch rounded-md border border-border px-3 text-base text-foreground hover:bg-surface-hover"
            >
              {t("sidebar.thoi")}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-1 pb-1">
          <button
            type="button"
            disabled={busy}
            aria-pressed={item.pinned}
            aria-label={`${item.pinned ? t("sidebar.boGhim") : t("sidebar.ghim")} — ${label}`}
            onClick={onTogglePin}
            className="motion-control min-h-touch rounded-md px-2 text-xs text-muted hover:bg-surface-hover disabled:opacity-50"
          >
            {item.pinned ? t("sidebar.boGhim") : t("sidebar.ghim")}
          </button>
          <button
            type="button"
            disabled={busy}
            aria-label={`${t("sidebar.doiTen")} — ${label}`}
            onClick={onStartRename}
            className="motion-control min-h-touch rounded-md px-2 text-xs text-muted hover:bg-surface-hover disabled:opacity-50"
          >
            {t("sidebar.doiTen")}
          </button>
          <button
            type="button"
            disabled={busy}
            aria-label={`${t("sidebar.xoa")} — ${label}`}
            onClick={onAskDelete}
            className="motion-control min-h-touch rounded-md px-2 text-xs text-danger-text hover:bg-surface-hover disabled:opacity-50"
          >
            {t("sidebar.xoa")}
          </button>
        </div>
      )}
    </li>
  );
}
