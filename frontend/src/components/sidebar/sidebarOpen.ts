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

// ───────────────────── drawer duoi 1024 px — T-3.10 ──────────────────────
//
// Mot trang thai THU HAI, rieng, va KHONG ghi xuong `localStorage`. Lua chon
// "mo" cua desktop la mot cot nam canh man chat, nho qua F5 la dung; mang
// dung lua chon ay sang dien thoai thi moi lan tai trang la mot drawer che
// kin man chat. Nen drawer luon bat dau DONG, va doi be rong giua chung khong
// lam mot ben keo theo ben kia.

let drawerOpen = false;

function getDrawerSnapshot(): boolean {
  return drawerOpen;
}

export function setDrawerOpen(next: boolean): void {
  if (next === drawerOpen) {
    return;
  }
  drawerOpen = next;
  for (const listener of listeners) {
    listener();
  }
}

export function useDrawerOpen(): boolean {
  return useSyncExternalStore(subscribe, getDrawerSnapshot, getDrawerSnapshot);
}

/**
 * `id` cua nut bat/tat o header. Drawer dong thi tieu diem ve DUNG nut nay —
 * khong dua vao "phan tu dang focus luc mo", vi Safari khong focus mot
 * `<button>` khi bam chuot, va luc do tieu diem se roi ve `<body>`.
 */
export const SIDEBAR_TOGGLE_ID = "sidebar-toggle";

/**
 * Doc lai `localStorage` va bao cho moi nguoi nghe — **chi danh cho test**.
 *
 * Store song o tam module nen no song sot qua `cleanup()` giua hai ca test;
 * khong co ham nay thi ca thu hai thua huong lua chon cua ca thu nhat va thu
 * tu chay test quyet dinh ket qua.
 */
export function resetSidebarOpenForTest(): void {
  open = readStored();
  drawerOpen = false;
  for (const listener of listeners) {
    listener();
  }
}
