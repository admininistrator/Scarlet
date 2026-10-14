import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  Download,
  Ellipsis,
  Pencil,
  Pin,
  Search,
  Share2,
  SquarePen,
  Trash2,
} from "lucide";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ApiError, api, type ConversationOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { ComingSoon } from "../ui/ComingSoon";
import { StaticIcon } from "../ui/Icon";
import {
  MENU_ITEM_CLASS,
  MENU_ITEM_DANGER_CLASS,
  MENU_SEPARATOR_CLASS,
  MenuDismissContext,
} from "../ui/menu";
import { groupByDay, useToday } from "./dayGroups";
import { ShareDialog, useShareLink } from "./ShareDialog";
import { useTitleStreams, type TitleView } from "./useTitleStreams";

/**
 * Sidebar hoi thoai — T-3.3 (ban T-HD2), dung lai o T-S.13 theo ban T-HD2-v2
 * (`ShellSidebar`, muc H).
 *
 * KH tham chieu: §18.2, §17.4, §24.2b·S6, S8, S12 · tasks.md T-3.3, T-S.13 ·
 * NQ-112, NQ-129 · CLAUDE.md A3.
 *
 *   [Hoi thoai moi] · [Tim hoi thoai] · Da ghim · Hom nay · Hom qua · d/m/yyyy … · [Tai them]
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  HAI NGUON, MOT DANH SACH                                              ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `GET /conversations?pinned=true` tra MOI hoi thoai ghim trong mot lan (tran
 * `CONVERSATION_PINNED_MAX`, vuot ⇒ `truncated`); `?pinned=false` la phan con
 * lai, phan trang bang `next_cursor` (T-S.8, NQ-112). Ca hai do vao MOT danh
 * sach, chong trung theo `id`, va hai muc tren man hinh CHIA THEO CO `pinned`
 * cua tung hang — khong theo nguon da tra no. Nho vay:
 *
 *   - muc "Da ghim" DU ngay lan nap dau, khong cho "Tai them" — dong Cam bay ①
 *     cua T-3.3 (B-227), va cau `sidebar.pinScopeNote` bo di duoc ma khong noi
 *     sai;
 *   - bo ghim / ghim mot hang doi muc NGAY bang chinh response cua `PATCH`, khong
 *     nap lai (Cam bay ③ cua T-S.13) — hai danh sach, mot thao tac.
 *
 * `truncated` (qua tran) thi nhung hang ghim cu nhat vang mat ca hai nguon, nen
 * man hinh noi ra mot dong duoi "Da ghim" (NQ-129, khong co trong ban ve).
 *
 * ── Hai cau van phai noi ra tren man hinh ─────────────────────────────────
 *
 * **1. Tim kiem chi chay tren PHAN DA TAI** (`sidebar.searchScopeNote`). Muc
 * ghim nay du, nhung phan con lai van phan trang, va khong co endpoint tim toan
 * van (B-09). Ban T-HD2-v2 bo dong nay; T-3.3 bat no phai o tren man hinh —
 * giu lai, bao nguoi thiet ke (NQ-129).
 *
 * **2. "Xoa" la xoa MEM** (`sidebar.deleteNote`). `DELETE` dat `deleted_at`,
 * cay message khong bi dung toi (C12); con so `PURGE_AFTER_DAYS` khong chep
 * vao day — no song trong `.env`, khong endpoint nao tra ra (A3).
 *
 * ── Nhom theo ngay va tieu de chay ─────────────────────────────────────────
 *
 * Nhom: `dayGroups.ts` (gio may, doc lai khi tab lay lai tieu diem). Tieu de
 * chay: `useTitleStreams.ts` (hang `title: null` con trong `STREAM_TTL_S`).
 * Hang dang chay giu nguyen be rong — nut chon hang la `min-w-0 flex-1`, chu
 * nam trong vo `.motion-title` `max-width: 100%` (Cam bay ②): moi `delta` chi
 * doi chu trong o, khong doi hinh hop cua hang nao.
 *
 * ── Trong dao dieu huong (T-S.19a, ban Khung chinh v3) ────────────────────
 *
 * Header 56, cot 256 bat/tat va drawer duoi 1024 px cua v2 da bi go: sidebar
 * nay nay la NOI DUNG cua hinh "sidebar doc" cua dao (neo trai / phai, mo) —
 * cao het lop cua no, khong vien phai (ban `ShellSidebar`). Dao giu no trong
 * DOM o moi hinh (lop an mang `inert`), nen danh sach nap mot lan va
 * `onItemsChange` cap cho thanh mo "6 hoi thoai gan day".
 *
 * ── Con tro phan trang den TU RESPONSE ─────────────────────────────────────
 *
 * `next_cursor` la `updated_at` cua dong cuoi trang `?pinned=false` theo thu
 * tu cua server; danh sach FE da tron them hang ghim nen dong cuoi cua no KHONG
 * phai con tro. Con tro song trong state rieng (`cursor`). Chong trung theo
 * `id` van can: `updated_at` doi moi lan gui tin nhan, nen mot hoi thoai o
 * trang 1 co the tut xuong va trang 2 tra no lan nua (B-228).
 */

