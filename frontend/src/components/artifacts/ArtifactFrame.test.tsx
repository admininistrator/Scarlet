/**
 * Khung artifact — T-5.6 (DoD dong 5), T-5.7 (bat tay `postMessage`). jsdom
 * KHONG ap `sandbox` va khong chay script trong iframe: o day dung
 * `MessageEvent` voi `source` tu dat (Cam bay ② T-5.7); hanh vi that do bang
 * `make test-artifact-origin` tren Chromium qua Nginx. T-5.8: watchdog (C32)
 * bang dong ho gia — nhip den tu `ready` (trang khung doc
 * `config/artifact_runtime.json`), khong hang so nao o FE.
 */

import { act, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ARTIFACT_MESSAGE, ARTIFACT_SANDBOX, ArtifactFrame } from "./ArtifactFrame";

const CONTENT = "<p>noi dung 482913</p>";
/** `ready` nhu trang khung that gui: hai nhip C32 cua `artifact_runtime.json`. */
const READY = { type: ARTIFACT_MESSAGE.ready, watchdog: { ping_interval_ms: 2000, timeout_ms: 6000 } };

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

function frame(): HTMLIFrameElement {
  return screen.getByTitle("khung") as HTMLIFrameElement;
}

/** `postMessage` cua `contentWindow` cua iframe hien tai, da spy. */
function spyPost(el: HTMLIFrameElement = frame()) {
  return vi.spyOn(el.contentWindow as Window, "postMessage").mockImplementation(() => {});
}

function send(source: MessageEventSource | null, data: unknown) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source, origin: "null" }));
  });
}

it("sandbox dung chu §14.3 va KHONG co allow-same-origin", () => {
  render(<ArtifactFrame title="khung" kind="html" content={CONTENT} />);
  const sandbox = frame().getAttribute("sandbox");
  expect(sandbox).toBe("allow-scripts allow-popups allow-forms");
  expect(sandbox).toBe(ARTIFACT_SANDBOX);
  expect(sandbox).not.toContain("allow-same-origin");
});

it("src lay tu cau hinh, khong literal", () => {
  vi.stubEnv("VITE_ARTIFACTS_BASE_URL", "https://artifacts.cau-hinh.test");
  render(<ArtifactFrame title="khung" kind="html" content={CONTENT} />);
  expect(frame().getAttribute("src")).toBe("https://artifacts.cau-hinh.test/html");
});

it("render chi gui SAU ready, khong o onload", () => {
  render(<ArtifactFrame title="khung" kind="html" content={CONTENT} />);
  const post = spyPost();
  act(() => {
    frame().dispatchEvent(new Event("load"));
  });
  expect(post).not.toHaveBeenCalled();
  send(frame().contentWindow, READY);
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith({ type: ARTIFACT_MESSAGE.render, kind: "html", content: CONTENT }, "*");
});

it("ready tu source khac ⇒ khong gui render", () => {
  render(
    <>
      <ArtifactFrame title="khung" kind="html" content={CONTENT} />
      <iframe title="la" />
    </>,
  );
  const post = spyPost();
  send(window, READY);
  send((screen.getByTitle("la") as HTMLIFrameElement).contentWindow, READY);
  send(null, READY);
  expect(post).not.toHaveBeenCalled();
});

it("rendered / error tu source la ⇒ bo qua; tu dung khung ⇒ bao len", () => {
  const onResult = vi.fn();
  render(<ArtifactFrame title="khung" kind="html" content={CONTENT} onResult={onResult} />);
  send(window, { type: ARTIFACT_MESSAGE.rendered });
  send(window, { type: ARTIFACT_MESSAGE.error, message: "gia" });
  expect(onResult).not.toHaveBeenCalled();
  send(frame().contentWindow, { type: ARTIFACT_MESSAGE.error, message: "that" });
  send(frame().contentWindow, { type: ARTIFACT_MESSAGE.rendered });
  expect(onResult.mock.calls).toEqual([[{ type: "error", message: "that" }], [{ type: "rendered" }]]);
});

