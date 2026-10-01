/**
 * Luong chat v3 — T-S.19a (ban Tin nhan v3): nhip luot va nut "Ve tin moi nhat".
 *
 * jsdom khong co layout: `scrollHeight` / `clientHeight` duoc DAT tay tren khung
 * cuon de mo ta "cach day hon mot man". So do that (40 / 24 / 12) la DoD Chrome.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ChatStream, type StreamItem } from "./ChatStream";

function items(roles: string[]): StreamItem[] {
  return roles.map((role, i) => ({ id: `m${i}`, role, node: <p>{`${role} ${i}`}</p> }));
}

/** Gia lap layout cua khung cuon: noi dung `content` px, khung `frame` px, dang o `top`. */
function layout(box: HTMLElement, content: number, frame: number, top: number) {
  Object.defineProperty(box, "scrollHeight", { configurable: true, value: content });
  Object.defineProperty(box, "clientHeight", { configurable: true, value: frame });
  // jsdom: `scrollTop` cua phan tu luon 0 — thay bang mot thuoc tinh ghi duoc.
  Object.defineProperty(box, "scrollTop", { configurable: true, writable: true, value: top });
}

describe("ChatStream", () => {
  it("1. `pt-turn` CHI tren cau hoi mo luot moi (sau mot cau tra loi); `gap-6` trong luot; dem tren `pt-island-clear`", () => {
    render(<ChatStream items={items(["user", "assistant", "user", "assistant"])} streaming={false} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((li) => li.classList.contains("pt-turn"))).toEqual([false, false, true, false]);
    expect(screen.getByRole("list")).toHaveClass("gap-6");
    expect(screen.getByRole("main")).toHaveClass("pt-island-clear");
  });

  it("2. cach day > 1 man ⇒ nut Ve tin moi nhat hien; bam ⇒ ve day va nut an", async () => {
    const user = userEvent.setup();
    render(<ChatStream items={items(["user", "assistant"])} streaming={false} />);
    const box = screen.getByRole("main");
    expect(screen.queryByRole("button", { name: "Về tin mới nhất" })).toBeNull();

    layout(box, 3000, 500, 1000); // cach day 1500 > 500
    fireEvent.scroll(box);
    const jump = await screen.findByRole("button", { name: "Về tin mới nhất" });
    expect(jump).not.toHaveAttribute("aria-describedby");

    await user.click(jump);
    expect(box.scrollTop).toBe(3000);
    layout(box, 3000, 500, 2500);
    fireEvent.scroll(box);
    expect(screen.queryByRole("button", { name: "Về tin mới nhất" })).toBeNull();
  });

  it("3. dang stream ma nguoi dung da roi day ⇒ cham 'Co noi dung moi ben duoi'; bam ⇒ bam day lai", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ChatStream items={items(["user", "assistant"])} streaming />);
    const box = screen.getByRole("main");
    layout(box, 2000, 500, 1400); // cach day 100: chua toi 1 man, nhung da roi day
    fireEvent.scroll(box);
    expect(screen.queryByRole("button", { name: "Về tin mới nhất" })).toBeNull();

    rerender(<ChatStream items={items(["user", "assistant", "assistant"])} streaming />);
    const jump = await screen.findByRole("button", { name: "Về tin mới nhất" });
    expect(jump).toHaveAccessibleDescription("Có nội dung mới bên dưới");
    expect(box.scrollTop).toBe(1400); // khong tu cuon khi nguoi dung da roi day

    await user.click(jump);
    expect(screen.queryByRole("button", { name: "Về tin mới nhất" })).toBeNull();
    rerender(<ChatStream items={items(["user", "assistant", "assistant", "assistant"])} streaming />);
    expect(box.scrollTop).toBe(2000); // bam day lai: chu moi keo theo
  });
});
