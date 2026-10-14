/**
 * Mic + Doc to — DoD dong 1 cua T-8.4 (ADR-13, §16.2, ban T-HD12).
 *
 * `SpeechRecognition` / `speechSynthesis` gia o `test/speech.ts`. Khong cai ⇒
 * dung nhu jsdom (va Firefox o ve mic): khong co.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, useRef, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { FakeRecognition, FakeUtterance, installRecognition, installSynthesis } from "../../test/speech";
import type { SendKeys, SendResult } from "../../features/chat/useChat";
import { AnswerActions } from "./AnswerActions";
import { Composer } from "./Composer";
import { Markdown } from "./Markdown";

const MIC = "Nhập bằng giọng nói";
const CODE_LINE = "print('khoa-bi-mat-42')";
const ANSWER = `Đây là câu trả lời.\n\n- mục một\n- mục hai\n\n\`\`\`python\n${CODE_LINE}\n\`\`\`\n\nHết.`;

function renderComposer(conversationId: string | null = "c-1", wrap = (node: ReactNode) => node) {
  const onSend = vi.fn(async (_c: string, _k: SendKeys, _a: string[]) => "da-gui" as SendResult);
  const element = (id: string | null) =>
    wrap(
      <Composer
        running={false}
        enabled
        maxChars={1000}
        docked
        onSend={onSend}
        onStop={vi.fn()}
        conversationId={id}
      />,
    );
  const view = render(element(conversationId));
  return { onSend, rerender: (id: string | null) => view.rerender(element(id)), unmount: view.unmount };
}

const textbox = () => screen.getByRole<HTMLTextAreaElement>("textbox");
const mic = () => screen.getByRole("button", { name: MIC });
const lastRecognition = () => FakeRecognition.instances.at(-1) as FakeRecognition;

describe("Mic (Composer)", () => {
  it("1. khong `SpeechRecognition` (Firefox) ⇒ 0 nut mic trong DOM — khong phai aria-disabled", () => {
    renderComposer();
    expect(screen.queryByRole("button", { name: MIC })).toBeNull();
    expect(document.querySelector('[aria-label="Nhập bằng giọng nói"], [data-planned="T-8.4"]')).toBeNull();
  });

  it("2. co `SpeechRecognition` ⇒ nut mic, tooltip noi la nhan dang cua trinh duyet", async () => {
    installRecognition();
    renderComposer();
    expect(mic()).not.toHaveAttribute("aria-disabled");
    act(() => mic().focus());
    expect(await screen.findByRole("tooltip")).toHaveTextContent("nhận dạng giọng nói của trình duyệt");
  });

  it("3. ket qua CUOI ⇒ chu noi vao o nhap (sau chu da go), KHONG gui", async () => {
    installRecognition();
    const { onSend } = renderComposer();
    await userEvent.type(textbox(), "Xin chào");
    fireEvent.click(mic());
    const recognition = lastRecognition();
    expect(recognition.lang).toBe("vi-VN");
    expect(recognition.interimResults).toBe(true);

    act(() => recognition.hear(" bạn khoẻ không ", true));

    expect(textbox().value).toBe("Xin chào bạn khoẻ không");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("4. ket qua TAM ⇒ hien, khong vao gia tri o nhap; dang nghe = nut 'Dung nghe'", () => {
    installRecognition();
    renderComposer();
    fireEvent.click(mic());
    expect(screen.getByRole("status")).toHaveTextContent("Đang nghe…");

    act(() => lastRecognition().hear("đang nói dở", false));

    expect(screen.getByText("đang nói dở")).toBeInTheDocument();
    expect(textbox().value).toBe("");
    expect(screen.getByRole("button", { name: "Dừng nghe" })).toBeInTheDocument();
  });

  it("5. `error: not-allowed` ⇒ cau loi + nut ve nghi", () => {
    installRecognition();
    renderComposer();
    fireEvent.click(mic());

    act(() => lastRecognition().fail("not-allowed"));

    expect(screen.getByRole("alert")).toHaveTextContent("Chưa có quyền dùng micro");
    expect(mic()).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dừng nghe" })).toBeNull();
  });

  it("6. `no-speech` / `network` ⇒ cau theo ma; bam lai ⇒ cau loi bien mat", () => {
    installRecognition();
    renderComposer();
    fireEvent.click(mic());
    act(() => lastRecognition().fail("no-speech"));
    expect(screen.getByRole("alert")).toHaveTextContent("Không nghe thấy gì");

    fireEvent.click(mic());
    expect(screen.queryByRole("alert")).toBeNull();
    act(() => lastRecognition().fail("network"));
    expect(screen.getByRole("alert")).toHaveTextContent("Mất kết nối tới dịch vụ nhận giọng nói");
  });

  it("7. StrictMode ⇒ dung MOT recognition, MOT `start()` moi lan bam", () => {
    installRecognition();
    renderComposer("c-1", (node) => <StrictMode>{node}</StrictMode>);

    fireEvent.click(mic());

    expect(FakeRecognition.instances).toHaveLength(1);
    expect(lastRecognition().start).toHaveBeenCalledTimes(1);
  });

  it("8. bam lai khi dang nghe ⇒ `stop()` (khong `abort()`)", () => {
    installRecognition();
    renderComposer();
    fireEvent.click(mic());
    const recognition = lastRecognition();

    fireEvent.click(screen.getByRole("button", { name: "Dừng nghe" }));

    expect(recognition.stop).toHaveBeenCalledTimes(1);
    expect(recognition.abort).not.toHaveBeenCalled();
    expect(mic()).toBeInTheDocument();
  });

  it("9. gui khi dang nghe ⇒ `abort()`, chu tam khong di theo", async () => {
    installRecognition();
    const { onSend } = renderComposer();
    await userEvent.type(textbox(), "câu hỏi");
    fireEvent.click(mic());
    const recognition = lastRecognition();
    act(() => recognition.hear("chưa chốt", false));

    fireEvent.click(screen.getByRole("button", { name: "Gửi" }));

    expect(recognition.abort).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(onSend.mock.calls[0][0]).toBe("câu hỏi");
    expect(mic()).toBeInTheDocument();
  });

  it("10. doi hoi thoai / roi man ⇒ `abort()`", () => {
    installRecognition();
    const { rerender, unmount } = renderComposer("c-1");
    fireEvent.click(mic());
    const first = lastRecognition();
    rerender("c-2");
    expect(first.abort).toHaveBeenCalledTimes(1);
    expect(mic()).toBeInTheDocument();

    fireEvent.click(mic());
    const second = lastRecognition();
    rerender("c-2");
    expect(second.abort).not.toHaveBeenCalled();
    unmount();
    expect(second.abort).toHaveBeenCalledTimes(1);
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Doc to (AnswerActions)
   ══════════════════════════════════════════════════════════════════════════ */

