/**
 * Hang nam nut duoi cau tra loi — DoD dong 1 cua T-3.7.
 *
 * File nay do HAI tang, va chung tra loi hai cau khac nhau:
 *
 *   `describe("hang nut")`   — bam mot nut thi component GOI GI. Spy la
 *                              `vi.fn()`, khong co mang.
 *   `describe("duong ra HTTP")` — cung nhung nut ay, nhung `onRetry` /
 *                              `onFeedback` noi vao `api` THAT (chi `fetch` bi
 *                              thay). Day la cho dong DoD *"Retry goi dung
 *                              endpoint"* va *"gui `model_id` khac"* duoc do:
 *                              mot spy khong biet gi ve chuoi URL that.
 *
 * Doan noi o tang hai chep dung mot dong cua `useChat.retry`/`sendFeedback`. No
 * khong the lech trong im lang: `tsc` buoc ca hai ben dung mot chu ky, va chu
 * ky ay (`thuLai(messageId, body, khoa)`) la thu B-231 vua doi.
 *
 * KH tham chieu: UC-02, UC-04, §18.2, §11.4 · tasks.md T-3.7, B-231, B-244.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type Feedback } from "../../lib/api";
import { AnswerActions } from "./AnswerActions";

const OLD_MODEL = "model-da-sinh-ra-cau-nay";
const SELECTED_MODEL = "model-dang-chon-tren-picker";
const ID = "msg-1";

const writeClipboard = vi.fn<(text: string) => Promise<void>>(() => Promise.resolve());

beforeEach(() => {
  // `navigator.clipboard` khong ton tai trong jsdom (cung ly do no khong ton
  // tai ngoai secure context — xem `lib/clipboard.ts`).
  vi.stubGlobal("navigator", { clipboard: { writeText: writeClipboard } });
});

function renderView(overrides: Partial<Parameters<typeof AnswerActions>[0]> = {}) {
  const props = {
    text: "noi dung cau tra loi",
    feedback: null,
    usedModel: OLD_MODEL,
    selectedModel: SELECTED_MODEL,
    onFeedback: vi.fn(),
    onRetry: vi.fn(),
    onRetryWithModel: vi.fn(),
    ...overrides,
  };
  return { ...render(<AnswerActions {...props} />), props };
}

/**
 * `fireEvent` chu khong `userEvent` — khac voi `Composer.test.tsx`, va co ly do.
 *
 * `userEvent.setup()` **tu dat mot ban gia cua `navigator.clipboard`** de mo
 * phong copy/paste cua ban phim; o file nay chinh `navigator.clipboard` la thu
 * dang duoc do, nen no se do ban gia cua thu vien chu khong phai lan goi cua
 * `lib/clipboard.ts`. `fireEvent` khong cham vao `navigator`.
 */
function clickButton(name: string): void {
  fireEvent.click(screen.getByRole("button", { name: name }));
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
          usedModel={OLD_MODEL}
          selectedModel={null}
          onFeedback={(next) => {
            sent.push(next);
            setValue(next);
          }}
          onRetry={vi.fn()}
          onRetryWithModel={vi.fn()}
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
    expect(screen.getByRole("button", { name: "Thích" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    rerender(
      <AnswerActions
        text="x"
        feedback="like"
        usedModel={OLD_MODEL}
        selectedModel={null}
        onFeedback={vi.fn()}
        onRetry={vi.fn()}
        onRetryWithModel={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Đã thích" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("Thu lai tron KHONG kem model nao", () => {
    const { props } = renderView();

    clickButton("Thử lại");

    expect(props.onRetry).toHaveBeenCalledTimes(1);
    expect(props.onRetry).toHaveBeenCalledWith();
    expect(props.onRetryWithModel).not.toHaveBeenCalled();
  });

  it("'Doi model & thu lai' gui model KHAC model da sinh ra cau tra loi", () => {
    const { props } = renderView({ usedModel: OLD_MODEL, selectedModel: SELECTED_MODEL });

    clickButton("Đổi model & thử lại");

    expect(props.onRetryWithModel).toHaveBeenCalledWith(SELECTED_MODEL);
    expect(props.onRetryWithModel).not.toHaveBeenCalledWith(OLD_MODEL);
  });

  it("nut doi model TAT khi picker dang chi dung model cu", () => {
    renderView({ usedModel: OLD_MODEL, selectedModel: OLD_MODEL });

    expect(screen.getByRole("button", { name: "Đổi model & thử lại" })).toBeDisabled();
  });

  it("nut doi model TAT khi chua biet model nao dang chon", () => {
    renderView({ selectedModel: null });

    expect(screen.getByRole("button", { name: "Đổi model & thử lại" })).toBeDisabled();
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
    fakeFetch.mockResolvedValue(respond(202, {}));
  });

  afterEach(() => {
    fakeFetch.mockReset();
  });

  /** Noi y het `useChat`: nut tron khong truyen model, nut kia truyen. */
  function renderReal(feedback: Feedback | null = null) {
    return render(
      <AnswerActions
        text="x"
        feedback={feedback}
        usedModel={OLD_MODEL}
        selectedModel={SELECTED_MODEL}
        onFeedback={(value) => void api.sendFeedback(ID, value)}
        onRetry={() => void api.retry(ID, {}, "khoa-cua-lan-bam")}
        onRetryWithModel={(modelId) => void api.retry(ID, { model_id: modelId }, "khoa-cua-lan-bam")}
      />,
    );
  }

  it("Thu lai ⇒ `POST /messages/{id}/retry` kem `Idempotency-Key` (B-231)", () => {
    renderReal();

    clickButton("Thử lại");

    expect(String(fakeFetch.mock.calls[0][0])).toBe(`/api/v1/messages/${ID}/retry`);
    const init = initOfCall(0);
    expect(init.method).toBe("POST");
    // Thieu header nay la `400 IDEMPOTENCY_KEY_REQUIRED` ke tu NQ-93.
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("khoa-cua-lan-bam");
    expect(init.body).toBe("{}");
  });

  it("'Doi model & thu lai' ⇒ cung endpoint, body mang `model_id` KHAC", () => {
    renderReal();

    clickButton("Đổi model & thử lại");

    expect(String(fakeFetch.mock.calls[0][0])).toBe(`/api/v1/messages/${ID}/retry`);
    const sent = JSON.parse(String(initOfCall(0).body)) as { model_id: string };
    expect(sent.model_id).toBe(SELECTED_MODEL);
    expect(sent.model_id).not.toBe(OLD_MODEL);
  });

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
