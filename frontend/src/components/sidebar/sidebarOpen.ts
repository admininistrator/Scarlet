import { useSyncExternalStore } from "react";

/**
 * Trang thai an/hien cua sidebar — T-3.3, theo ban T-HD2 giao.
 *
 * KH tham chieu: §23 · tasks.md T-3.3 · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO MOT STORE NHO CHU KHONG PHAI `useState` TRONG `Sidebar`        ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Ban T-HD2 dat nut bat/tat o **header**, khong o trong sidebar, va bang so do
 * cua no noi thang ly do: sidebar dong la **0 px, khong co dai icon** — *"dai
 * icon se nhan doi nut bat/tat cua header ma khong hien duoc tieu de hoi
 * thoai"*. Tuc thu bam va thu bi an nam o hai cay component khac nhau:
 * `app/Layout.tsx` (header) va `components/chat/ChatScreen.tsx` (sidebar).
 *
 * Ba duong noi chung, va vi sao chon duong nay:
 *
 *   1. Day state len `Layout` roi chuyen xuong qua `Outlet context` — nhung
 *      context ay dang mang `Phien` (xem `app/Layout.tsx`), va them mot truong
 *      thu hai vao no bat MOI man hinh (`/admin`, `/dang-nhap`, …) doc mot
 *      thu chi man chat dung toi.
 *   2. Mot React Context rieng — dung duoc, nhung no la mot provider moi boc
 *      ca cay chi de mang mot `boolean`.
 *   3. Mot store ngoai React (duoi day) — `useSyncExternalStore` la dung co
 *      che React sinh ra cho ca nay, va no khong them mot lop JSX nao.
 *
 * ── `localStorage` boc `try/catch`, khong ngoai le ───────────────────────
 *
 * Che do rieng tu nem `SecurityError` ngay o `getItem`. Cung cai bay
 * `ThemeToggle` da ghi tu T-0.10: doc khong duoc ⇒ roi ve **mo**, khong lam vo
 * app. Gia tri trong bo nho (`open`) van la nguon su that cua phien nay, nen
 * nut bat/tat cu chay binh thuong ca khi khong ghi xuong duoc.
 */

const STORAGE_KEY = "scarlet-sidebar";
const STORED_OPEN = "open";
const STORED_CLOSED = "closed";

function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== STORED_CLOSED;
  } catch {
    // che do rieng tu co the chan localStorage — coi nhu chua ai bam gi
    return true;
  }
}

let open = readStored();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** `useSyncExternalStore` so sanh bang `Object.is`, nen phai tra dung boolean. */
function getSnapshot(): boolean {
  return open;
}

export function setSidebarOpen(next: boolean): void {
  if (next === open) {
    return;
  }
  open = next;
  try {
    localStorage.setItem(STORAGE_KEY, next ? STORED_OPEN : STORED_CLOSED);
  } catch {
    // che do rieng tu co the chan localStorage — bo qua, khong lam vo app
  }
  for (const listener of listeners) {
    listener();
  }
}

export function toggleSidebar(): void {
  setSidebarOpen(!open);
}

export function useSidebarOpen(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/**
 * Doc lai `localStorage` va bao cho moi nguoi nghe — **chi danh cho test**.
 *
 * Store song o tam module nen no song sot qua `cleanup()` giua hai ca test;
 * khong co ham nay thi ca thu hai thua huong lua chon cua ca thu nhat va thu
 * tu chay test quyet dinh ket qua.
 */
export function resetSidebarOpenForTest(): void {
  open = readStored();
  for (const listener of listeners) {
    listener();
  }
}
