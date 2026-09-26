import { useCallback, useEffect, useRef, useState } from "react";

import { api, type ConversationOut } from "../../lib/api";
import { openStream, type StreamHandle, type TitleStreamEvent } from "../../lib/sse";

/**
 * Tieu de chay trong sidebar — T-S.13, §24.2b·S6 + S8, ban T-HD2-v2 H3/H4 va
 * T-HD5-v2 muc 3.
 *
 * KH tham chieu: §24.2b·S6, S8 · tasks.md T-S.13 · B-287, B-289 · NQ-110,
 * NQ-129.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  NGHE HANG NAO: `title: null` VA `updated_at` CON TRONG STREAM_TTL_S    ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Job `title` chay o cau DAU cua mot hoi thoai chua co ten (T-S.7) va ghi vao
 * `stream:title:{id}`, khoa song `STREAM_TTL_S` sau `start` (§7.2). Moc
 * `updated_at` cua hang >= luc cau dau duoc ghi, nen "con trong cua so" doc
 * tu `updated_at` khong bao gio bo sot mot stream con song — va mot hang da
 * qua cua so thi chac chan khong con gi de nghe. Mot luat cho ca hai duong:
 *
 *   - hang VUA TAO tu man nhap (T-S.10 bao `createdConversationId` sau `202`
 *     ⇒ sidebar nap lai ⇒ hang moi `title: null`, `updated_at` = vua xong);
 *   - F5 giua luc dang dat ten — hang van `null`, van trong cua so, nghe tiep
 *     (consumer phat lai `start` + moi `delta`, §7.3).
 *
 * `STREAM_TTL_S` den tu `/auth/me` (`stream_ttl_s`, NQ-129) — `null` khi chua
 * hoi xong ⇒ chua nghe hang nao (A3: khong chep `3600`).
 *
 * ── Ba cach mot hang thoi nghe ───────────────────────────────────────────
 *
 *   `done`   ⇒ `onTitle(id, title)`: `title` la chuoi DANG NAM TRONG DB (co
 *              the la ten nguoi dung tu dat giua chung, B-289) — THAY chu da
 *              chay, khong noi them.
 *   `error`  ⇒ "Hoi thoai chua dat ten" (§24.2b·S6 "Hong"; ca `JOB_LOST`).
 *   het han  ⇒ cung vay, dung luc `updated_at + stream_ttl_s` (NQ-129): khoa
 *              stream da het song, khong event ket thuc nao con toi duoc —
 *              ca worker chet giua luot dat ten (B-287) dung o day.
 *
 * Mot hang da ket (ba ca tren) KHONG mo lai trong doi component: nap lai danh
 * sach tra ve dung hang `null` ay thi mo lai chi de nghe lai `error`.
 *
 * Hang CO TEN giua luc dang nghe (doi ten tay, nap lai danh sach) ⇒ dong
 * stream va bo trang thai chay — ten trong danh sach thang.
 */

/**
 * Trang thai hien thi cua mot hang dang/da nghe:
 *   - `streaming` — `text` rong ⇒ thanh xam `motion-pulse` (H3 khung 1); co
 *     chu ⇒ `.motion-title` duoi mo (khung 2);
 *   - `done` — ten da ve; hang giu vo `.motion-title` voi `data-state="done"`
 *     de duoi mo co ve 0 (T-HD5-v2 muc 3), chu lay tu danh sach.
 */
export type TitleView = { phase: "streaming"; text: string } | { phase: "done" };

interface Listener {
  handle: StreamHandle;
  expiry: number;
}

/** Moc (ms) ma hang thoi co gi de nghe — `null` = hang nay khong nghe. */
export function titleDeadline(item: ConversationOut, streamTtlS: number): number | null {
  if (item.title !== null) {
    return null;
  }
  return Date.parse(item.updated_at) + streamTtlS * 1000;
}

export function useTitleStreams(
  items: readonly ConversationOut[],
  streamTtlS: number | null,
  onTitle: (conversationId: string, title: string) => void,
): ReadonlyMap<string, TitleView> {
  const [views, setViews] = useState<ReadonlyMap<string, TitleView>>(() => new Map());
  const listenersRef = useRef(new Map<string, Listener>());
  const settledRef = useRef(new Set<string>());
  // Ham cua nguoi goi doi moi lan render; stream mo mot lan va doc ban MOI NHAT.
  const onTitleRef = useRef(onTitle);
  useEffect(() => {
    onTitleRef.current = onTitle;
  }, [onTitle]);

  const setView = useCallback((id: string, view: TitleView | null) => {
    setViews((previous) => {
      if (view === null && !previous.has(id)) {
        return previous;
      }
      const next = new Map(previous);
      if (view === null) {
        next.delete(id);
      } else {
        next.set(id, view);
      }
      return next;
    });
  }, []);

  const stop = useCallback((id: string) => {
    const listener = listenersRef.current.get(id);
    if (listener !== undefined) {
      listener.handle.close();
      window.clearTimeout(listener.expiry);
      listenersRef.current.delete(id);
    }
  }, []);

  /** Ket mot hang: thoi nghe, va khong mo lai trong doi component nay. */
  const settle = useCallback(
    (id: string, view: TitleView | null) => {
      stop(id);
      settledRef.current.add(id);
      setView(id, view);
    },
    [setView, stop],
  );

  useEffect(() => {
    const listeners = listenersRef.current;
    const wanted = new Map<string, number>();
    if (streamTtlS !== null) {
      const now = Date.now();
      for (const item of items) {
        const deadline = titleDeadline(item, streamTtlS);
        if (deadline !== null && deadline > now && !settledRef.current.has(item.id)) {
          wanted.set(item.id, deadline);
        }
      }
    }

    // Da co ten, bi xoa, hoac vua het cua so ⇒ thoi nghe, ten trong danh sach thang.
    for (const id of [...listeners.keys()]) {
      if (!wanted.has(id)) {
        stop(id);
        setView(id, null);
      }
    }

    for (const [id, deadline] of wanted) {
      if (listeners.has(id)) {
        continue;
      }
      const handle = openStream<TitleStreamEvent>({
        url: api.titleStreamUrl(id),
        onEvent: (event) => {
          switch (event.event) {
            case "start":
              // §7.4 / `sse.ts` diem 4: `start` = BAT DAU TU DAU (ca lan phat lai).
              setView(id, { phase: "streaming", text: "" });
              break;
            case "delta":
              setViews((previous) => {
                const current = previous.get(id);
                const next = new Map(previous);
                next.set(id, {
                  phase: "streaming",
                  text: (current?.phase === "streaming" ? current.text : "") + event.data.t,
                });
                return next;
              });
              break;
            case "done":
              onTitleRef.current(id, event.data.title);
              settle(id, { phase: "done" });
              break;
            case "error":
              settle(id, null);
              break;
          }
        },
        // Het `MAX_ATTEMPTS` lan noi lai: khong phai "da co ten" — nhu `error`.
        onFatal: () => settle(id, null),
      });
      const expiry = window.setTimeout(() => settle(id, null), deadline - Date.now());
      listeners.set(id, { handle, expiry });
      setView(id, { phase: "streaming", text: "" });
    }
  }, [items, setView, settle, stop, streamTtlS]);

  // Go component (ca lan go gia cua `StrictMode`) ⇒ dong het. Lan gan lai,
  // effect tren chay lai va mo lai dung nhung hang con can nghe.
  useEffect(
    () => () => {
      for (const id of [...listenersRef.current.keys()]) {
        stop(id);
      }
    },
    [stop],
  );

  return views;
}
