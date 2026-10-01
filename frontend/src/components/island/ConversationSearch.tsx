import * as Dialog from "@radix-ui/react-dialog";
import { CornerDownLeft, MessageSquare, Pin, Search, SearchX, X } from "lucide";
import { useDeferredValue, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { t } from "../../lib/i18n";
import { StaticIcon } from "../ui/Icon";

/**
 * Hop tim hoi thoai — T-S.19a, ban Khung chinh v3 (`ConversationSearch.tsx`).
 *
 * Mo tu muc "Tim hoi thoai" va nut "Xem tat ca" tren dao, hoac Ctrl K / ⌘ K
 * (`AppIsland`). O nhap trong = toan bo danh sach theo nhom.
 *
 *   - Loc theo tieu de, khong phan biet hoa thuong va dau: "hop" khop "họp".
 *   - combobox + listbox, `aria-activedescendant`: tieu diem luon o o nhap.
 *   - Radix Dialog: bay tieu diem, Esc dong, tra tieu diem ve cho da mo.
 *   - Khong interpolation: so ket qua va chu "ket qua" la hai manh.
 *
 * Danh sach do `AppIsland` nap KHI MO hop: muc ghim + MOI trang
 * `?pinned=false`, loc o FE — khong endpoint moi (T-S.19a). `null` = dang nap.
 */

export type SearchConversation = {
  id: string;
  title: string;
  pinned: boolean;
  untitled?: boolean;
  /** Nhan nhom da dich san: Da ghim, Hom nay, Hom qua hoac `d/m/yyyy`. */
  group: string;
};

/**
 * NFD bo dau + đ → d. Do dai GIU NGUYEN voi chuoi NFC (chi bo dau ket hop
 * U+0300–U+036F), nen chi so khop dung thang tren tieu de goc de to dam. Khac
 * `foldVietnamese` cua `Sidebar` (`\p{Diacritic}` xoa ca `^`, `` ` `` — lech chi so).
 */
export function foldVietnamese(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[đĐ]/g, "d")
    .toLowerCase();
}

type Row = SearchConversation & { index: number; before: string; hit: string; after: string };

export function filterConversations(items: readonly SearchConversation[], query: string) {
  const folded = foldVietnamese(query.trim());
  const groups: { label: string; rows: Row[] }[] = [];
  const flat: Row[] = [];
  for (const item of items) {
    const at = folded ? foldVietnamese(item.title).indexOf(folded) : -1;
    if (folded && at < 0) {
      continue;
    }
    const row: Row = {
      ...item,
      index: flat.length,
      before: at < 0 ? item.title : item.title.slice(0, at),
      hit: at < 0 ? "" : item.title.slice(at, at + folded.length),
      after: at < 0 ? "" : item.title.slice(at + folded.length),
    };
    flat.push(row);
    const last = groups[groups.length - 1];
    if (last !== undefined && last.label === item.group) {
      last.rows.push(row);
    } else {
      groups.push({ label: item.group, rows: [row] });
    }
  }
  return { groups, flat };
}

