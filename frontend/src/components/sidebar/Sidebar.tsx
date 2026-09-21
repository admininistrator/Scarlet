import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { ApiError, api, type HoiThoaiRa } from "../../lib/api";
import { t } from "../../lib/i18n";
import { MoreIcon, PinIcon, SearchIcon } from "./icons";
import { useSidebarOpen } from "./sidebarOpen";

/**
 * Sidebar hoi thoai — T-3.3, dung theo ban T-HD2 giao (`AppShell.tsx`).
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
 * cau ay phai nam canh o tim (`sidebar.searchScopeNote`).
 *
 * **2. Ghim cung chi noi trong PHAN DA TAI.** Backend sap xep
 * `ORDER BY updated_at DESC, id DESC` — doc duoc o
 * `app/db/repositories/conversations.py`, khong mot chu `pinned` nao. Sidebar
 * tach hai nhom "Da ghim" / "Gan day" theo dung ban T-HD2, tuc mot hoi thoai
 * ghim tu thang truoc nam o trang 3 se **vang mat khoi nhom Da ghim** cho toi
 * khi nguoi dung bam "Tai them". Xem Cam bay ① cua T-3.3 va B-227: nga con
 * lai la them `pinned DESC` vao `ORDER BY` cua backend, va no keo theo mot con
 * tro phan trang khac han — mot thay doi hop dong backend, khong thuoc task nay.
 *
 * **3. "Xoa" la xoa MEM.** `DELETE /conversations/{id}` dat `deleted_at`, cay
 * message ben duoi khong bi dung toi (C12), va ban ghi con nam tren may chu
 * toi luot purge. Chu tren man hinh phai noi dung thu no lam
 * (`sidebar.deleteNote`) — con so ngay cu the (`PURGE_AFTER_DAYS`) khong duoc
 * chep vao day: no la mot han muc song trong `.env` va khong endpoint nao tra
 * no ra cho FE (A3).
 *
 * ── Dong = 0 px, KHONG co dai icon ───────────────────────────────────────
 *
 * Bang so do cua T-HD2 ghi nguyen van: *"An han, khong co dai icon. Dai icon
 * se nhan doi nut bat/tat cua header ma khong hien duoc tieu de hoi thoai.
 * Nut bat/tat 44 × 44 o header luon hien, khong doi cho."* Vi vay component
 * nay tra `null` khi dong, va nut bat/tat song o `app/Layout.tsx` — trang thai
 * di qua `sidebarOpen.ts`.
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
 * `updated_at`; no khong sinh ra ban sao (B-228). Nhung con mot duong khac co
 * that: `updated_at` doi moi lan nguoi dung gui tin nhan, nen mot hoi thoai o
 * trang 1 luc dau co the tut xuong giua hai lan goi, va luc do trang 2 tra ve
 * dung no lan nua. `mergePages()` chong trung theo `id` de DoD *"khong hoi
 * thoai nao xuat hien hai lan sau hai trang"* dung ke ca trong ca ay.
 */

/** Ky tu dau dung de cat khi so khop khong dau. */
const DIACRITIC = /\p{Diacritic}/gu;