it("noi dung khong nam trong src / name / bat ky thuoc tinh nao", () => {
  render(<ArtifactFrame title="khung" kind="html" content={CONTENT} />);
  expect(frame().getAttribute("src")).toBe(`${import.meta.env.VITE_ARTIFACTS_BASE_URL}/html`);
  expect(frame().getAttribute("name")).toBeNull();
  expect(frame().hasAttribute("srcdoc")).toBe(false);
  expect(frame().outerHTML).not.toContain("482913");
});

it("doi noi dung ⇒ iframe MOI, ready cua khung moi nhan noi dung moi", () => {
  const { rerender } = render(<ArtifactFrame title="khung" kind="html" content={CONTENT} />);
  const old = frame();
  const oldWindow = old.contentWindow;
  rerender(<ArtifactFrame title="khung" kind="html" content="<p>v2</p>" />);
  expect(frame()).not.toBe(old);
  expect(old.isConnected).toBe(false);
  const post = spyPost();
  send(oldWindow, READY);
  expect(post).not.toHaveBeenCalled();
  send(frame().contentWindow, READY);
  expect(post).toHaveBeenCalledWith({ type: ARTIFACT_MESSAGE.render, kind: "html", content: "<p>v2</p>" }, "*");
});

it("StrictMode: mot ready ⇒ mot render; unmount ⇒ so add('message') = so remove", () => {
  const add = vi.spyOn(window, "addEventListener");
  const remove = vi.spyOn(window, "removeEventListener");
  const count = (spy: typeof add | typeof remove) => spy.mock.calls.filter(([type]) => type === "message").length;
  const { rerender, unmount } = render(
    <StrictMode>
      <ArtifactFrame title="khung" kind="html" content={CONTENT} />
    </StrictMode>,
  );
  const post = spyPost();
  send(frame().contentWindow, READY);
  expect(post).toHaveBeenCalledTimes(1);
  rerender(
    <StrictMode>
      <ArtifactFrame title="khung" kind="html" content="<p>v2</p>" />
    </StrictMode>,
  );
  unmount();
  expect(count(add)).toBeGreaterThan(0);
  expect(count(remove)).toBe(count(add));
});

