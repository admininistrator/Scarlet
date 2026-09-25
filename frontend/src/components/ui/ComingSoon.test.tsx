/**
 * `ComingSoon` — T-S.9 (DoD dong 3), §24.2b·S12, NQ-121.
 *
 * Ba loi hua cua nut cho, moi loi hua mot phep do HANH VI:
 *
 *   1. Bam (chuot, Enter, Space) khong goi gi — ke ca mot `onClick` lot vao
 *      bang ep kieu, ke ca khi nut nam trong mot `<form>`.
 *   2. `data-planned` mang dung ID task se gan no.
 *   3. Tooltip dung chu "Sap co", KHONG ghi phase, va TOI DUOC bang ban phim —
 *      ly do cua `aria-disabled` thay vi `disabled` (Cam bay ④).
 */

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { t } from "../../lib/i18n";
import { ComingSoon } from "./ComingSoon";
import { MenuDismissContext } from "./menu";

describe("ComingSoon", () => {
  it("la nut khoa bang aria-disabled, khong phai disabled, va mang data-planned", () => {
    render(<ComingSoon planned="T-8.1" label="Chia sẻ" />);

    const button = screen.getByRole("button", { name: "Chia sẻ" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("data-planned", "T-8.1");
    expect(button).toHaveClass("control-disabled");
  });

  it("nut icon: label thanh ten truy cap, icon nam trong nut", () => {
    render(<ComingSoon planned="T-4.7" label="Đính kèm tệp" icon={<svg data-testid="icon" />} />);

    const button = screen.getByRole("button", { name: "Đính kèm tệp" });
    expect(button).toHaveAttribute("data-planned", "T-4.7");
    expect(button).toContainElement(screen.getByTestId("icon"));
  });

  it("cong tac (T-S.10, 'Tim web'): chu hien ra LA ten truy cap, icon nam canh, aria-pressed=false", () => {
    render(
      <ComingSoon planned="T-6.7" label="Tìm web" icon={<svg data-testid="icon" />} toggle />,
    );

    const button = screen.getByRole("button", { name: "Tìm web" });
    expect(button).toHaveTextContent("Tìm web");
    expect(button).not.toHaveAttribute("aria-label");
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("data-planned", "T-6.7");
    expect(button).toContainElement(screen.getByTestId("icon"));
    expect(button).toHaveClass("control-disabled", "rounded-full");
  });

  it("bam bang chuot va ban phim khong goi gi, khong gui form", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const onSubmit = vi.fn((e: { preventDefault(): void }) => e.preventDefault());
    // Kieu props khong co `onClick`, nen chi lot vao duoc bang ep kieu — dung
    // cach mot nguoi vo tinh se lam.
    const smuggled = { planned: "T-7.9", label: "Chọn skill", onClick } as unknown as Parameters<
      typeof ComingSoon
    >[0];
    render(
      <form onSubmit={onSubmit}>
        <ComingSoon {...smuggled} />
      </form>,
    );

    const button = screen.getByRole("button", { name: "Chọn skill" });
    await user.click(button);
    button.focus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");

    expect(onClick).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("Tab toi duoc nut, va tooltip hien dung chu 'Sap co', khong ghi phase", async () => {
    const user = userEvent.setup();
    render(<ComingSoon planned="T-6.7" label="Tìm web" />);

    await user.tab();
    const button = screen.getByRole("button", { name: "Tìm web" });
    expect(button).toHaveFocus();

    const tooltip = await screen.findByRole("tooltip");
    expect(t("common.comingSoon")).toBe("Sắp có");
    expect(tooltip).toHaveTextContent(/^Sắp có$/);
    expect(tooltip.textContent).not.toContain("T-6.7");
  });

  it("kieu props bat buoc planned va tu choi onClick", () => {
    // Hai dong duoi day do `pnpm typecheck` kiem, khong phai vitest: bo
    // `@ts-expect-error` nao ma dong ay het loi thi tsc do.
    // @ts-expect-error — thieu `planned`
    const missingPlanned = <ComingSoon label="Xuất" />;
    // @ts-expect-error — `onClick` khong co trong kieu props
    const withClick = <ComingSoon planned="T-8.7" label="Xuất" onClick={() => {}} />;
    // @ts-expect-error — cong tac thieu `icon`
    const toggleWithoutIcon = <ComingSoon planned="T-6.7" label="Tìm web" toggle />;
    // @ts-expect-error — muc menu cho thieu `icon`
    const menuItemWithoutIcon = <ComingSoon planned="B-264" label="Ngôn ngữ" menuItem />;
    expect(missingPlanned).toBeTruthy();
    expect(withClick).toBeTruthy();
    expect(toggleWithoutIcon).toBeTruthy();
    expect(menuItemWithoutIcon).toBeTruthy();
  });

  it("T-S.12 muc menu cho: aria-disabled (KHONG disabled cua Radix), data-planned, chon khong dong menu", async () => {
    const user = userEvent.setup();
    const dismiss = vi.fn();
    render(
      // `open` co dinh: jsdom co the ban `window.blur` khi focus vao menu (xem
      // `openMenu` trong `AccountMenu.test.tsx`) va Radix se dong menu.
      <DropdownMenu.Root open onOpenChange={() => {}}>
        <DropdownMenu.Trigger>mo</DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content>
            <MenuDismissContext.Provider value={dismiss}>
              <DropdownMenu.Item>Thật</DropdownMenu.Item>
              <ComingSoon menuItem planned="B-264" label="Ngôn ngữ" icon={<svg data-testid="icon" />} />
            </MenuDismissContext.Provider>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>,
    );

    const item = await screen.findByRole("menuitem", { name: "Ngôn ngữ" });
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(item).toHaveAttribute("data-planned", "B-264");
    expect(item).not.toHaveAttribute("data-disabled");
    expect(item).toHaveClass("control-disabled");
    expect(item).toContainElement(screen.getByTestId("icon"));

    await user.click(item);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(dismiss).not.toHaveBeenCalled();

    // Mui ten toi duoc muc cho (Radix BO QUA muc `disabled`) ⇒ tooltip mo; Esc
    // luc ay goi ham dong menu cua nguoi so huu (`MenuDismissContext`).
    await user.keyboard("{Home}{ArrowDown}");
    expect(item).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent(/^Sắp có$/);
    await user.keyboard("{Escape}");
    expect(dismiss).toHaveBeenCalledTimes(1);
  });
});
