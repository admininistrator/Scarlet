import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { PATHS } from "../../app/paths";
import { conversationHref } from "../../features/chat/useChat";
import type { SessionState } from "../../features/auth/useSessionState";
import { ApiError, api, type ConversationOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { AccountMenu } from "../sidebar/AccountMenu";
import { dayGroupOf } from "../sidebar/dayGroups";
import { Sidebar, conversationLabel, mergePages, sortConversations } from "../sidebar/Sidebar";
import { ConversationSearch, type SearchConversation } from "./ConversationSearch";
import { DynamicIsland, type IslandContext, type RecentConversation } from "./DynamicIsland";

/**
 * Noi dao dieu huong vao phien, router va danh sach hoi thoai — T-S.19a.
 *
 * Ban Khung chinh v3 dat Ctrl K / ⌘ K va hop tim "o AppShell, khong o dao":
 * day la cho do. Dung o HAI noi, khong bao gio cung luc:
 *
 *   - `ChatScreen` (`/`): co `chat` — mo hoi thoai, hoi thoai moi, trang thai
 *     ket noi di thang vao `useChat`, khong qua URL;
 *   - `Layout` (`/cai-dat/*`, `/admin`): khong `chat` — chon hoi thoai la sang
 *     `/?c=<id>`, "Hoi thoai moi" la sang `/` (man nhap, §24.2b·S7).
 *
 * Neo cua dao song o `localStorage`, nen doi trang (dao go roi dung lai) van
 * giu neo.
 *
 * `memo`: man chat render lai theo tung manh chu dang chay; dao (ca sidebar
 * ben trong) chi can render lai khi `chat` doi — `ChatScreen` giu `chat` on
 * dinh bang `useMemo`.
 */

export interface ChatBindings {
  activeId: string | null;
  createdId: string | null;
  reconnecting: boolean;
  onSelect: (conversationId: string) => void;
  onNewChat: () => void;
  onDeleted: () => void;
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}

function isUntitled(item: ConversationOut): boolean {
  return (item.title?.trim() ?? "") === "";
}

/**
 * Hop tim: muc ghim + MOI trang `?pinned=false` (T-S.19a — loc o FE, khong
 * endpoint moi). Trang noi tiep theo `next_cursor` cho toi `null`.
 */
async function loadAllConversations(): Promise<ConversationOut[]> {
  const [pinned, first] = await Promise.all([
    api.listConversations({ pinned: true }),
    api.listConversations({ pinned: false }),
  ]);
  let all = mergePages(pinned.items, first.items);
  let cursor = first.next_cursor;
  while (cursor !== null) {
    const page = await api.listConversations({ pinned: false, updatedBefore: cursor });
    all = mergePages(all, page.items);
    cursor = page.next_cursor;
  }
  return sortConversations(all);
}

function toSearchItems(items: readonly ConversationOut[], now: Date): SearchConversation[] {
  return items.map((item) => ({
    id: item.id,
    title: conversationLabel(item),
    pinned: item.pinned,
    untitled: isUntitled(item),
    group: item.pinned ? t("sidebar.pinnedGroup") : dayGroupOf(item.updated_at, now).label,
  }));
}

export const AppIsland = memo(function AppIsland({
  session,
  context,
  chat,
}: {
  session: SessionState;
  context: IslandContext;
  chat?: ChatBindings;
}) {
  const navigate = useNavigate();
  const [items, setItems] = useState<readonly ConversationOut[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchItems, setSearchItems] = useState<SearchConversation[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const returnFocus = useRef<Element | null>(null);
  const openSearch = useCallback(() => {
    returnFocus.current = document.activeElement;
    setSearchOpen(true);
  }, []);
  /*
    Dong hop tim ⇒ tieu diem ve cho da mo. Cho ay nam trong lop dao vua thu lai
    (`inert`) hoac da bien mat (doi trang) ⇒ ve nut mo dao (ban ve A1 `closeSearch`).
  */
  const restoreFocus = useCallback((event: Event) => {
    event.preventDefault();
    const previous = returnFocus.current;
    returnFocus.current = null;
    const target =
      previous instanceof HTMLElement && previous.isConnected && previous.closest("[inert]") === null
        ? previous
        : [...document.querySelectorAll<HTMLElement>("[data-island-trigger]")].find((el) => el.closest("[inert]") === null);
    target?.focus({ preventScroll: true });
  }, []);

  const onItemsChange = useCallback((next: readonly ConversationOut[]) => setItems(next), []);

  // Ctrl K / ⌘ K o moi man da dang nhap co dao.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openSearch();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openSearch]);

  // Nap lai moi lan mo: danh sach co the da doi tu lan truoc.
  useEffect(() => {
    if (!searchOpen) {
      return undefined;
    }
    let cancelled = false;
    setSearchItems(null);
    setSearchError(null);
    loadAllConversations().then(
      (all) => {
        if (!cancelled) {
          setSearchItems(toSearchItems(all, new Date()));
        }
      },
      (error: unknown) => {
        if (!cancelled) {
          setSearchError(errorText(error));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [searchOpen]);

  // 6 hoi thoai gan nhat theo `updated_at` — ghim KHONG noi len dau (ban ve A1).
  const recent = useMemo<RecentConversation[]>(
    () =>
      [...items]
        .sort((a, b) => (a.updated_at === b.updated_at ? 0 : a.updated_at < b.updated_at ? 1 : -1))
        .map((item) => ({ id: item.id, title: conversationLabel(item), pinned: item.pinned, untitled: isUntitled(item) })),
    [items],
  );

  const user = session.user;
  if (user === null) {
    return null;
  }

  const select = chat?.onSelect ?? ((id: string) => navigate(conversationHref(id)));
  const newChat = chat?.onNewChat ?? (() => navigate(PATHS.home));
  const avatarColor = session.profile?.avatar_color ?? null;

  return (
    <>
      <DynamicIsland
        context={context}
        recent={recent}
        activeId={chat?.activeId ?? null}
        isAdmin={user.role === "admin"}
        user={user}
        avatarColor={avatarColor}
        onLogout={session.logout}
        reconnecting={chat?.reconnecting ?? false}
        artifactPanel={context === "chat"}
        onNewChat={newChat}
        onSelect={select}
        onOpenSearch={openSearch}
        sidebar={
          <Sidebar
            openConversationId={chat?.activeId ?? null}
            createdConversationId={chat?.createdId ?? null}
            // T-S.13: cua so nghe tieu de chay (`STREAM_TTL_S`, NQ-129).
            streamTtlS={session.profile?.stream_ttl_s ?? null}
            onSelect={select}
            onNewChat={newChat}
            onOpenConversationDeleted={chat?.onDeleted ?? (() => undefined)}
            onItemsChange={onItemsChange}
            footer={<AccountMenu user={user} avatarColor={avatarColor} onLogout={session.logout} />}
          />
        }
      />
      <ConversationSearch
        open={searchOpen}
        onOpenChange={setSearchOpen}
        conversations={searchItems}
        error={searchError}
        onPick={select}
        onCloseAutoFocus={restoreFocus}
      />
    </>
  );
});
