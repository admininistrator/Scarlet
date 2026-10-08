/**
 * Dinh kem anh/tep — T-4.7 (UC-06, §15.1, NQ-138 ⑧).
 *
 * jsdom 30.1.0 khong co `DataTransfer`, `ClipboardEvent`, `DragEvent`,
 * `URL.createObjectURL` (Cam bay ①): dan va keo-tha la su kien TU DUNG
 * (`clipboardData`/`dataTransfer` gia qua `fireEvent`). `URL.createObjectURL`
 * toan cuc trong vitest la ban cua NODE (do: no doi `Blob` Node, nem voi `File`
 * cua jsdom) ⇒ thay bang `vi.spyOn(...).mockImplementation` va dem. Hanh vi that cua trinh duyet chi
 * chung minh duoc tren Chrome (DoD dong 3).
 *
 * Moi ca ket thuc bang phep dem `createObjectURL` = `revokeObjectURL` o diem
 * nao no bo khay (go / gui / unmount) — DoD dong 2.
 */

import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      uploadAttachment: vi.fn(),
      getAttachment: vi.fn(),
      createConversation: vi.fn(),
      sendMessage: vi.fn(),
      getConversation: vi.fn(),
    },
  };
});

// jsdom khong co `EventSource`; ca 13 do body HTTP, khong do stream.
vi.mock("../../lib/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/sse")>();
  return { ...actual, openStream: () => ({ close: () => {}, cursor: () => "" }) };
});

import { ApiError, api, type MessageAttachment, type MessageOut } from "../../lib/api";
import { useChat, type SendKeys, type SendResult } from "../../features/chat/useChat";
import { emptyTree } from "../../lib/tree";
import { Composer } from "./Composer";
import { MessageItem } from "./MessageItem";

const upload = vi.mocked(api.uploadAttachment);
const getAttachment = vi.mocked(api.getAttachment);

const LIMITS = {
  max_upload_mb: 10,
  max_attachments: 3,
  allowed_upload_mime: ["image/png", "image/jpeg", "application/pdf", "text/plain"],
};
const MB = 1024 * 1024;

function file(name: string, type: string, size?: number): File {
  const f = new File(["x"], name, { type });
  if (size !== undefined) {
    Object.defineProperty(f, "size", { value: size });
  }
  return f;
}

function served(f: File, extract = f.type === "application/pdf" ? "pending" : "none"): MessageAttachment {
  return {
    id: `srv-${f.name}`,
    kind: f.type.startsWith("image/") ? "image" : "file",
    name: f.name,
    bytes: f.size,
    mime_type: f.type,
    width: null,
    height: null,
    extract_status: extract,
    url: null,
  };
}