/** Ky tu dau dung de cat khi so khop khong dau. */
const DIACRITIC = /\p{Diacritic}/gu;

/**
 * Menu hang hoi thoai (ban T-HD2-v2 H6): dinh menu cach dinh hang 48 = hang 44
 * + 4. Nut "⋯" nam TRONG vien 1 px cua hang, nen tinh tu day nut la 5.
 */
const ROW_MENU_OFFSET = 5;

export interface SidebarProps {
  /** Hoi thoai dang mo o man chat, hoac `null` khi chua mo cai nao. */
  openConversationId: string | null;
  /**
   * T-S.10 — hoi thoai vua ra doi tu man nhap (cau dau da `202`). Doi gia tri
   * ⇒ nap lai trang dau de hang moi hien ra; hang ay `title: null` nen
   * `useTitleStreams` nghe tieu de chay cua no (T-S.13).
   */
  createdConversationId?: string | null;
  /**
   * T-S.13 — `stream_ttl_s` cua `/auth/me` (`STREAM_TTL_S`, NQ-129). `null` /
   * vang mat = chua biet ⇒ chua nghe tieu de chay cua hang nao.
   */
  streamTtlS?: number | null;
  /** Nguoi dung bam mot hang — man chat mo hoi thoai ay. */
  onSelect: (conversationId: string) => void;
  /** Nut "Hoi thoai moi" — T-HD2 dat no trong sidebar, khong o thanh cong cu. */
  onNewChat: () => void;
  /** Hoi thoai **dang mo** vua bi xoa: man chat phai roi khoi no. */
  onOpenConversationDeleted: () => void;
  /**
   * Chan sidebar — T-S.12: khoi tai khoan (`AccountMenu`), ca trong drawer.
   * Nam NGOAI vung dem `p-3` cua danh sach, duong ke tren chay het be rong
   * (ban T-HD2-v2 muc I). Nguoi goi dua vao vi sidebar khong biet phien; phan
   * tu tu dong drawer khi can (xem docstring `AccountMenu`).
   */
  footer?: ReactNode;
  /** T-S.19a — danh sach vua doi (nap, ghim, doi ten, xoa, tieu de chay xong). */
  onItemsChange?: (items: readonly ConversationOut[]) => void;
}

// ───────────────────────────── ham thuan ──────────────────────────────────
//
// Bon ham duoi day khong cham React va khong cham mang, nen chung kiem duoc
// truc tiep — do la ly do chung `export`.

/**
 * Ghim truoc, roi `updated_at` giam dan, roi `id` giam dan.
 *
 * Hai khoa sau chep dung `ORDER BY` cua server (`updated_at DESC, id DESC`) —
 * ca `?pinned=true` lan `?pinned=false` — de hai nguon va cac trang noi vao
 * nhau khong tao ra mot thu tu thu ba. `groupByDay` va muc ghim giu nguyen
 * thu tu mang.
 */
export function sortConversations(items: readonly ConversationOut[]): ConversationOut[] {
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
  current: readonly ConversationOut[],
  incoming: readonly ConversationOut[],
): ConversationOut[] {
  const byId = new Map<string, ConversationOut>();
  for (const item of current) {
    byId.set(item.id, item);
  }
  for (const item of incoming) {
    byId.set(item.id, item);
  }
  return [...byId.values()];
}