export interface SidebarProps {
  /** Hoi thoai dang mo o man chat, hoac `null` khi chua mo cai nao. */
  openConversationId: string | null;
  /** Nguoi dung bam mot hang — man chat mo hoi thoai ay. */
  onSelect: (conversationId: string) => void;
  /** Nut "Hoi thoai moi" — T-HD2 dat no trong sidebar, khong o thanh cong cu. */
  onNewChat: () => void;
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
 * (`pinned`) la phan **chi FE biet** — xem cau 2 o dau file. No van can thiet
 * du man hinh da tach hai nhom: `ConversationGroup` giu nguyen thu tu mang.
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
  return title === "" ? t("sidebar.untitled") : title;
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
  onNewChat,
  onOpenConversationDeleted,
}: SidebarProps) {
  const searchId = useId();
  const open = useSidebarOpen();

  const [items, setItems] = useState<HoiThoaiRa[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [menuFor, setMenuFor] = useState<string | null>(null);
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

  /** Menu "⋯" dong khi bam ra ngoai hoac bam `Esc` — khuon popover thong thuong. */
  useEffect(() => {
    if (menuFor === null) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuFor(null);
      }
    };
    const onPointerDown = () => setMenuFor(null);
    document.addEventListener("keydown", onKeyDown);
    // `click` o pha bong bong: nut mo menu da `stopPropagation` nen lan bam mo
    // khong tu dong lai chinh no.
    document.addEventListener("click", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("click", onPointerDown);
    };
  }, [menuFor]);

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
      setMenuFor(null);
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
  const pinned = visible.filter((item) => item.pinned);
  const recent = visible.filter((item) => !item.pinned);

  // T-HD2: dong = 0 px, KHONG co dai icon. Nut bat/tat o header (`Layout.tsx`).
  if (!open) {
    return null;
  }

  const rowProps = (item: HoiThoaiRa) => ({
    item,
    active: item.id === openConversationId,
    busy: busyId === item.id,
    menuOpen: menuFor === item.id,
    renamingDraft: renaming?.id === item.id ? renaming.draft : null,
    confirmingDelete: confirming === item.id,
    onSelect: () => onSelect(item.id),
    onOpenMenu: () => setMenuFor((current) => (current === item.id ? null : item.id)),
    onTogglePin: () => void togglePin(item),
    onStartRename: () => {
      setMenuFor(null);
      setRenaming({ id: item.id, draft: item.title ?? "" });
    },
    onChangeRenameDraft: (draft: string) => setRenaming({ id: item.id, draft }),
    onSubmitRename: () => void submitRename(),
    onCancelRename: () => setRenaming(null),
    onAskDelete: () => {
      setMenuFor(null);
      setConfirming(item.id);
    },
    onCancelDelete: () => setConfirming(null),
    onConfirmDelete: () => void remove(item.id),
  });

  return (
    <nav
      aria-label={t("sidebar.title")}
      className="flex w-sidebar shrink-0 flex-col border-r border-border bg-surface-sidebar p-3 motion-theme"
    >
      <button
        type="button"
        onClick={onNewChat}
        className="motion-control h-touch w-full shrink-0 rounded-md bg-accent px-3 text-base font-semibold text-accent-foreground hover:bg-accent-hover active:bg-accent-active"
      >
        {t("nav.newChat")}
      </button>

      <label htmlFor={searchId} className="mt-3 block shrink-0">
        <span className="sr-only">{t("sidebar.search")}</span>
        <span className="relative block">
          <span
            aria-hidden="true"
            className="pointer-events-none absolute top-3.5 left-3 text-muted"
          >
            <SearchIcon />
          </span>
          <input
            id={searchId}
            type="search"
            value={query}
            placeholder={t("sidebar.search")}
            onChange={(e) => setQuery(e.target.value)}
            className="motion-control h-touch w-full rounded-md border border-border-strong bg-background pr-3 pl-9 text-base text-foreground placeholder:text-muted"
          />
        </span>
      </label>
      <p className="mt-1 shrink-0 text-xs text-muted">{t("sidebar.searchScopeNote")}</p>

      {error !== null && (
        <p className="mt-2 shrink-0 text-xs text-danger-text">{error}</p>
      )}

      <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
        <ConversationGroup label={t("sidebar.pinnedGroup")} items={pinned} rowProps={rowProps} />
        <ConversationGroup label={t("sidebar.recentGroup")} items={recent} rowProps={rowProps} />

        {items.length === 0 && !loading && (
          <p className="px-2 text-xs text-muted">{t("sidebar.empty")}</p>
        )}
        {items.length > 0 && visible.length === 0 && (
          <p className="px-2 text-xs text-muted">{t("sidebar.noMatch")}</p>
        )}
        {loading && <p className="px-2 text-xs text-muted">{t("sidebar.loading")}</p>}

        {cursor !== null && (
          <button
            type="button"
            disabled={loading}
            onClick={() => void loadMore()}
            className="motion-control mt-2 h-touch w-full rounded-md text-base font-medium text-accent-text hover:bg-surface-hover disabled:opacity-50"
          >
            {t("sidebar.loadMore")}
          </button>
        )}
      </div>

      <p className="mt-2 shrink-0 text-xs text-muted">{t("sidebar.pinScopeNote")}</p>
    </nav>
  );
}

function ConversationGroup({
  label,
  items,
  rowProps,
}: {
  label: string;
  items: HoiThoaiRa[];
  rowProps: (item: HoiThoaiRa) => ConversationRowProps;
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section className="mb-3">
      <h2 className="px-2 pb-1 text-2xs font-semibold tracking-wider text-muted uppercase">
        {label}
      </h2>
      <ul className="flex flex-col gap-0.5">
        {items.map((item) => (
          <ConversationRow key={item.id} {...rowProps(item)} />
        ))}
      </ul>
    </section>
  );
}