function Answer({ text = ANSWER, collapse = false }: { text?: string; collapse?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <article>
      <div ref={ref}>
        <Markdown text={text} streaming={false} />
      </div>
      <AnswerActions
        text={text}
        contentRef={ref}
        feedback={null}
        collapse={collapse}
        onFeedback={vi.fn()}
        onRetry={vi.fn()}
      />
    </article>
  );
}

const spoken = (synth: ReturnType<typeof installSynthesis>, n = 0) => synth.speak.mock.calls[n][0] as FakeUtterance;

describe("Doc to (AnswerActions)", () => {
  it("11. khong `speechSynthesis` ⇒ khong nut Doc to, ca o menu '…'", async () => {
    render(<Answer collapse />);
    expect(screen.queryByRole("button", { name: "Đọc to" })).toBeNull();
    const trigger = screen.getByRole("button", { name: "Thêm thao tác" });
    act(() => trigger.focus());
    await userEvent.click(trigger);
    const menu = await screen.findByRole("menu");
    expect(within(menu).queryByRole("menuitem", { name: "Đọc to" })).toBeNull();
    expect(document.querySelector('[data-planned="T-8.4"]')).toBeNull();
  });

  it("12. bam ⇒ `speak` MOT utterance locale vi, giong `vi*` khi co; dang doc = 'Dung doc'", () => {
    const vietnameseVoice = { lang: "vi-VN", name: "Linh" };
    const synth = installSynthesis([{ lang: "en-US", name: "Sam" }, vietnameseVoice]);
    render(<Answer />);

    fireEvent.click(screen.getByRole("button", { name: "Đọc to" }));

    expect(synth.speak).toHaveBeenCalledTimes(1);
    expect(spoken(synth).lang).toBe("vi-VN");
    expect(spoken(synth).voice).toBe(vietnameseVoice);
    expect(screen.getByRole("button", { name: "Dừng đọc" })).toHaveAttribute("aria-pressed", "true");
  });

  it("13. khong giong vi ⇒ giong mac dinh (`voice` null), van `lang` vi", () => {
    const synth = installSynthesis([{ lang: "en-US", name: "Sam" }]);
    render(<Answer />);
    fireEvent.click(screen.getByRole("button", { name: "Đọc to" }));
    expect(spoken(synth).voice).toBeNull();
    expect(spoken(synth).lang).toBe("vi-VN");
  });

  it("14. chu doc la chu DA RENDER, KHONG chua noi dung khoi ma, khong ky hieu markdown", () => {
    const synth = installSynthesis();
    render(<Answer />);
    fireEvent.click(screen.getByRole("button", { name: "Đọc to" }));
    const text = spoken(synth).text;
    expect(text).toBe("Đây là câu trả lời. mục một mục hai Hết.");
    expect(text.includes(CODE_LINE)).toBe(false);
    expect(document.body.textContent).toContain(CODE_LINE);
  });

  it("15. bam lai ⇒ `cancel()`, nut ve nghi", () => {
    const synth = installSynthesis();
    render(<Answer />);
    fireEvent.click(screen.getByRole("button", { name: "Đọc to" }));
    synth.cancel.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Dừng đọc" }));

    expect(synth.cancel).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Đọc to" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("16. bam cau thu hai ⇒ cau thu nhat huy, chi cau hai 'dang doc', khong cau loi", () => {
    const synth = installSynthesis();
    render(
      <>
        <Answer text="Câu một." />
        <Answer text="Câu hai." />
      </>,
    );
    const [first, second] = screen.getAllByRole("button", { name: "Đọc to" });
    fireEvent.click(first);
    fireEvent.click(second);

    expect(synth.cancel).toHaveBeenCalledTimes(2);
    expect(spoken(synth, 1).text).toBe("Câu hai.");
    const buttons = screen.getAllByRole("button", { name: /Đọc to|Dừng đọc/ });
    expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual(["Đọc to", "Dừng đọc"]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("17. `error: synthesis-failed` (khong `end`) ⇒ ve nghi + cau loi, khong ket 'dang doc'", () => {
    const synth = installSynthesis();
    render(<Answer />);
    fireEvent.click(screen.getByRole("button", { name: "Đọc to" }));

    act(() => spoken(synth).onerror?.({ error: "synthesis-failed" }));

    expect(screen.getByRole("button", { name: "Đọc to" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("alert")).toHaveTextContent("Không đọc được");
  });

  it("18. doc xong (`end`) ⇒ ve nghi", () => {
    const synth = installSynthesis();
    render(<Answer />);
    fireEvent.click(screen.getByRole("button", { name: "Đọc to" }));
    act(() => spoken(synth).onend?.());
    expect(screen.getByRole("button", { name: "Đọc to" })).toBeInTheDocument();
  });

  it("19. menu '…' (< 640, co nhanh): muc Doc to that, bam ⇒ `speak`", async () => {
    const synth = installSynthesis();
    render(<Answer collapse />);
    const trigger = screen.getByRole("button", { name: "Thêm thao tác" });
    act(() => trigger.focus());
    await userEvent.click(trigger);
    const menu = await screen.findByRole("menu");
    const item = within(menu).getByRole("menuitem", { name: "Đọc to" });
    expect(item).not.toHaveAttribute("aria-disabled");

    await userEvent.click(item);

    expect(synth.speak).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Dừng đọc" })).toBeInTheDocument();
  });

  it("20. unmount khi dang doc (doi hoi thoai) ⇒ `cancel()`", () => {
    const synth = installSynthesis();
    const view = render(<Answer />);
    fireEvent.click(screen.getByRole("button", { name: "Đọc to" }));
    synth.cancel.mockClear();
    view.unmount();
    expect(synth.cancel).toHaveBeenCalledTimes(1);
  });
});
