/**
 * Khung artifact — T-5.6 (DoD dong 5), T-5.7 (bat tay `postMessage`). jsdom
 * KHONG ap `sandbox` va khong chay script trong iframe: o day dung
 * `MessageEvent` voi `source` tu dat (Cam bay ② T-5.7); hanh vi that do bang
 * `make test-artifact-origin` tren Chromium qua Nginx.
 */

import { act, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { ARTIFACT_MESSAGE, ARTIFACT_SANDBOX, ArtifactFrame } from "./ArtifactFrame";

const CONTENT = "<p>noi dung 482913</p>";

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
  expect(frame().getAttribute("src")).toBe("https://artifacts.cau-hinh.test/");
});

it("render chi gui SAU ready, khong o onload", () => {
  render(<ArtifactFrame title="khung" kind="html" content={CONTENT} />);
  const post = spyPost();
  act(() => {
    frame().dispatchEvent(new Event("load"));
  });
  expect(post).not.toHaveBeenCalled();
  send(frame().contentWindow, { type: ARTIFACT_MESSAGE.ready });
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
  send(window, { type: ARTIFACT_MESSAGE.ready });
  send((screen.getByTitle("la") as HTMLIFrameElement).contentWindow, { type: ARTIFACT_MESSAGE.ready });
  send(null, { type: ARTIFACT_MESSAGE.ready });
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
  expect(frame().getAttribute("src")).toBe(`${import.meta.env.VITE_ARTIFACTS_BASE_URL}/`);
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
  send(oldWindow, { type: ARTIFACT_MESSAGE.ready });
  expect(post).not.toHaveBeenCalled();
  send(frame().contentWindow, { type: ARTIFACT_MESSAGE.ready });
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
  send(frame().contentWindow, { type: ARTIFACT_MESSAGE.ready });
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
