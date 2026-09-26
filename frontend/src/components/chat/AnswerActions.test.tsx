/**
 * Hang nut duoi cau tra loi — DoD dong 1 cua T-3.7, ban T-HD3-v2 (T-S.15).
 *
 * File nay do HAI tang, va chung tra loi hai cau khac nhau:
 *
 *   `describe("hang nut")`   — bam mot nut thi component GOI GI. Spy la
 *                              `vi.fn()`, khong co mang.
 *   `describe("duong ra HTTP")` — `onFeedback` noi vao `api` THAT (chi `fetch`
 *                              bi thay). Duong Thu lai dau-cuoi (picker →
 *                              `useChat.retry` → `fetch`) do o
 *                              `RetryFlow.test.tsx`: body cua no do `useChat`
 *                              dung, khong phai component nay.
 *
 * KH tham chieu: UC-02, UC-04, §18.2, §11.4, §24.2b·S4, S12 · tasks.md T-3.7,
 * T-S.15, B-231, B-244.
 */

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type Feedback } from "../../lib/api";
import { AnswerActions } from "./AnswerActions";

const ID = "msg-1";

const writeClipboard = vi.fn<(text: string) => Promise<void>>(() => Promise.resolve());

beforeEach(() => {
  // `navigator.clipboard` khong ton tai trong jsdom (cung ly do no khong ton
  // tai ngoai secure context — xem `lib/clipboard.ts`).
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: writeClipboard } });
});

function renderView(overrides: Partial<Parameters<typeof AnswerActions>[0]> = {}) {
  const props = {
    text: "noi dung cau tra loi",
    feedback: null,
    collapse: false,
    onFeedback: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  };
  return { ...render(<AnswerActions {...props} />), props };
}

/**
 * `fireEvent` chu khong `userEvent` o cac ca clipboard — `userEvent.setup()`
 * **tu dat mot ban gia cua `navigator.clipboard`**, tuc no se do ban gia cua
 * thu vien chu khong phai lan goi cua `lib/clipboard.ts`.
 */
function clickButton(name: string): void {
  fireEvent.click(screen.getByRole("button", { name: name }));
}

/**
 * Mo menu "…" bang chuot. Dat tieu diem vao nut TRUOC — cung tat cua jsdom da
 * ghi o `openMenu` cua `AccountMenu.test.tsx`: khong co no, jsdom ban `blur`
 * len `window` va `Menu` cua Radix tu dong ngay khi vua mo.
 */
async function openMore(): Promise<HTMLElement> {
  const trigger = screen.getByRole("button", { name: "Thêm thao tác" });
  act(() => trigger.focus());
  await userEvent.click(trigger);
  return screen.findByRole("menu");
}

describe("hang nut", () => {
  it("Copy dua DUNG noi dung cau tra loi vao clipboard", async () => {
    renderView({ text: "hai dong\nva mot `code`" });

    clickButton("Sao chép");
    await vi.waitFor(() => expect(writeClipboard).toHaveBeenCalledWith("hai dong\nva mot `code`"));
    await screen.findByRole("button", { name: "Đã sao chép" });
  });

  it("Thich lan dau gui 'like'", () => {
    const { props } = renderView({ feedback: null });

    clickButton("Thích");

    expect(props.onFeedback).toHaveBeenCalledWith("like");
  });

  it("bam Thich HAI lan ⇒ lan hai GO danh gia (`null`)", () => {
    /*
      Trang thai di vong qua chinh `feedback` cua props — dung duong ma
      `MessageOut` di qua that. Mot `useState` ben trong component se lam ca
      nay xanh ma van sai: F5 se tat nut vua bam.
    */
    const sent: (Feedback | null)[] = [];
    function Wrapper() {
      const [value, setValue] = useState<Feedback | null>(null);
      return (
        <AnswerActions
          text="x"
          feedback={value}
          collapse={false}
          onFeedback={(next) => {
            sent.push(next);
            setValue(next);
          }}
          onRetry={vi.fn()}
        />
      );
    }
    render(<Wrapper />);

    clickButton("Thích");
    clickButton("Đã thích");

    expect(sent).toEqual(["like", null]);
  });

  it("dang Thich ma bam Khong thich ⇒ DOI gia tri, khong go", () => {
    const { props } = renderView({ feedback: "like" });

    clickButton("Không thích");

    expect(props.onFeedback).toHaveBeenCalledWith("dislike");
  });

  it("nut sang/toi doc tu prop `feedback`, khong tu state rieng", () => {
    const { rerender } = renderView({ feedback: null });
    expect(screen.getByRole("button", { name: "Thích" })).toHaveAttribute("aria-pressed", "false");

    rerender(<AnswerActions text="x" feedback="like" collapse={false} onFeedback={vi.fn()} onRetry={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Đã thích" })).toHaveAttribute("aria-pressed", "true");
  });

  it("MOT nut Thu lai, goi `onRetry()` khong tham so; khong con nut 'Doi model & thu lai'", () => {
    const { props } = renderView();

    expect(screen.getAllByRole("button", { name: /thử lại/i })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /đổi model/i })).toBeNull();
    expect(screen.queryByText(/đổi model/i)).toBeNull();

    clickButton("Thử lại");

    expect(props.onRetry).toHaveBeenCalledTimes(1);
    expect(props.onRetry).toHaveBeenCalledWith();
  });

  it("Cam bay ① — tooltip cua Thu lai noi no dung model DANG CHON, noi qua `aria-describedby`", async () => {
    renderView();
    const retry = screen.getByRole("button", { name: "Thử lại" });

    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    expect(retry).toHaveFocus();

    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent("Tạo lại bằng model đang chọn");
    expect(retry).toHaveAttribute("aria-describedby", tip.id);
  });

  it("Doc to la nut cho T-8.4: `aria-disabled`, khong `disabled`, khong handler", () => {
    renderView();
    const readAloud = screen.getByRole("button", { name: "Đọc to" });

    expect(readAloud).toHaveAttribute("aria-disabled", "true");
    expect(readAloud).toHaveAttribute("data-planned", "T-8.4");
    expect(readAloud).not.toBeDisabled();
    fireEvent.click(readAloud);
  });
});

