import { ArrowDown } from "lucide";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { t } from "../../lib/i18n";
import { StaticIcon } from "../ui/Icon";

/**
 * Luong chat v3 — T-S.19a, ban Tin nhan v3 (`ChatStream.tsx`). Khong bong bong,
 * nen nhip va vi tri thay cho khung:
 *
 *   - Trong mot luot (cau hoi → cau tra loi): `gap-6` = 24.
 *   - Giua hai luot (cau tra loi → cau hoi ke): `pt-turn` = 40 tren `<li>` cua
 *     cau hoi, CONG `gap-6` — 64, dung class cua ma kem (NQ-135 ①; canvas 3j
 *     ghi 40).
 *   - Dem tren `pt-island-clear` = 88: tin dau khong nam duoi dao.
 *   - Nut "Ve tin moi nhat": hien khi cach day > 1 man; cham accent khi co chu
 *     moi dang chay phia duoi. Bam = cuon ve day va bam day lai.
 *
 * `MessageItem` giu phan than tin nhan; file nay chi lo luong. Nut nam ngay
 * tren mep tren cua o nhap (`Composer` la anh em ngay duoi khung nay), cach
 * `--spacing-jump-gap`.
 */

export type StreamItem = { id: string; role: string; node: ReactNode };

export function ChatStream({ items, streaming }: { items: StreamItem[]; streaming: boolean }) {
  const scrollRef = useRef<HTMLElement>(null);
  const [farFromEnd, setFarFromEnd] = useState(false);
  const [newBelow, setNewBelow] = useState(false);
  const stuck = useRef(true); // dang bam day: chu moi den thi tu cuon theo

  const onScroll = () => {
    const box = scrollRef.current;
    if (box === null) {
      return;
    }
    const distance = box.scrollHeight - box.scrollTop - box.clientHeight;
    stuck.current = distance < 8;
    setFarFromEnd(distance > box.clientHeight);
    if (stuck.current) {
      setNewBelow(false);
    }
  };

  useEffect(() => {
    const box = scrollRef.current;
    if (box === null) {
      return;
    }
    if (stuck.current) {
      box.scrollTop = box.scrollHeight;
    } else if (streaming) {
      setNewBelow(true);
    }
  }, [items, streaming]);

  const jump = () => {
    const box = scrollRef.current;
    if (box === null) {
      return;
    }
    stuck.current = true;
    box.scrollTop = box.scrollHeight; // giam chuyen dong: theme.css dat `scroll-behavior: auto`
    setNewBelow(false);
  };

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <main
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-gutter pt-island-clear pb-6 lg:px-gutter-lg"
      >
        <ol aria-label={t("chat.streamLabel")} className="mx-auto flex max-w-measure flex-col gap-6">
          {items.map((item, index) => (
            <li
              key={item.id}
              className={
                item.role === "user" && index > 0 && items[index - 1].role === "assistant"
                  ? "flex flex-col pt-turn"
                  : "flex flex-col"
              }
            >
              {item.node}
            </li>
          ))}
        </ol>
      </main>
      {(farFromEnd || newBelow) && <JumpToLatest onJump={jump} newBelow={newBelow} />}
    </div>
  );
}

function JumpToLatest({ onJump, newBelow }: { onJump: () => void; newBelow: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-jump-gap flex justify-center">
      <button
        type="button"
        data-state="open"
        aria-label={t("chat.jumpToLatest")}
        aria-describedby={newBelow ? "jump-new-below" : undefined}
        onClick={onJump}
        className="motion-jump pointer-events-auto relative grid size-touch place-items-center rounded-full border border-border-strong bg-surface-panel text-foreground shadow-popover hover:bg-surface-hover"
      >
        <StaticIcon icon={ArrowDown} size={18} />
        {newBelow && (
          <>
            <span
              aria-hidden="true"
              className="absolute top-0.5 right-0.5 size-2.5 rounded-full border-2 border-surface-panel bg-accent"
            />
            <span id="jump-new-below" className="sr-only">
              {t("chat.newBelow")}
            </span>
          </>
        )}
      </button>
    </div>
  );
}