/** Tieu de de hien: `null` (chua ai dat ten) co mot cau rieng, khong de trong. */
export function conversationLabel(item: ConversationOut): string {
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
export function matchesQuery(item: ConversationOut, query: string): boolean {
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
function metaOf(detail: ConversationOut): ConversationOut {
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
  createdConversationId = null,
  streamTtlS = null,
  onSelect,
  onNewChat,
  onOpenConversationDeleted,
  footer,
  onItemsChange,
}: SidebarProps) {
  const searchId = useId();
  const today = useToday();

  const [items, setItems] = useState<ConversationOut[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [pinnedTruncated, setPinnedTruncated] = useState(false);
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
  const itemsRef = useRef<ConversationOut[]>([]);
  const applyItems = useCallback((change: (previous: ConversationOut[]) => ConversationOut[]) => {
    const next = sortConversations(change(itemsRef.current));
    itemsRef.current = next;
    setItems(next);
  }, []);

  /** `done` cua stream tieu de: THAY ten cua hang bang chuoi trong DB (B-289). */
  const applyTitle = useCallback(
    (id: string, title: string) => {
      applyItems((previous) =>
        previous.map((item) => (item.id === id ? { ...item, title } : item)),
      );
    },
    [applyItems],
  );
  const titleViews = useTitleStreams(items, streamTtlS, applyTitle);
  useEffect(() => onItemsChange?.(items), [items, onItemsChange]);

  /** Hai nguon cung luc; nap lai = thay CA danh sach (cac trang da tai them roi di). */
  const loadFirstPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pinnedList, firstPage] = await Promise.all([
        api.listConversations({ pinned: true }),
        api.listConversations({ pinned: false }),
      ]);
      applyItems(() => mergePages(pinnedList.items, firstPage.items));
      setCursor(firstPage.next_cursor);
      setPinnedTruncated(pinnedList.truncated === true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [applyItems]);

  /**
   * Nap lan dau luc mount, va nap LAI khi man chat mo mot hoi thoai chua co
   * trong danh sach, hoac bao mot hoi thoai vua ra doi tu man nhap (T-S.10).
   *
   * Bam mot hang **da co** trong danh sach thi khong goi mang: neu goi, moi
   * lan chon mot hoi thoai la mot lan mat cac trang da tai them.
   *
   * Ve man nhap (`openConversationId` → `null`: "Hoi thoai moi", hoac hoi thoai
   * dang mo vua bi xoa) cung KHONG goi mang: §24.2b·S7 noi bam "Hoi thoai moi"
   * la khong mot loi goi API nao, va danh sach khong doi gi.
   */
  const loadedRef = useRef(false);
  const handledCreatedRef = useRef<string | null>(null);
  useEffect(() => {
    const known =
      openConversationId === null ||
      itemsRef.current.some((item) => item.id === openConversationId);
    const justCreated =
      createdConversationId !== null && createdConversationId !== handledCreatedRef.current;
    handledCreatedRef.current = createdConversationId;
    if (loadedRef.current && known && !justCreated) {
      return;
    }
    loadedRef.current = true;
    void loadFirstPage();
  }, [openConversationId, createdConversationId, loadFirstPage]);

  /** `next_cursor === null` nghia la HET; khong goi them mot lan nao. */
  const loadMore = useCallback(async () => {
    if (cursor === null || loading) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const page = await api.listConversations({ pinned: false, updatedBefore: cursor });
      applyItems((previous) => mergePages(previous, page.items));
      setCursor(page.next_cursor);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [applyItems, cursor, loading]);

  /**
   * Response cua `PATCH` mang co `pinned` moi (va `updated_at` moi — cot co
   * `onupdate`), nen hang doi muc ngay trong lan `applyItems` nay (Cam bay ③).
   */
  const togglePin = useCallback(
    async (item: ConversationOut) => {
      setBusyId(item.id);
      setError(null);
      try {
        const detail = await api.updateConversation(item.id, { pinned: !item.pinned });
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
      const detail = await api.updateConversation(id, { title: trimmed === "" ? null : trimmed });
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
        await api.deleteConversation(id);
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
  const dayGroups = useMemo(
    () =>
      groupByDay(
        visible.filter((item) => !item.pinned),
        today,
      ),
    [visible, today],
  );

  const rowProps = (item: ConversationOut): ConversationRowProps => ({
    item,
    titleView: titleViews.get(item.id),
    active: item.id === openConversationId,
    busy: busyId === item.id,
    renamingDraft: renaming?.id === item.id ? renaming.draft : null,
    confirmingDelete: confirming === item.id,
    onSelect: () => onSelect(item.id),
    onTogglePin: () => void togglePin(item),
    onStartRename: () => setRenaming({ id: item.id, draft: item.title ?? "" }),
    onChangeRenameDraft: (draft: string) => setRenaming({ id: item.id, draft }),
    onSubmitRename: () => void submitRename(),
    onCancelRename: () => setRenaming(null),
    onAskDelete: () => setConfirming(item.id),
    onCancelDelete: () => setConfirming(null),
    onConfirmDelete: () => void remove(item.id),
  });

  return (
    <div className="flex h-full flex-col bg-surface-sidebar motion-theme">
      <nav aria-label={t("sidebar.title")} className="flex min-h-0 flex-1 flex-col p-3">
        <button
          type="button"
          onClick={onNewChat}
          className="motion-press flex h-touch w-full shrink-0 items-center justify-center gap-2 rounded-md bg-accent px-3 text-base font-semibold text-accent-foreground hover:bg-accent-hover active:bg-accent-active"
        >
          <StaticIcon icon={SquarePen} size={18} />
          {t("nav.newChat")}
        </button>

        <label htmlFor={searchId} className="mt-3 block shrink-0">
          <span className="sr-only">{t("sidebar.search")}</span>
          <span className="relative block">
            <span className="pointer-events-none absolute top-3.5 left-3 text-muted">
              <StaticIcon icon={Search} size={16} />
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

        <div className="min-h-0 flex-1 overflow-y-auto">
          <ConversationSection
            label={t("sidebar.pinnedGroup")}
            items={pinned}
            rowProps={rowProps}
            note={pinnedTruncated ? t("sidebar.pinnedTruncated") : null}
          />
          {dayGroups.map((group) => (
            <ConversationSection
              key={group.key}
              label={group.label}
              items={group.items}
              rowProps={rowProps}
            />
          ))}

          {items.length === 0 && !loading && (
            <p className="mt-4 px-2 text-xs text-muted">{t("sidebar.empty")}</p>
          )}
          {items.length > 0 && visible.length === 0 && (
            <p className="mt-4 px-2 text-xs text-muted">{t("sidebar.noMatch")}</p>
          )}
          {loading && <p className="mt-2 px-2 text-xs text-muted">{t("sidebar.loading")}</p>}

          {cursor !== null && (
            <button
              type="button"
              disabled={loading}
              onClick={() => void loadMore()}
              className="motion-press control-disabled mt-2 h-touch w-full rounded-md text-base font-medium text-accent-text hover:bg-surface-hover"
            >
              {t("sidebar.loadMore")}
            </button>
          )}
        </div>
      </nav>
      {footer}
    </div>
  );
}

/**
 * Mot muc cua danh sach (ban T-HD2-v2 `ShellSidebar`): nhan chu hoa 11 px,
 * cach khoi tren 16, dem duoi 6; hang cach nhau 2. Muc rong khong ve gi.
 */
function ConversationSection({
  label,
  items,
  rowProps,
  note = null,
}: {
  label: string;
  items: ConversationOut[];
  rowProps: (item: ConversationOut) => ConversationRowProps;
  note?: string | null;
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section>
      {/* `.08em` dung ban T-HD2-v2 `ShellSidebar` (B-310 ⑥, T-S.18). */}
      <h2 className="mt-4 px-2 pb-1.5 text-2xs font-semibold tracking-[0.08em] text-muted uppercase">
        {label}
      </h2>
      <ul className="flex flex-col gap-0.5">
        {items.map((item) => (
          <ConversationRow key={item.id} {...rowProps(item)} />
        ))}
      </ul>
      {note !== null && <p className="mt-1 px-2 text-xs text-muted">{note}</p>}
    </section>
  );
}

interface ConversationRowProps {
  item: ConversationOut;
  /** Tieu de dang/da chay (`useTitleStreams`); vang mat = hang binh thuong. */
  titleView: TitleView | undefined;
  active: boolean;
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
 * Mot hang — ban T-HD2-v2 H1–H6: tieu de · chim ghim 14 · nut "⋯" 44 × 42.
 *
 * Nut chon hoi thoai va nut "⋯" la ANH EM chu khong long nhau: mot `<button>`
 * trong mot `<button>` la HTML khong hop le. Nut chon keo cao het hang
 * (`self-stretch`) — ca hang la vung bam, nhu ban ve.
 *
 * Doi ten va xac nhan xoa **khong** co trong ban ve — chung dung tai cho trong
 * hang vi do la cho nguoi dung dang nhin; hop xac nhan xoa la bat buoc cua Cam
 * bay ③ cua T-3.3.
 */
function ConversationRow({
  item,
  titleView,
  active,
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
              className="motion-press control-disabled h-touch rounded-md bg-accent px-3 text-base font-semibold text-accent-foreground hover:bg-accent-hover active:bg-accent-active"
            >
              {t("sidebar.save")}
            </button>
            <button
              type="button"
              onClick={onCancelRename}
              className="motion-press h-touch rounded-md border border-border px-3 text-base text-foreground hover:bg-surface-hover"
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
              className="motion-press control-disabled h-touch rounded-md bg-danger px-3 text-base font-semibold text-danger-foreground hover:bg-danger-hover"
            >
              {t("sidebar.delete")}
            </button>
            <button
              type="button"
              onClick={onCancelDelete}
              className="motion-press h-touch rounded-md border border-border px-3 text-base text-foreground hover:bg-surface-hover"
            >
              {t("sidebar.cancel")}
            </button>
          </div>
        </div>
      </li>
    );
  }

  // H3: dang cho ten (chua co ten trong danh sach) ⇒ hang `aria-busy`.
  const streaming = titleView?.phase === "streaming" && item.title === null;

  return (
    <li>
      <div
        aria-busy={streaming || undefined}
        className={
          active
            ? "motion-control flex h-touch items-center gap-0.5 rounded-md border border-accent bg-accent-subtle pl-3"
            : "motion-control flex h-touch items-center gap-0.5 rounded-md border border-transparent pl-3 hover:bg-surface-hover has-[[data-state=open]]:bg-surface-hover"
        }
      >
        <button
          type="button"
          onClick={onSelect}
          aria-current={active ? "page" : undefined}
          className={`min-w-0 flex-1 self-stretch truncate text-left text-base text-foreground ${
            active ? "font-semibold" : ""
          }`}
        >
          <RowTitle item={item} view={titleView} label={label} />
        </button>

        {item.pinned && (
          <StaticIcon
            icon={Pin}
            size={14}
            label={t("sidebar.pinned")}
            className="shrink-0 text-muted"
          />
        )}

        <RowMenu
          conversationId={item.id}
          label={label}
          pinned={item.pinned}
          active={active}
          busy={busy}
          onStartRename={onStartRename}
          onTogglePin={onTogglePin}
          onAskDelete={onAskDelete}
        />
      </div>
    </li>
  );
}

/**
 * Chu trong hang (ban T-HD2-v2 H3/H4, T-HD5-v2 muc 3):
 *
 *   - dang chay, chua mot manh ⇒ thanh xam 120 × 10 `motion-pulse` (ten cho
 *     trinh doc man hinh van la "Hoi thoai chua dat ten");
 *   - dang chay, co chu ⇒ vo `.motion-title` (duoi mo 24 px) boc chu
 *     `.motion-none` — chu KHONG co hoat anh tung ky tu;
 *   - ten da ve qua stream ⇒ cung vo, `data-state="done"`: duoi co ve 0;
 *   - khong ten (loi, het han, hoac hang cu) ⇒ "Hoi thoai chua dat ten" mau
 *     `muted` (H4).
 */
function RowTitle({
  item,
  view,
  label,
}: {
  item: ConversationOut;
  view: TitleView | undefined;
  label: string;
}) {
  if (item.title === null && view?.phase === "streaming") {
    if (view.text === "") {
      return (
        <>
          <span aria-hidden="true" className="block h-2.5 w-30 rounded-full bg-surface-code motion-pulse" />
          <span className="sr-only">{label}</span>
        </>
      );
    }
    return (
      <span className="motion-title" data-state="streaming">
        <span className="motion-none">{view.text}</span>
      </span>
    );
  }
  if (item.title === null || item.title.trim() === "") {
    return <span className="text-muted">{label}</span>;
  }
  if (view?.phase === "done") {
    return (
      <span className="motion-title" data-state="done">
        <span className="motion-none">{label}</span>
      </span>
    );
  }
  return <>{label}</>;
}

/**
 * Menu "⋯" cua hang — ban T-HD2-v2 H6: Doi ten · Ghim · Chia se · Xuat* · ── · Xoa.
 *
 * `*` = nut cho (bang §7b.2): `T-8.7` Xuat — `ComingSoon` hinh dang
 * `menuItem`, toi duoc bang mui ten de tooltip "Sap co" mo. Chia se (T-8.2,
 * ban T-HD12) mo `ShareDialog`; POST chay ngay trong `onSelect` (mot lan mo =
 * mot khoa), va menu khong tra tieu diem ve nut "⋯" vi hop thoai giu no.
 *
 * `DropdownMenu` cua Radix (cung primitive menu tai khoan, T-S.12) lo ban
 * phim, Esc, bam ra ngoai. `open` co kiem soat de dua ham dong xuong muc cho
 * qua `MenuDismissContext` — thieu no thi Esc dau chi dong tooltip (B-308 ②).
 *
 * Doi ten / Xoa thay CA HANG bang mot form tai cho, tuc nut "⋯" bi go: Radix
 * se tra tieu diem ve mot nut khong con nua, nen lan dong ay bo buoc tra tieu
 * diem (`keepFocusRef`) — o nhap ten co `autoFocus`.
 */
function RowMenu({
  conversationId,
  label,
  pinned,
  active,
  busy,
  onStartRename,
  onTogglePin,
  onAskDelete,
}: {
  conversationId: string;
  label: string;
  pinned: boolean;
  active: boolean;
  busy: boolean;
  onStartRename: () => void;
  onTogglePin: () => void;
  onAskDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const closeMenu = useCallback(() => setOpen(false), []);
  const keepFocusRef = useRef(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const name = `${t("sidebar.rowMenu")} — ${label}`;
  const share = useShareLink(conversationId);

  return (
    <>
      <DropdownMenu.Root open={open} onOpenChange={setOpen}>
        <DropdownMenu.Trigger
          ref={triggerRef}
          disabled={busy}
          aria-label={name}
          className={`motion-press control-disabled grid h-full w-touch shrink-0 place-items-center rounded-md hover:bg-surface-hover data-[state=open]:bg-surface-panel data-[state=open]:shadow-sm ${
            active ? "text-accent-text" : "text-muted"
          }`}
        >
          <StaticIcon icon={Ellipsis} size={18} />
        </DropdownMenu.Trigger>

        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            sideOffset={ROW_MENU_OFFSET}
            // Radix mac dinh dat ten menu = ten nut (`aria-labelledby`); dat thang.
            aria-labelledby={undefined}
            aria-label={name}
            onCloseAutoFocus={(event) => {
              if (keepFocusRef.current) {
                keepFocusRef.current = false;
                event.preventDefault();
              }
            }}
            className="motion-popover z-50 flex w-50 flex-col rounded-lg border border-border bg-surface-panel p-1.5 shadow-popover"
          >
            <MenuDismissContext.Provider value={closeMenu}>
              <DropdownMenu.Item
                onSelect={() => {
                  keepFocusRef.current = true;
                  onStartRename();
                }}
                className={MENU_ITEM_CLASS}
              >
                <StaticIcon icon={Pencil} size={18} />
                {t("sidebar.rename")}
              </DropdownMenu.Item>
              <DropdownMenu.Item onSelect={onTogglePin} className={MENU_ITEM_CLASS}>
                <StaticIcon icon={Pin} size={18} />
                {pinned ? t("sidebar.unpin") : t("sidebar.pin")}
              </DropdownMenu.Item>
              <DropdownMenu.Item
                onSelect={() => {
                  keepFocusRef.current = true;
                  share.open();
                }}
                className={MENU_ITEM_CLASS}
              >
                <StaticIcon icon={Share2} size={18} />
                {t("sidebar.share")}
              </DropdownMenu.Item>
              <ComingSoon
                menuItem
                planned="T-8.7"
                label={t("sidebar.export")}
                icon={<StaticIcon icon={Download} size={18} />}
              />
              <DropdownMenu.Separator className={MENU_SEPARATOR_CLASS} />
              <DropdownMenu.Item
                onSelect={() => {
                  keepFocusRef.current = true;
                  onAskDelete();
                }}
                className={MENU_ITEM_DANGER_CLASS}
              >
                <StaticIcon icon={Trash2} size={18} />
                {t("sidebar.delete")}
              </DropdownMenu.Item>
            </MenuDismissContext.Provider>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <ShareDialog state={share.state} onClose={share.close} onRetry={share.retry} returnFocusRef={triggerRef} />
    </>
  );
}
