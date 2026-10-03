/**
 * T-4.5 (S9) — phia FE cua guard vision: nut dinh kem va khe canh bao.
 *
 * jsdom khong co layout (T-S.19a ②): kiem `aria-disabled` va CHU tooltip;
 * toa do la viec cua Chrome.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ModelOut } from "../../lib/api";
import { CurrentModel } from "../../features/models/CurrentModel";
import { Composer } from "./Composer";

function renderComposer(noVision?: boolean) {
  return render(
    <Composer
      running={false}
      enabled
      maxChars={null}
      onSend={vi.fn()}
      onStop={vi.fn()}
      docked={false}
      noVision={noVision}
    />,
  );
}

describe("nut dinh kem theo `vision` cua model dang chon", () => {
  it("1. khong vision ⇒ aria-disabled, Tab toi ⇒ tooltip `composer.noVision`, KHONG con data-planned", async () => {
    const user = userEvent.setup();
    renderComposer(true);

    const button = screen.getByRole("button", { name: "Đính kèm ảnh hoặc tệp" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toHaveAttribute("data-planned");
    await user.tab(); // o nhap
    await user.tab();
    expect(button).toHaveFocus();

    expect(await screen.findByRole("tooltip")).toHaveTextContent(/^Model này không đọc được ảnh$/);
  });

  it("2. co vision ⇒ nut cua T-4.7 (chua gan hanh vi), khong phai nut 'khong doc duoc anh'", () => {
    renderComposer(false);

    const button = screen.getByRole("button", { name: "Đính kèm ảnh hoặc tệp" });
    expect(button).toHaveAttribute("data-planned", "T-4.7");
  });
});

function model(capabilities: string[]): ModelOut {
  return {
    id: "m",
    display_name: "M",
    provider: "Hang",
    provider_id: "hang",
    capabilities,
    context_window: 1000,
    max_output: 100,
    default: false,
    badge: null,
    available: true,
    unavailable_reason: null,
    reasoning: null,
    pricing: null,
    pricing_mode: "unmetered",
    checked_at: null,
    stale_after_s: 30,
  };
}

function warning(container: HTMLElement): HTMLElement {
  const slot = container.querySelector<HTMLElement>('[data-slot="capability-warning"]');
  expect(slot).not.toBeNull();
  return slot as HTMLElement;
}

describe("khe `capability-warning` cua CurrentModel", () => {
  it("3. model khong vision + hoi thoai co anh ⇒ co chu canh bao", () => {
    const { container } = render(<CurrentModel model={model([])} tier={null} narrow={false} conversationHasImages />);

    expect(warning(container).textContent?.length).toBeGreaterThan(0);
    expect(warning(container)).not.toHaveAttribute("data-planned");
  });

  it.each([
    ["model co vision", ["vision"], true],
    ["hoi thoai khong co anh", [], false],
  ])("4. %s ⇒ khe rong", (_label, capabilities, hasImages) => {
    const { container } = render(
      <CurrentModel model={model(capabilities)} tier={null} narrow={false} conversationHasImages={hasImages} />,
    );

    expect(warning(container).textContent).toBe("");
  });
});