describe("watchdog C32 (T-5.8), dong ho gia", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const tick = (ms: number) =>
    act(() => {
      vi.advanceTimersByTime(ms);
    });
  const pings = (post: ReturnType<typeof spyPost>) =>
    post.mock.calls.filter(([data]) => (data as { type: string }).type === ARTIFACT_MESSAGE.ping).length;

  it("W1. tra loi deu ⇒ khong huy: 10 nhip, moi nhip mot ping, moi ping mot alive", () => {
    const onResult = vi.fn();
    render(<ArtifactFrame title="khung" kind="react" content={CONTENT} onResult={onResult} />);
    const el = frame();
    const post = spyPost(el);
    send(el.contentWindow, READY);
    for (let i = 1; i <= 10; i++) {
      tick(2000);
      expect(pings(post)).toBe(i);
      send(el.contentWindow, { type: ARTIFACT_MESSAGE.alive });
    }
    expect(frame()).toBe(el);
    expect(onResult).not.toHaveBeenCalledWith({ type: "stalled" });
  });

  it("W2. im qua nguong ⇒ go iframe + bao stalled DUNG luc 6000 ms; im 4000 roi tra loi ⇒ dem lai tu dau", () => {
    const onResult = vi.fn();
    render(<ArtifactFrame title="khung" kind="react" content={CONTENT} onResult={onResult} />);
    const el = frame();
    const post = spyPost(el);
    send(el.contentWindow, READY);
    tick(4000);
    send(el.contentWindow, { type: ARTIFACT_MESSAGE.alive });
    tick(4000); // 8000 ms tu ready, nhung moi im 4000
    expect(el.isConnected).toBe(true);
    tick(1999);
    expect(el.isConnected).toBe(true);
    expect(onResult).not.toHaveBeenCalled();
    tick(1);
    expect(el.isConnected).toBe(false);
    expect(screen.queryByTitle("khung")).toBeNull();
    expect(onResult.mock.calls).toEqual([[{ type: "stalled" }]]);
    expect(pings(post)).toBe(4); // 2000, 4000 ⇒ alive ⇒ 6000, 8000; 10000 = huy, khong ping
  });

  it("W3. tra loi muon sau khi huy ⇒ bo qua: khong bao them, khong iframe, khong timer", () => {
    const onResult = vi.fn();
    render(<ArtifactFrame title="khung" kind="react" content={CONTENT} onResult={onResult} />);
    const old = frame().contentWindow;
    spyPost();
    send(old, READY);
    tick(6000);
    send(old, { type: ARTIFACT_MESSAGE.alive });
    send(old, { type: ARTIFACT_MESSAGE.rendered });
    send(old, { type: ARTIFACT_MESSAGE.error, message: "muon" });
    send(old, READY);
    tick(20_000);
    expect(onResult.mock.calls).toEqual([[{ type: "stalled" }]]);
    expect(screen.queryByTitle("khung")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("W4. unmount ⇒ khong con timer; StrictMode ⇒ dung mot interval", () => {
    const { unmount } = render(
      <StrictMode>
        <ArtifactFrame title="khung" kind="mermaid" content="graph TD; A-->B" />
      </StrictMode>,
    );
    spyPost();
    expect(vi.getTimerCount()).toBe(0); // chua `ready` ⇒ chua dem (khung con nap CDN)
    send(frame().contentWindow, READY);
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("W5. nhip doc tu `ready` (cau hinh), khong hang so: 500 / 1500 ⇒ ping o 500, huy o 1500", () => {
    const onResult = vi.fn();
    render(<ArtifactFrame title="khung" kind="html" content={CONTENT} onResult={onResult} />);
    const post = spyPost();
    send(frame().contentWindow, { type: ARTIFACT_MESSAGE.ready, watchdog: { ping_interval_ms: 500, timeout_ms: 1500 } });
    tick(499);
    expect(pings(post)).toBe(0);
    tick(1);
    expect(pings(post)).toBe(1);
    tick(1000);
    expect(onResult.mock.calls).toEqual([[{ type: "stalled" }]]);
  });

  it("W6. ready thieu / hong watchdog ⇒ error, KHONG gui render, khong timer", () => {
    for (const watchdog of [undefined, { ping_interval_ms: 0, timeout_ms: 6000 }, { ping_interval_ms: "2000", timeout_ms: 6000 }]) {
      const onResult = vi.fn();
      const { unmount } = render(<ArtifactFrame title="khung" kind="react" content={CONTENT} onResult={onResult} />);
      const post = spyPost();
      send(frame().contentWindow, { type: ARTIFACT_MESSAGE.ready, watchdog });
      expect(post).not.toHaveBeenCalled();
      expect(onResult.mock.calls).toEqual([[{ type: "error", message: "Khung không gửi nhịp watchdog nên nội dung không được chạy." }]]);
      expect(vi.getTimerCount()).toBe(0);
      unmount();
    }
  });

  it("W7. src theo kind: /react, /mermaid — trang khung chi nap runtime cua kind ay", () => {
    vi.stubEnv("VITE_ARTIFACTS_BASE_URL", "https://artifacts.cau-hinh.test");
    const { rerender } = render(<ArtifactFrame title="khung" kind="react" content={CONTENT} />);
    expect(frame().getAttribute("src")).toBe("https://artifacts.cau-hinh.test/react");
    rerender(<ArtifactFrame title="khung" kind="mermaid" content={CONTENT} />);
    expect(frame().getAttribute("src")).toBe("https://artifacts.cau-hinh.test/mermaid");
  });
});