interface ConversationRowProps {
  item: HoiThoaiRa;
  active: boolean;
  busy: boolean;
  menuOpen: boolean;
  /** `null` = hang nay khong o che do doi ten. */
  renamingDraft: string | null;
  confirmingDelete: boolean;
  onSelect: () => void;
  onOpenMenu: () => void;
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
 * Mot hang cua sidebar — ban T-HD2: tieu de · chim ghim · nut "⋯".
 *
 * Nut chon hoi thoai va nut "⋯" la ANH EM chu khong long nhau: mot `<button>`
 * trong mot `<button>` la HTML khong hop le, va trinh duyet se tu tach chung
 * ra theo cach khong ai doan duoc.
 *
 * Doi ten va xac nhan xoa **khong** co trong ban ve — T-HD2 chi ve menu. Hai
 * khoi ay dung tai cho trong hang vi do la cho nguoi dung dang nhin; hop xac
 * nhan xoa la bat buoc cua Cam bay ③.
 */
function ConversationRow({
  item,
  active,
  busy,
  menuOpen,
  renamingDraft,
  confirmingDelete,
  onSelect,
  onOpenMenu,
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

  if (renamingDraft !== null) {
    return (
      <li>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmitRename();
          }}
          className="flex flex-col gap-1 py-1"
        >
          <label className="text-xs text-muted">
            {t("sidebar.newName")}
            <input
              autoFocus
              value={renamingDraft}
              onChange={(e) => onChangeRenameDraft(e.target.value)}
              className="motion-control mt-1 h-touch w-full rounded-md border border-border-strong bg-background px-3 text-base text-foreground"
            />
          </label>
          <div className="flex gap-1">
            <button
              type="submit"
              disabled={busy}
              className="motion-control h-touch rounded-md bg-accent px-3 text-base font-semibold text-accent-foreground hover:bg-accent-hover active:bg-accent-active disabled:opacity-50"
            >
              {t("sidebar.save")}
            </button>
            <button
              type="button"
              onClick={onCancelRename}
              className="motion-control h-touch rounded-md border border-border px-3 text-base text-foreground hover:bg-surface-hover"
            >
              {t("sidebar.cancel")}
            </button>
          </div>
        </form>
      </li>
    );
  }

  if (confirmingDelete) {
    return (
      <li>
        <div className="motion-panel flex flex-col gap-1 rounded-md bg-danger-subtle p-2">
          <p className="text-sm font-semibold text-danger-text">{t("sidebar.deleteConfirm")}</p>
          <p className="text-xs text-muted">{t("sidebar.deleteNote")}</p>
          <div className="flex gap-1">
            <button
              type="button"
              disabled={busy}
              onClick={onConfirmDelete}
              className="motion-control h-touch rounded-md bg-danger px-3 text-base font-semibold text-danger-foreground hover:bg-danger-hover disabled:opacity-50"
            >
              {t("sidebar.delete")}
            </button>
            <button
              type="button"
              onClick={onCancelDelete}
              className="motion-control h-touch rounded-md border border-border px-3 text-base text-foreground hover:bg-surface-hover"
            >
              {t("sidebar.cancel")}
            </button>
          </div>
        </div>
      </li>
    );
  }

  return (
    <li className="relative">
      <div
        className={
          active
            ? "motion-control flex h-touch items-center gap-0.5 rounded-md border border-accent bg-accent-subtle pr-1 pl-3"
            : "motion-control flex h-touch items-center gap-0.5 rounded-md border border-transparent pr-1 pl-3 hover:bg-surface-hover"
        }
      >
        <button
          type="button"
          onClick={onSelect}
          aria-current={active ? "page" : undefined}
          className={
            active
              ? "min-w-0 flex-1 truncate text-left text-base font-semibold text-foreground"
              : "min-w-0 flex-1 truncate text-left text-base text-foreground"
          }
        >
          {label}
        </button>

        {item.pinned && (
          <span className="grid w-5 shrink-0 place-items-center text-muted">
            <PinIcon />
            <span className="sr-only">{t("sidebar.pinned")}</span>
          </span>
        )}

        <button
          type="button"
          disabled={busy}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={`${t("sidebar.rowMenu")} — ${label}`}
          onClick={(e) => {
            // Khong de lan bam nay chay toi `document` — no se dong menu vua mo.
            e.stopPropagation();
            onOpenMenu();
          }}
          className={
            active
              ? "motion-control grid size-touch shrink-0 place-items-center rounded-md text-accent-text hover:bg-surface-hover disabled:opacity-50"
              : "motion-control grid size-touch shrink-0 place-items-center rounded-md text-muted hover:bg-surface-hover disabled:opacity-50"
          }
        >
          <MoreIcon />
        </button>
      </div>

      {menuOpen && (
        <div
          role="menu"
          aria-label={`${t("sidebar.rowMenu")} — ${label}`}
          onClick={(e) => e.stopPropagation()}
          className="motion-popover absolute top-12 right-0 z-10 w-46 rounded-lg border border-border bg-surface-panel p-1 shadow-popover"
        >
          <button
            type="button"
            role="menuitem"
            onClick={onStartRename}
            className="motion-control flex h-touch w-full items-center rounded-md px-3 text-left text-base text-foreground hover:bg-surface-hover"
          >
            {t("sidebar.rename")}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={onTogglePin}
            className="motion-control flex h-touch w-full items-center rounded-md px-3 text-left text-base text-foreground hover:bg-surface-hover"
          >
            {item.pinned ? t("sidebar.unpin") : t("sidebar.pin")}
          </button>
          <div className="mx-2 my-1 h-px bg-border" />
          <button
            type="button"
            role="menuitem"
            onClick={onAskDelete}
            className="motion-control flex h-touch w-full items-center rounded-md px-3 text-left text-base text-danger-text hover:bg-surface-hover"
          >
            {t("sidebar.delete")}
          </button>
        </div>
      )}
    </li>
  );
}
