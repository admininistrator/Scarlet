/**
 * Hai thanh phan DUNG SAN, CHUA MOUNT cua o nhap — T-S.10, §7b.2.
 *
 * Chua co du lieu that (P4), nen do bang fixture: hinh dang, `data-planned`,
 * ten tep di vao nhu CHU, nut xoa goi dung id, va tooltip ly do cua trang
 * thai "model khong doc duoc anh" toi duoc bang ban phim.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AttachButtonNoVision, AttachmentPreviews, formatBytes, type PendingAttachment } from "./Attachments";

const ITEMS: PendingAttachment[] = [
  { id: "img-1", kind: "image", name: "anh-chup.png", bytes: 180_000 },
  { id: "pdf-1", kind: "file", name: "bao-cao-chi-phi-quy-3-2026.pdf", bytes: 2_516_582 },
];

describe("AttachmentPreviews (T-4.7, dung san)", () => {
  it("1. mot anh + mot tep: data-planned, ten, dung luong theo locale", () => {
    render(<AttachmentPreviews items={ITEMS} onRemove={vi.fn()} />);

    const previews = screen.getByRole("list", { name: "Tệp đính kèm" });
    expect(previews).toHaveAttribute("data-planned", "T-4.7");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("bao-cao-chi-phi-quy-3-2026.pdf")).toHaveClass("truncate");
    expect(screen.getByText("2,4 MB")).toBeInTheDocument();
  });

  it("2. nut xoa: vung cham 44 px, goi `onRemove` voi DUNG id", async () => {
    const onRemove = vi.fn();
    render(<AttachmentPreviews items={ITEMS} onRemove={onRemove} />);

    const removeImage = screen.getByRole("button", { name: "Xoá tệp đính kèm — anh-chup.png" });
    expect(removeImage).toHaveClass("size-touch");
    await userEvent.click(removeImage);
    await userEvent.click(
      screen.getByRole("button", { name: "Xoá tệp đính kèm — bao-cao-chi-phi-quy-3-2026.pdf" }),
    );

    expect(onRemove.mock.calls).toEqual([["img-1"], ["pdf-1"]]);
  });

  it("3. ten tep la CHU, khong bao gio la HTML", () => {
    render(
      <AttachmentPreviews
        items={[{ id: "x", kind: "file", name: '<img src=x onerror="alert(1)">.pdf', bytes: 10 }]}
        onRemove={vi.fn()}
      />,
    );

    expect(screen.getByText('<img src=x onerror="alert(1)">.pdf')).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("4. khay rong ⇒ khong ve gi", () => {
    const { container } = render(<AttachmentPreviews items={[]} onRemove={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("5. `formatBytes` doi don vi theo 1024", () => {
    expect(formatBytes(512)).toBe("512 byte");
    expect(formatBytes(2048)).toBe("2 kB");
    expect(formatBytes(2_516_582)).toBe("2,4 MB");
  });
});

describe("AttachButtonNoVision (T-4.5, ve san — P4 bat)", () => {
  it("6. mo nhu nut cho, tooltip noi LY DO thay cho 'Sap co', toi duoc bang Tab", async () => {
    const user = userEvent.setup();
    render(<AttachButtonNoVision />);

    await user.tab();
    const button = screen.getByRole("button", { name: "Đính kèm ảnh hoặc tệp" });
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute("data-planned", "T-4.5");

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(/^Model này không đọc được ảnh$/);
  });
});