export function ConversationSearch({
  open,
  onOpenChange,
  conversations,
  error,
  onPick,
  onCloseAutoFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `null` = dang nap. */
  conversations: SearchConversation[] | null;
  error: string | null;
  onPick: (id: string) => void;
  /** Tra tieu diem khi dong (Radix `onCloseAutoFocus`). */
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const deferred = useDeferredValue(query);
  const { groups, flat } = useMemo(
    () => filterConversations(conversations ?? [], deferred),
    [conversations, deferred],
  );
  const current = flat.length > 0 ? Math.min(active, flat.length - 1) : -1;
  const listRef = useRef<HTMLDivElement>(null);
  const baseId = useId();
  const optionId = (index: number) => `${baseId}-option-${index}`;

  useEffect(() => setActive(0), [deferred]);
  useEffect(() => {
    if (!open) {
      setQuery("");
    }
  }, [open]);
  // Giu muc dang chon trong khung nhin — khong dung `scrollIntoView`.
  useEffect(() => {
    const box = listRef.current;
    const item = box?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (box === null || box === undefined || item === null || item === undefined) {
      return;
    }
    const top = item.offsetTop;
    const bottom = top + item.offsetHeight;
    if (top < box.scrollTop) {
      box.scrollTop = top;
    } else if (bottom > box.scrollTop + box.clientHeight) {
      box.scrollTop = bottom - box.clientHeight;
    }
  }, [current]);

  const pick = (row: Row | undefined) => {
    if (row === undefined) {
      return;
    }
    onOpenChange(false);
    onPick(row.id);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (flat.length === 0) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((current + 1) % flat.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((current - 1 + flat.length) % flat.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(flat[current]);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="motion-scrim fixed inset-0 z-60 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          onCloseAutoFocus={onCloseAutoFocus}
          className="motion-panel fixed top-island-gap left-1/2 z-60 flex max-h-[calc(100dvh_-_2*var(--spacing-island-gap))] w-[min(var(--spacing-search),calc(100vw_-_2*var(--spacing-island-gap)))] -translate-x-1/2 flex-col overflow-hidden rounded-xl border border-border bg-surface-panel text-foreground shadow-popover sm:top-search-top sm:max-h-[calc(100dvh_-_var(--spacing-search-top)_-_var(--spacing-island-gap))]"
        >
          <Dialog.Title className="sr-only">{t("sidebar.search")}</Dialog.Title>
          <div className="flex shrink-0 items-center gap-1 border-b border-divider pr-1.5 pl-4">
            <StaticIcon icon={Search} size={18} className="shrink-0 text-muted" />
            <input
              type="text"
              role="combobox"
              aria-expanded="true"
              aria-controls={`${baseId}-list`}
              aria-autocomplete="list"
              aria-activedescendant={current >= 0 ? optionId(current) : undefined}
              aria-label={t("sidebar.search")}
              placeholder={t("search.placeholder")}
              autoComplete="off"
              spellCheck={false}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onKeyDown}
              className="h-search-input min-w-0 flex-1 bg-transparent px-2 text-input text-foreground outline-none placeholder:text-muted focus-visible:shadow-[inset_0_-2px_0_var(--color-ring)]"
            />
            <Dialog.Close
              aria-label={t("a11y.closeDialog")}
              className="motion-control grid size-touch shrink-0 place-items-center rounded-md text-muted hover:bg-surface-hover hover:text-foreground"
            >
              <StaticIcon icon={X} size={18} />
            </Dialog.Close>
          </div>

          <div ref={listRef} className="relative min-h-0 flex-1 overflow-y-auto px-1.5 pt-1 pb-1.5">
            {error !== null ? (
              <p className="px-2.5 py-3 text-sm text-danger-text">{error}</p>
            ) : flat.length > 0 ? (
              <div id={`${baseId}-list`} role="listbox" aria-label={t("nav.chats")}>
                {groups.map((group, groupIndex) => (
                  <div key={group.label} role="group" aria-labelledby={`${baseId}-group-${groupIndex}`}>
                    <div
                      id={`${baseId}-group-${groupIndex}`}
                      className="px-2.5 pt-3 pb-1 text-2xs font-semibold tracking-[0.08em] text-muted uppercase"
                    >
                      {group.label}
                    </div>
                    {group.rows.map((row) => {
                      const selected = row.index === current;
                      return (
                        <div
                          key={row.id}
                          id={optionId(row.index)}
                          role="option"
                          aria-selected={selected}
                          onClick={() => pick(row)}
                          onPointerMove={() => {
                            if (!selected) {
                              setActive(row.index);
                            }
                          }}
                          className={
                            selected
                              ? "flex h-row-search items-center gap-2.5 rounded-md bg-surface-hover px-2.5 text-base"
                              : "flex h-row-search items-center gap-2.5 rounded-md px-2.5 text-base"
                          }
                        >
                          <StaticIcon
                            icon={row.pinned ? Pin : MessageSquare}
                            size={16}
                            className="shrink-0 text-muted"
                          />
                          <span className={row.untitled ? "min-w-0 flex-1 truncate text-muted" : "min-w-0 flex-1 truncate"}>
                            {row.before}
                            {row.hit !== "" && (
                              <mark className="rounded-sm bg-accent-subtle px-px font-semibold text-foreground">
                                {row.hit}
                              </mark>
                            )}
                            {row.after}
                          </span>
                          {/* Dau "Enter mo" chi tren muc dang chon — tin hieu khong dua vao mau nen. */}
                          <StaticIcon
                            icon={CornerDownLeft}
                            size={16}
                            className={selected ? "shrink-0 text-muted" : "shrink-0 text-muted opacity-0"}
                          />
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            ) : conversations !== null ? (
              <div className="flex flex-col items-center gap-2 px-4 pt-9 pb-10 text-center">
                <StaticIcon icon={SearchX} size={28} className="mb-1 text-muted" />
                <p className="text-body font-semibold">{t("search.empty")}</p>
                <p className="max-w-75 text-sm text-muted">{t("search.emptyHint")}</p>
              </div>
            ) : null}
          </div>

          <div className="hidden shrink-0 items-center gap-4.5 border-t border-divider px-4 py-2.5 text-xs text-muted sm:flex">
            <span className="inline-flex items-center gap-1.5">
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd>
              {t("search.keySelect")}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd>Enter</Kbd>
              {t("search.keyOpen")}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd>Esc</Kbd>
              {t("search.keyClose")}
            </span>
          </div>
          <p role="status" className="sr-only">
            <span>{flat.length}</span> <span>{t("search.resultsSuffix")}</span>
          </p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="min-w-5 rounded-sm border border-border-strong px-1.5 text-center font-mono text-2xs text-foreground">
      {children}
    </kbd>
  );
}