let created: ReturnType<typeof vi.spyOn>;
let revoked: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  upload.mockReset().mockImplementation(async (f: File) => served(f));
  getAttachment.mockReset();
  // Ham cua Node (vitest dua ra toan cuc) doi `Blob` cua Node, khong nhan
  // `File` cua jsdom — thay bang ban dem.
  let blobs = 0;
  created = vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:test/${(blobs += 1)}`);
  revoked = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});

afterEach(() => {
  created.mockRestore();
  revoked.mockRestore();
});

type OnSend = (content: string, keys: SendKeys, ids: string[]) => Promise<SendResult>;

function renderComposer(onSend: OnSend = vi.fn(async () => "da-gui" as SendResult), noVision = false) {
  return render(
    <Composer
      running={false}
      enabled
      maxChars={null}
      onSend={onSend}
      onStop={vi.fn()}
      docked
      noVision={noVision}
      uploadLimits={LIMITS}
    />,
  );
}

const textbox = () => screen.getByRole("textbox");
const sendButton = () => screen.getByRole("button", { name: "Gửi" });
const fileInput = () => document.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement;
/** Hop nhap: textarea → label → hop (noi nghe keo-tha). */
const box = () => textbox().parentElement?.parentElement as HTMLElement;
const previews = () => screen.queryByRole("list", { name: "Tệp đính kèm" });

function pick(...files: File[]) {
  fireEvent.change(fileInput(), { target: { files } });
}

describe("o nhap — dinh kem (T-4.7)", () => {
  it("1. chon qua nut: input `multiple` + `accept` tu /auth/me, MOT POST moi tep, khoa KHAC nhau, anh hien bang blob:", async () => {
    const click = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    renderComposer();

    await userEvent.click(screen.getByRole("button", { name: "Đính kèm ảnh hoặc tệp" }));
    expect(click).toHaveBeenCalledOnce();
    click.mockRestore();
    expect(fileInput()).toHaveAttribute("multiple");
    expect(fileInput()).toHaveAttribute("accept", LIMITS.allowed_upload_mime.join(","));

    pick(file("a.png", "image/png"), file("b.txt", "text/plain"));
    await waitFor(() => expect(sendButton()).toBeEnabled());

    expect(upload).toHaveBeenCalledTimes(2);
    const keys = upload.mock.calls.map(([, key]) => key);
    expect(new Set(keys).size).toBe(2);
    expect(within(previews() as HTMLElement).getByRole("img", { name: "a.png" })).toHaveAttribute(
      "src",
      expect.stringMatching(/^blob:/),
    );
    expect(created).toHaveBeenCalledTimes(1); // chi anh co blob:
  });

  it("2. go khoi khay: KHONG goi API nao, blob: duoc thu hoi", async () => {
    renderComposer();
    pick(file("a.png", "image/png"), file("b.png", "image/png"));
    await waitFor(() => expect(sendButton()).toBeEnabled());
    upload.mockClear();

    await userEvent.click(screen.getByRole("button", { name: "Xoá tệp đính kèm — b.png" }));

    expect(within(previews() as HTMLElement).getAllByRole("listitem")).toHaveLength(1);
    expect(upload).not.toHaveBeenCalled();
    expect(getAttachment).not.toHaveBeenCalled();
    expect(revoked).toHaveBeenCalledTimes(1);
    expect(revoked).toHaveBeenCalledWith(created.mock.results[1].value);

    await userEvent.click(screen.getByRole("button", { name: "Xoá tệp đính kèm — a.png" }));
    expect(previews()).toBeNull();
    expect(revoked).toHaveBeenCalledTimes(created.mock.calls.length);
  });

  it("3. chan TRUOC upload: qua co, sai loai (.svg), qua so ⇒ bao ly do, KHONG POST cho tep bi chan", async () => {
    renderComposer();

    pick(file("to.png", "image/png", 11 * MB), file("logo.svg", "image/svg+xml"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("to.png: vượt dung lượng cho phép (10 MB)");
    expect(alert).toHaveTextContent("logo.svg: loại tệp không được hỗ trợ");
    expect(upload).not.toHaveBeenCalled();
    expect(previews()).toBeNull();

    pick(file("1.png", "image/png"), file("2.png", "image/png"), file("3.png", "image/png"), file("4.png", "image/png"));
    expect(await screen.findByRole("alert")).toHaveTextContent("4.png: quá số tệp cho phép mỗi tin nhắn (3)");
    expect(upload).toHaveBeenCalledTimes(3);
    expect(created).toHaveBeenCalledTimes(3); // tep bi chan khong tao blob:
  });

  it("4. gui: `attachment_ids` dung thu tu, chu duoc RONG; xong ⇒ khay rong, moi blob: thu hoi", async () => {
    const onSend = vi.fn<OnSend>(async () => "da-gui");
    renderComposer(onSend);
    pick(file("a.png", "image/png"), file("b.txt", "text/plain"));
    await waitFor(() => expect(sendButton()).toBeEnabled());

    await userEvent.click(sendButton());

    expect(onSend).toHaveBeenCalledOnce();
    const [content, keys, ids] = onSend.mock.calls[0];
    expect(content).toBe("");
    expect(keys.message).toEqual(expect.any(String));
    expect(ids).toEqual(["srv-a.png", "srv-b.txt"]);
    expect(previews()).toBeNull();
    expect(revoked).toHaveBeenCalledTimes(created.mock.calls.length);
  });

  it("5. gui LOI ⇒ khay GIU, blob: con song; gui lai mang CUNG khoa va CUNG ids", async () => {
    const onSend = vi.fn<OnSend>().mockResolvedValueOnce("hong").mockResolvedValueOnce("da-gui");
    renderComposer(onSend);
    pick(file("a.png", "image/png"));
    await waitFor(() => expect(sendButton()).toBeEnabled());

    await userEvent.click(sendButton());
    expect(within(previews() as HTMLElement).getAllByRole("listitem")).toHaveLength(1);
    expect(revoked).not.toHaveBeenCalled();

    await userEvent.click(sendButton());
    expect(onSend.mock.calls[1][1]).toEqual(onSend.mock.calls[0][1]);
    expect(onSend.mock.calls[1][2]).toEqual(["srv-a.png"]);
    expect(revoked).toHaveBeenCalledTimes(created.mock.calls.length);
  });

  it("6. PDF: Gui tat toi khi `extract_status` roi `pending`", async () => {
    getAttachment.mockResolvedValueOnce(served(file("bc.pdf", "application/pdf"), "pending"));
    getAttachment.mockResolvedValueOnce(served(file("bc.pdf", "application/pdf"), "done"));
    renderComposer();
    await userEvent.type(textbox(), "tom tat giup");

    pick(file("bc.pdf", "application/pdf"));
    expect(await screen.findByText("Đang đọc tệp…")).toBeInTheDocument();
    expect(sendButton()).toBeDisabled();

    await waitFor(() => expect(sendButton()).toBeEnabled(), { timeout: 4000 });
    expect(getAttachment).toHaveBeenCalledTimes(2);
    expect(getAttachment).toHaveBeenCalledWith("srv-bc.pdf");
  });

  it("7. upload hong (`413` HTML cua Nginx) ⇒ chip bao loi, Gui tat toi khi go", async () => {
    upload.mockRejectedValueOnce(new ApiError(413, "HTTP_ERROR", "HTTP 413 Request Entity Too Large"));
    renderComposer();
    await userEvent.type(textbox(), "x");

    pick(file("bc.pdf", "application/pdf"));
    expect(await screen.findByText("vượt dung lượng cho phép (10 MB)")).toBeInTheDocument();
    expect(sendButton()).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Xoá tệp đính kèm — bc.pdf" }));
    expect(sendButton()).toBeEnabled();
  });

  it("8. dan anh tu clipboard (su kien tu dung) ⇒ them 1 anh; clipboard CO chu ⇒ la dan chu", async () => {
    renderComposer();

    fireEvent.paste(textbox(), { clipboardData: { files: [file("chup.png", "image/png")], types: ["Files"] } });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(within(previews() as HTMLElement).getByRole("img", { name: "chup.png" })).toBeInTheDocument();

    fireEvent.paste(textbox(), {
      clipboardData: { files: [file("word.png", "image/png")], types: ["text/plain", "Files"] },
    });
    expect(upload).toHaveBeenCalledTimes(1);
  });

  it("9. keo-tha tep len hop nhap (su kien tu dung) ⇒ `dragover` chan mac dinh, `drop` them tep", async () => {
    renderComposer();
    const dataTransfer = { files: [file("bc.pdf", "application/pdf")], types: ["Files"] };

    expect(fireEvent.dragOver(box(), { dataTransfer })).toBe(false); // da `preventDefault`
    fireEvent.drop(box(), { dataTransfer });

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(screen.getByText("bc.pdf")).toBeInTheDocument();
  });

  it("10. model khong vision: dan/tha ANH bi tu choi kem ly do; PDF van nhan", async () => {
    renderComposer(undefined, true);

    fireEvent.drop(box(), {
      dataTransfer: { files: [file("a.png", "image/png"), file("bc.pdf", "application/pdf")], types: ["Files"] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("a.png: Model này không đọc được ảnh");
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload.mock.calls[0][0].name).toBe("bc.pdf");
    expect(created).not.toHaveBeenCalled();
  });

  it("11. unmount voi khay con anh ⇒ moi blob: deu thu hoi", async () => {
    const view = renderComposer();
    pick(file("a.png", "image/png"), file("b.jpg", "image/jpeg"));
    await waitFor(() => expect(sendButton()).toBeEnabled());

    act(() => view.unmount());

    expect(created).toHaveBeenCalledTimes(2);
    expect(revoked).toHaveBeenCalledTimes(2);
  });
});

describe("useChat.send — body HTTP", () => {
  it("13. co tep ⇒ `attachment_ids` trong body `POST …/messages`, `content` rong; khong tep ⇒ KHONG co truong ay", async () => {
    const conversation = {
      id: "c-1",
      title: null,
      default_model: null,
      system_prompt_override: null,
      active_leaf_id: null,
      pinned: false,
      created_at: "2026-10-06T00:00:00Z",
      updated_at: "2026-10-06T00:00:00Z",
    };
    vi.mocked(api.createConversation).mockResolvedValue(conversation);
    vi.mocked(api.getConversation).mockResolvedValue({ ...conversation, path: [] });
    const sendMessage = vi.mocked(api.sendMessage).mockResolvedValue({
      assistant_message_id: "a",
      stream_url: "/api/v1/messages/a/stream",
      branched: false,
      quota_warning: null,
    } as Awaited<ReturnType<typeof api.sendMessage>>);
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.send("", { conversation: "k1", message: "k2" }, ["srv-a.png", "srv-bc.pdf"]);
    });
    await act(async () => {
      await result.current.send("cau sau", { conversation: "k3", message: "k4" });
    });

    expect(sendMessage.mock.calls[0][1]).toMatchObject({ content: "", attachment_ids: ["srv-a.png", "srv-bc.pdf"] });
    expect(sendMessage.mock.calls[0][2]).toBe("k2");
    expect(sendMessage.mock.calls[1][1]).not.toHaveProperty("attachment_ids");
  });
});

describe("bong bong nguoi dung — tep tu duong di (UC-06 dong 5)", () => {
  it("12. `attachments[]` cua message ⇒ anh cung origin + chip PDF; `content` rong ⇒ khong doan chu rong", () => {
    const node: MessageOut = {
      id: "u1",
      parent_id: null,
      role: "user",
      status: "completed",
      content: "",
      reasoning: null,
      model_id: null,
      finish_reason: null,
      error_code: null,
      created_at: "2026-10-06T00:00:00Z",
      sibling_index: 0,
      sibling_count: 1,
      feedback: null,
      reasoning_effort: null,
      attachments: [
        { ...served(file("a.png", "image/png")), url: `${window.location.origin}/media/scarlet/u/a.png?X-Amz-Signature=s` },
        served(file("bc.pdf", "application/pdf"), "done"),
      ],
    };
    const { container } = render(
      <MessageItem
        node={node}
        tree={emptyTree()}
        models={[]}
        running={false}
        busy={false}
        onRetry={vi.fn()}
        onFeedback={vi.fn()}
        onEdit={vi.fn()}
        onSwitchBranch={vi.fn()}
      />,
    );

    const list = screen.getByRole("list", { name: "Tệp đính kèm" });
    expect(within(list).getByRole("img", { name: "a.png" })).toHaveAttribute(
      "src",
      `${window.location.origin}/media/scarlet/u/a.png?X-Amz-Signature=s`,
    );
    expect(within(list).getByText("bc.pdf")).toBeInTheDocument();
    expect(container.querySelector("article > p")).toBeNull();
  });
});
