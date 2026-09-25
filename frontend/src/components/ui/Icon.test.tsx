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

import { act, render } from "@testing-library/react";
import type { IconNode } from "lucide";
import { Menu, Settings, X } from "lucide";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ACCOUNT_MENU_NUDGE_PX, REDUCED_MOTION_QUERY } from "../../lib/motion";
import { Icon, NudgeIcon } from "./Icon";

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

/**
 * `NudgeIcon` — T-S.12, menu tai khoan (ban T-HD5-v2 muc 6, NQ-128 a): muc
 * menu giu tieu diem ⇒ icon nhich `ACCOUNT_MENU_NUDGE_PX` theo lo xo gentle,
 * roi muc ⇒ ve 0. Doc `transform` cua vo `<span>` sau tung khung hinh.
 */
describe("NudgeIcon — nhich khi muc menu duoc chon", () => {
  beforeEach(() => {
    stubFrames();
    stubMatchMedia(false);
  });

  function renderItem() {
    const { container } = render(
      <div role="menuitem" tabIndex={-1}>
        <NudgeIcon icon={Settings} size={18} />
      </div>,
    );
    const item = container.querySelector<HTMLElement>('[role="menuitem"]');
    const host = item?.querySelector("span");
    if (!item || !host) {
      throw new Error("khong dung duoc muc menu");
    }
    return { item, host };
  }

  /** `translateX(Npx)` → N; rong → 0. */
  function offsetOf(host: HTMLElement): number {
    const match = /translateX\((-?[\d.e-]+)px\)/.exec(host.style.transform);
    return match === null ? 0 : Number.parseFloat(match[1]);
  }

  /** Chay het lo xo, tra moi vi tri da ve. */
  function runOut(host: HTMLElement): number[] {
    const seen: number[] = [];
    let frames = 0;
    while (step() && frames < MAX_FRAMES) {
      seen.push(offsetOf(host));
      frames++;
    }
    expect(frames).toBeLessThan(MAX_FRAMES);
    return seen;
  }

  it("focus ⇒ nhich dan toi dung 3 px qua nhieu khung; blur ⇒ ve 0", () => {
    const { item, host } = renderItem();
    expect(host.style.transform).toBe("");

    act(() => item.focus());
    const going = runOut(host);
    expect(going.filter((x) => x > 0 && x < ACCOUNT_MENU_NUDGE_PX - 0.5).length).toBeGreaterThan(1);
    expect(host.style.transform).toBe(`translateX(${ACCOUNT_MENU_NUDGE_PX}px)`);

    act(() => item.blur());
    const back = runOut(host);
    expect(back.filter((x) => x > 0.5 && x < ACCOUNT_MENU_NUDGE_PX).length).toBeGreaterThan(1);
    expect(host.style.transform).toBe("");
  });

  it("doi huong giua chung: khong nhay cach, di tiep tu cho dang dung", () => {
    const { item, host } = renderItem();
    act(() => item.focus());
    for (let i = 0; i < 3; i++) {
      step();
    }
    const midway = offsetOf(host);
    expect(midway).toBeGreaterThan(0);
    expect(midway).toBeLessThan(ACCOUNT_MENU_NUDGE_PX);

    act(() => item.blur());
    step();
    // Khung dau sau khi doi huong o GAN cho cu (van toc duoc giu), khong ve 0 mot phat.
    expect(Math.abs(offsetOf(host) - midway)).toBeLessThan(ACCOUNT_MENU_NUDGE_PX / 2);
    runOut(host);
    expect(host.style.transform).toBe("");
  });

  it("matchMedia reduce ⇒ khong nhich, khong xin khung hinh nao", () => {
    stubMatchMedia(true);
    const { item, host } = renderItem();

    act(() => item.focus());
    expect(queue).toHaveLength(0);
    expect(host.style.transform).toBe("");
    act(() => item.blur());
    expect(queue).toHaveLength(0);
  });
});