describe("375 px — gap vao '…' khi co nhanh (ban T-HD3-v2 3f)", () => {
  it("khong nhanh ⇒ khong co nut '…'; Thich/Khong thich/Doc to khong bi an o bat ky be rong nao", () => {
    renderView({ collapse: false });

    expect(screen.queryByRole("button", { name: "Thêm thao tác" })).toBeNull();
    expect(screen.getByRole("button", { name: "Thích" }).parentElement).not.toHaveClass("hidden");
    expect(screen.getByRole("button", { name: "Đọc to" }).parentElement).not.toHaveClass("hidden");
  });

  it("co nhanh ⇒ ba nut an duoi `sm`, '…' chi hien duoi `sm`; menu co Thich/Khong thich (loai tru) + Doc to cho", async () => {
    const { props } = renderView({ collapse: true, feedback: "like" });

    expect(screen.getByRole("button", { name: "Đã thích" }).parentElement).toHaveClass("hidden", "sm:flex");
    expect(screen.getByRole("button", { name: "Đọc to" }).parentElement).toHaveClass("hidden", "sm:block");
    const more = screen.getByRole("button", { name: "Thêm thao tác" });
    expect(more).toHaveClass("sm:hidden");
    // Sao chep va Thu lai KHONG bao gio gap.
    expect(screen.getByRole("button", { name: "Sao chép" }).parentElement).not.toHaveClass("hidden");
    expect(screen.getByRole("button", { name: "Thử lại" }).parentElement).not.toHaveClass("hidden");

    const menu = await openMore();
    const liked = within(menu).getByRole("menuitemcheckbox", { name: "Đã thích" });
    expect(liked).toHaveAttribute("aria-checked", "true");
    expect(within(menu).getByRole("menuitemcheckbox", { name: "Không thích" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    const pending = within(menu).getByRole("menuitem", { name: "Đọc to" });
    expect(pending).toHaveAttribute("aria-disabled", "true");
    expect(pending).toHaveAttribute("data-planned", "T-8.4");

    await userEvent.click(within(menu).getByRole("menuitemcheckbox", { name: "Không thích" }));
    expect(props.onFeedback).toHaveBeenCalledWith("dislike");
  });

  it("bam Doc to trong menu KHONG lam gi va KHONG dong menu", async () => {
    const { props } = renderView({ collapse: true });

    const menu = await openMore();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Đọc to" }));

    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(props.onFeedback).not.toHaveBeenCalled();
    expect(props.onRetry).not.toHaveBeenCalled();
  });
});

// ────────────────── tang hai: chuoi URL that di ra day ──────────────────

const fakeFetch = vi.fn();

function respond(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function initOfCall(n: number): RequestInit {
  return fakeFetch.mock.calls[n][1] as RequestInit;
}

describe("duong ra HTTP", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fakeFetch);
  });

  afterEach(() => {
    fakeFetch.mockReset();
  });

  function renderReal(feedback: Feedback | null = null) {
    return render(
      <AnswerActions
        text="x"
        feedback={feedback}
        collapse={false}
        onFeedback={(value) => void api.sendFeedback(ID, value)}
        onRetry={vi.fn()}
      />,
    );
  }

  it("Thich ⇒ `POST /messages/{id}/feedback` `{value:'like'}`, KHONG khoa §11.4", () => {
    fakeFetch.mockResolvedValue(respond(200, { message_id: ID, feedback: "like", feedback_reason: null }));
    renderReal();

    clickButton("Thích");

    expect(String(fakeFetch.mock.calls[0][0])).toBe(`/api/v1/messages/${ID}/feedback`);
    expect(initOfCall(0).body).toBe('{"value":"like"}');
    // A8 noi ve POST **tao tai nguyen**; day la `UPDATE` hai cot tren mot hang
    // da co, nen no khong vao `IDEMPOTENCY_REQUIRED_ROUTES` (T-3.7a).
    expect(initOfCall(0).headers).not.toHaveProperty("Idempotency-Key");
  });

  it("go danh gia ⇒ `{value:null}` TUONG MINH, khong phai body rong", () => {
    fakeFetch.mockResolvedValue(respond(200, { message_id: ID, feedback: null, feedback_reason: null }));
    renderReal("like");

    clickButton("Đã thích");

    // Backend khai `value` la truong bat buoc: mot body rong la `422`, va do
    // la co y — xem `FeedbackRequest` cua T-3.7a.
    expect(initOfCall(0).body).toBe('{"value":null}');
  });
});
