/**
 * Khung artifact — T-5.6 (DoD dong 5). jsdom KHONG ap `sandbox` va khong chay
 * script trong iframe: day chi khoa CHUOI thuoc tinh; hanh vi that do bang
 * `make test-artifact-origin` tren Chromium qua Nginx.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ARTIFACT_SANDBOX, ArtifactFrame } from "./ArtifactFrame";

afterEach(() => {
  vi.unstubAllEnvs();
});

it("sandbox dung chu §14.3 va KHONG co allow-same-origin", () => {
  render(<ArtifactFrame title="khung" />);
  const sandbox = screen.getByTitle("khung").getAttribute("sandbox");
  expect(sandbox).toBe("allow-scripts allow-popups allow-forms");
  expect(sandbox).toBe(ARTIFACT_SANDBOX);
  expect(sandbox).not.toContain("allow-same-origin");
});

it("src lay tu cau hinh, khong literal", () => {
  vi.stubEnv("VITE_ARTIFACTS_BASE_URL", "https://artifacts.cau-hinh.test");
  render(<ArtifactFrame title="khung" />);
  expect(screen.getByTitle("khung").getAttribute("src")).toBe("https://artifacts.cau-hinh.test/");
});
