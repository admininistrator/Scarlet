import { useSyncExternalStore } from "react";

import { ISLAND_COMPACT_QUERY } from "../../lib/motion";
import { useMediaQuery } from "../../lib/viewport";

/**
 * Neo cua dao dieu huong — T-S.19a, NQ-136.
 *
 * Hai noi doc: dao (ve hinh nao) va `Layout` (neo hai ben thi day noi dung vao
 * `--spacing-island-gap + --spacing-sidebar`). Hai cay khac nhau nen la mot kho
 * ngoai React (`useSyncExternalStore`), cung loi `sidebarOpen.ts` cu.
 *
 * Luu `localStorage` — tien ich tung may. Doc/ghi hong (che do rieng tu) ⇒ neo
 * van doi trong phien nay, giu o bien nho. Kho doc `localStorage` o MOI lan lay
 * anh chup chu khong chep mot lan luc nap module: test dat neo truoc khi render
 * khong phai dat lai kho.
 */

export type Anchor = "top" | "left" | "right";

export const ANCHOR_STORAGE_KEY = "island.anchor";

/** Chi dung khi `localStorage` nem. */
let fallback: Anchor = "top";
const listeners = new Set<() => void>();

function snapshot(): Anchor {
  try {
    const saved = localStorage.getItem(ANCHOR_STORAGE_KEY);
    return saved === "left" || saved === "right" ? saved : "top";
  } catch {
    return fallback;
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setIslandAnchor(next: Anchor): void {
  try {
    localStorage.setItem(ANCHOR_STORAGE_KEY, next);
  } catch {
    // che do rieng tu co the chan localStorage — `fallback` giu neo cho phien nay
    fallback = next;
  }
  for (const listener of listeners) {
    listener();
  }
}

/**
 * T-5.5 (ban T-HD6 ⑦) — be ngang panel artifact dang chiem o mep phai, px (0 khi
 * dong hoac phu kin). Neo tren can giua COT CHAT chu khong giua cua so: panel
 * 560 + thanh dao 640 can giua 1440 la de len panel 160 px. Khong listener:
 * `useIslandPhysics` doc moi khung hinh, panel ghi khi doi.
 */
let rightInset = 0;
export const islandRightInset = (): number => rightInset;
export function setIslandRightInset(px: number): void {
  rightInset = px;
}

/** Neo HIEU LUC: < 640 px luon "top"; neo hai ben da luu duoc giu cho man rong. */
export function useIslandAnchor(): Anchor {
  const stored = useSyncExternalStore(subscribe, snapshot, () => "top" as const);
  const compact = useMediaQuery(ISLAND_COMPACT_QUERY);
  return compact ? "top" : stored;
}
