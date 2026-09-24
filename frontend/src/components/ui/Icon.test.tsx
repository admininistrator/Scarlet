/**
 * `Icon` va `prefers-reduced-motion` — T-S.9 (DoD dong 3 + Ca am), NQ-117.
 *
 * `morphicons` ve moi khung hinh bang `path.setAttribute("d", …)` trong mot
 * vong `requestAnimationFrame` dung chung. File nay thay `requestAnimationFrame`
 * bang mot hang doi tu bam, va nghe `setAttribute` cua chinh `<path>`, nen dem
 * duoc CHINH XAC tung khung hinh icon ve ra:
 *
 *   - "giam"     ⇒ doi icon la MOT lan ghi — dung hinh dich — va khong mot
 *                  khung hinh nao duoc xin.
 *   - "khong giam" (ca doi chung) ⇒ co khung hinh trung gian: hinh khac ca
 *                  hinh dau lan hinh dich. Khong co ca nay thi ca tren co the
 *                  xanh chi vi jsdom khong chay hoat anh nao ca.
 *
 * Ca am cua DoD: bo `reducedMotion="user"` khoi `Icon.tsx` ⇒ ca "giam" do.
 *
 * File nay KHONG import `morphicons`: dong DoD cua cac task sau
 * (`grep "from \"morphicons" … | grep -v components/ui/Icon.tsx` → rong) quet
 * ca test. Hinh chuan cua mot icon lay bang cach dung chinh `Icon` roi doc `d`.
 */

import { render } from "@testing-library/react";
import type { IconNode } from "lucide";
import { Menu, X } from "lucide";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { REDUCED_MOTION_QUERY } from "../../lib/motion";
import { Icon } from "./Icon";

/** Mot khung hinh o 60 Hz, tinh bang giay chia nghin nhu `requestAnimationFrame`. */
const FRAME_STEP = 1000 / 60;
/** Tran so khung hinh cho mot lan bay — lo xo cham nhat trong `SPRINGS` tat trong duoi mot giay. */
const MAX_FRAMES = 600;

let queue: FrameRequestCallback[] = [];
let clock = 0;
let nextId = 1;

function stubFrames(): void {
  queue = [];
  clock = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    queue.push(cb);
    return nextId++;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {
    queue = [];
  });
}

/** Chay mot khung hinh; `false` khi khong ai xin khung hinh nao. */
function step(): boolean {
  const pending = queue;
  queue = [];
  clock += FRAME_STEP;
  pending.forEach((cb) => cb(clock));
  return pending.length > 0;
}

function stubMatchMedia(reduce: boolean): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === REDUCED_MOTION_QUERY ? reduce : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

/** `d` luc nghi cua mot icon — dung mot `Icon` rieng roi doc lai. */
function restingD(icon: IconNode): string {
  const { container, unmount } = render(<Icon icon={icon} spring="sidebarToggle" />);
  const d = container.querySelector("path")?.getAttribute("d") ?? "";
  unmount();
  return d;
}

/** Dung icon `Menu`, doi sang `X`, tra ve moi `d` ma thu vien da ghi. */
function morphMenuToX() {
  const { container, rerender } = render(<Icon icon={Menu} spring="sidebarToggle" />);
  const path = container.querySelector("path");
  if (path === null) {
    throw new Error("Icon khong dung <path>");
  }
  const writes: string[] = [];
  const original = path.setAttribute.bind(path);
  vi.spyOn(path, "setAttribute").mockImplementation((name: string, value: string) => {
    if (name === "d") {
      writes.push(value);
    }
    original(name, value);
  });
  rerender(<Icon icon={X} spring="sidebarToggle" />);
  return { path, writes };
}

describe("Icon — prefers-reduced-motion", () => {
  let menuD = "";
  let xD = "";

  beforeEach(() => {
    stubFrames();
    stubMatchMedia(false);
    menuD = restingD(Menu);
    xD = restingD(X);
    expect(menuD).not.toBe("");
    expect(xD).not.toBe(menuD);
  });

  it("matchMedia reduce ⇒ doi tuc thi, khong co khung hinh trung gian", () => {
    stubMatchMedia(true);
    const { path, writes } = morphMenuToX();

    expect(queue).toHaveLength(0);
    expect(writes).toEqual([xD]);
    expect(path.getAttribute("d")).toBe(xD);

    // Ke ca khi trinh duyet cu chay tiep khung hinh, khong con gi de ve.
    for (let i = 0; i < 10; i++) {
      step();
    }
    expect(writes).toEqual([xD]);
  });

  it("ca doi chung: khong giam ⇒ co khung hinh trung gian, roi dung o hinh dich", () => {
    const { path, writes } = morphMenuToX();

    expect(queue.length).toBeGreaterThan(0);
    let frames = 0;
    while (step() && frames < MAX_FRAMES) {
      frames++;
    }

    const between = writes.filter((d) => d !== menuD && d !== xD);
    expect(between.length).toBeGreaterThan(1);
    expect(frames).toBeLessThan(MAX_FRAMES);
    expect(path.getAttribute("d")).toBe(xD);
  });
});
