/**
 * `ModelPicker` + `pickDefault` — T-3.6.
 *
 * KH tham chieu: §9.3, §9.4, UC-05, RR-5 · tasks.md T-3.6 (DoD dong 3, Cam
 * bay ① và ③) · ADR-16.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  ID MODEL CHỈ ĐƯỢC PHÉP SỐNG TRONG FILE NÀY                            ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * DoD dòng 4 chạy `grep -rnE '"(deepseek|claude|gpt|gemini|ol)-[a-z0-9.-]+"'`
 * trên `frontend/src/` rồi lọc bỏ `.test.`, và kết quả phải rỗng. Vì vậy
 * fixture nằm **trong chính file test** chứ không ở một `*.fixture.ts` cạnh
 * component — một file như thế sẽ khớp lệnh grep ấy và làm phép kiểm A3 của
 * FE đỏ vĩnh viễn (cùng cái bẫy `check_hardcode.sh` lệnh 2 đã gặp ở T-0.9).
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ModelOut } from "../../lib/api";
import { pickDefault } from "./defaults";
import { ModelPicker } from "./ModelPicker";

/** Lý do khoá — dài, có dấu, đúng hình dạng câu server trả (bản T-HD4). */
const REASON =
  "9Router (local) đang không phản hồi, nên các model của nguồn này tạm thời " +
  "không chọn được. Hãy thử lại sau ít phút, hoặc xem mục Hệ thống để biết chi tiết.";

function model(p: Partial<ModelOut> & Pick<ModelOut, "id">): ModelOut {
  return {
    display_name: p.id,
    provider: "nha cung cap",
    provider_id: "nha-cung-cap",
    capabilities: [],
    context_window: 1000,
    max_output: 100,
    default: false,
    badge: null,
    available: true,
    unavailable_reason: null,
    checked_at: "2026-09-24T07:32:10Z",
    stale_after_s: 30,
    ...p,
  };
}

const RE = model({
  id: "deepseek-flash",
  display_name: "DeepSeek Flash",
  provider: "DeepSeek AI",
  capabilities: ["tools", "vision", "reasoning"],
  badge: "Mặc định · Rẻ",
  default: true,
});
const HAIKU = model({
  id: "claude-haiku",
  display_name: "Claude Haiku 4.5",
  provider: "Anthropic",
  capabilities: ["tools", "vision"],
});
const DISABLED = model({
  id: "nr-gemini-flash",
  display_name: "Gemini Flash (qua 9Router)",
  provider: "9Router (local)",
  capabilities: ["tools"],
  badge: "9Router",
  available: false,
  unavailable_reason: REASON,
});
const QWEN = model({
  id: "ol-qwen-small",
  display_name: "Qwen2.5 0.5B (Ollama)",
  provider: "Ollama (self-host)",
  badge: "Self-host",
});

const FOUR = [RE, HAIKU, DISABLED, QWEN];

function renderView(
  options: {
    models?: ModelOut[];
    conversation?: string | null;
    account?: string | null;
    refreshing?: boolean;
    loading?: boolean;
  } = {},
) {
  const models = options.models ?? FOUR;
  const onPick = vi.fn();
  const onRefresh = vi.fn();
  const onOpen = vi.fn();
  render(
    <ModelPicker
      models={models}
      defaultPick={pickDefault(models, {
        conversation: options.conversation ?? null,
        account: options.account ?? null,
      })}
      checkedAtLabel="14:32"
      loading={options.loading}
      refreshing={options.refreshing}
      onRefresh={onRefresh}
      onPick={onPick}
      onOpen={onOpen}
    />,
  );
  return { onPick, onRefresh, onOpen };
}

async function openPicker(): Promise<void> {
  await userEvent.click(screen.getByRole("button", { name: "Chọn mô hình" }));
}

/**
 * Hàng của một model, tìm theo TÊN HIỂN THỊ.
 *
 * Không dựng `RegExp` từ `ten`: hai tên trong catalog thật có dấu ngoặc
 * (`Gemini Flash (qua 9Router)`, `Qwen2.5 0.5B (Ollama)`) và chúng là ký tự
 * CÓ NGHĨA trong biểu thức chính quy — `new RegExp(ten)` biến chúng thành
 * một nhóm bắt, nên phép tìm trượt đúng hai hàng mà DoD dòng 3 cần.
 */
function row(name: string): HTMLElement {
  // Bó trong `listbox`: nút mở picker CŨNG in tên model đang chọn, nên một
  // `getByText` trên cả màn hình khớp hai phần tử cho đúng model ấy.
  const o = within(screen.getByRole("listbox")).getByText(name).closest('[role="option"]');
  if (o === null) {
    throw new Error(`khong tim thay hang cho "${name}"`);
  }
  return o as HTMLElement;
}

beforeEach(() => {
  /*
    jsdom không có `matchMedia`. Trả `matches: false` = bề rộng desktop, tức
    nhánh Popover + tooltip — đúng nhánh mà DoD dòng 3 đo.
  */
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});

// ───────────────────── `pickDefault` — ba tầng (UC-05 dòng 4) ────────────────

describe("chonMacDinh — ba tầng", () => {
  it("1. không tầng nào đặt ⇒ rơi về `default: true` của catalog", () => {
    const r = pickDefault(FOUR, { conversation: null, account: null });
    expect(r.modelId).toBe(RE.id);
    expect(r.tier).toBe("catalog");
  });

  it("2. chỉ tầng tài khoản ⇒ tài khoản thắng catalog", () => {
    const r = pickDefault(FOUR, { conversation: null, account: QWEN.id });
    expect(r.modelId).toBe(QWEN.id);
    expect(r.tier).toBe("account");
  });

  it("3. cả hai tầng ⇒ hội thoại thắng tài khoản", () => {
    const r = pickDefault(FOUR, { conversation: HAIKU.id, account: QWEN.id });
    expect(r.modelId).toBe(HAIKU.id);
    expect(r.tier).toBe("conversation");
  });

  it("4. Cạm bẫy ① — `default_model` của user trỏ vào model đã biến mất khỏi catalog ⇒ rơi về catalog, KHÔNG trả id trần", () => {
    const r = pickDefault(FOUR, { conversation: null, account: "model-da-bi-xoa" });
    expect(r.modelId).toBe(RE.id);
    expect(r.tier).toBe("catalog");
    expect(r.byTier.account).toBeNull();
  });

  it("5. Cạm bẫy ① — `default_model` của HỘI THOẠI biến mất ⇒ rơi xuống tầng tài khoản chứ không xuống thẳng catalog", () => {
    const r = pickDefault(FOUR, { conversation: "model-da-bi-xoa", account: QWEN.id });
    expect(r.modelId).toBe(QWEN.id);
    expect(r.tier).toBe("account");
  });

  it("6. model không khả dụng VẪN được chọn làm mặc định (Cạm bẫy ③ — 9Router bật lại sau vài phút)", () => {
    const r = pickDefault(FOUR, { conversation: DISABLED.id, account: null });
    expect(r.modelId).toBe(DISABLED.id);
    expect(r.tier).toBe("conversation");
  });

  it("7. catalog không có `default` nào ⇒ lấy model đầu tiên theo `order`, không trả `null`", () => {
    const r = pickDefault([HAIKU, QWEN], { conversation: null, account: null });
    expect(r.modelId).toBe(HAIKU.id);
    expect(r.tier).toBeNull();
  });

  it("8. danh sách rỗng ⇒ `null`, không ném", () => {
    const r = pickDefault([], { conversation: "bat-ky", account: "bat-ky" });
    expect(r.modelId).toBeNull();
    expect(r.tier).toBeNull();
  });
});

// ──────────────── Hàng `available: false` — DoD dòng 3 ───────────────────────

describe("model không khả dụng", () => {
  it("9. mục đó `aria-disabled`", async () => {
    renderView();
    await openPicker();
    expect(row(DISABLED.display_name)).toHaveAttribute("aria-disabled", "true");
  });

  it("10. bấm KHÔNG đổi model", async () => {
    const { onPick } = renderView();
    await openPicker();
    await userEvent.click(row(DISABLED.display_name));
    expect(onPick).not.toHaveBeenCalled();
  });

  it("11. Enter và Space cũng KHÔNG đổi model (Cạm bẫy ③ — không chỉ mờ đi)", async () => {
    const { onPick } = renderView();
    await openPicker();
    row(DISABLED.display_name).focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onPick).not.toHaveBeenCalled();
  });

  it("12. hover ⇒ tooltip là `unavailable_reason` NGUYÊN VĂN, không cắt", async () => {
    renderView();
    await openPicker();
    await userEvent.hover(row(DISABLED.display_name));
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(REASON);
  });

  it("13. desktop — `aria-describedby` chỉ tồn tại khi tooltip MỞ, và nó trỏ vào một `id` CÓ THẬT", async () => {
    renderView();
    await openPicker();
    // Đóng: không được trỏ vào một id không có trong DOM.
    expect(row(DISABLED.display_name)).not.toHaveAttribute("aria-describedby");

    await userEvent.hover(row(DISABLED.display_name));
    await screen.findByRole("tooltip");
    const id = row(DISABLED.display_name).getAttribute("aria-describedby");
    expect(id).not.toBeNull();
    expect(document.getElementById(id as string)).toHaveTextContent(REASON);
  });

  it("14. bề rộng nhỏ — không có hover nên lý do nằm THẲNG trong hàng, gắn bằng `aria-describedby`", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: true,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    );
    renderView();
    await openPicker();

    const h = row(DISABLED.display_name);
    const id = h.getAttribute("aria-describedby");
    expect(id).not.toBeNull();
    expect(document.getElementById(id as string)).toHaveTextContent(REASON);
  });

  it("15. hàng khoá vẫn nằm trong tab order (`tabIndex 0`, KHÔNG `disabled`)", async () => {
    renderView();
    await openPicker();
    expect(row(DISABLED.display_name)).toHaveAttribute("tabindex", "0");
  });

  it("16. model khả dụng thì bấm ĐỔI được — phép kiểm ngược của ca 10", async () => {
    const { onPick } = renderView();
    await openPicker();
    await userEvent.click(row(HAIKU.display_name));
    expect(onPick).toHaveBeenCalledWith(HAIKU.id);
  });
});

// ───────────────────────── Badge capability (§9.4) ──────────────────────────

describe("badge và capability", () => {
  it("17. ba capability của §9.4 hiện bằng nhãn tiếng Việt", async () => {
    renderView();
    await openPicker();
    const h = within(row(RE.display_name));
    expect(h.getByText("Công cụ")).toBeInTheDocument();
    expect(h.getByText("Hình ảnh")).toBeInTheDocument();
    expect(h.getByText("Suy luận")).toBeInTheDocument();
  });

  it("18. `badge` của catalog hiện NGUYÊN VĂN, không dịch", async () => {
    renderView();
    await openPicker();
    expect(within(row(RE.display_name)).getByText("Mặc định · Rẻ")).toBeInTheDocument();
  });

  it("19. model không có capability nào ⇒ nói ra, không để trống", async () => {
    renderView();
    await openPicker();
    expect(
      within(row(QWEN.display_name)).getByText("Không có khả năng đặc biệt"),
    ).toBeInTheDocument();
  });

  it("20. capability lạ (catalog sửa nóng) hiện chuỗi thô chứ không làm vỡ hàng", async () => {
    const unknown = model({ id: "x-la", display_name: "Model la", capabilities: ["telepathy"] });
    renderView({ models: [unknown] });
    await openPicker();
    expect(within(row("Model la")).getByText("telepathy")).toBeInTheDocument();
  });
});

// ──────────────────── Chip tầng + strip trạng thái (T-HD4) ──────────────────

describe("tầng mặc định và strip trạng thái", () => {
  it("21. ba tầng vẽ ba chip khác nhau, đúng hàng", async () => {
    renderView({ conversation: HAIKU.id, account: QWEN.id });
    await openPicker();
    expect(within(row(HAIKU.display_name)).getByText("Mặc định hội thoại")).toBeInTheDocument();
    expect(within(row(QWEN.display_name)).getByText("Mặc định tài khoản")).toBeInTheDocument();
    expect(within(row(RE.display_name)).getByText("Mặc định catalog")).toBeInTheDocument();
  });

  it("22. dấu tích theo model ĐANG CHỌN, chip theo TẦNG — hai thông tin tách nhau", async () => {
    renderView({ conversation: HAIKU.id, account: QWEN.id });
    await openPicker();
    expect(row(HAIKU.display_name)).toHaveAttribute("aria-selected", "true");
    expect(row(QWEN.display_name)).toHaveAttribute("aria-selected", "false");
    // QWEN có chip (tầng tài khoản) mà KHÔNG được chọn — đúng ca bản T-HD4 mô tả.
    expect(within(row(QWEN.display_name)).getByText("Mặc định tài khoản")).toBeInTheDocument();
  });

  it("23. nút mở in tầng của model đang dùng ở dòng thứ hai", () => {
    renderView({ conversation: HAIKU.id });
    const button = screen.getByRole("button", { name: "Chọn mô hình" });
    expect(within(button).getByText("Claude Haiku 4.5")).toBeInTheDocument();
    expect(within(button).getByText("Mặc định hội thoại")).toBeInTheDocument();
  });

  it("24. mốc giờ và câu chữ là HAI phần tử cạnh nhau, không phải một chuỗi ghép", async () => {
    renderView();
    await openPicker();
    expect(screen.getByText("Trạng thái kiểm lúc")).toBeInTheDocument();
    expect(screen.getByText("14:32")).toBeInTheDocument();
  });

  it("25. bấm nút làm mới gọi `onLamMoi` đúng một lần", async () => {
    const { onRefresh } = renderView();
    await openPicker();
    await userEvent.click(screen.getByRole("button", { name: "Kiểm lại trạng thái" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("26. đang làm mới ⇒ `aria-busy` + nhãn đổi, và danh sách VẪN bấm được", async () => {
    const { onPick } = renderView({ refreshing: true });
    await openPicker();
    const button = screen.getByRole("button", { name: "Đang kiểm lại trạng thái" });
    expect(button).toHaveAttribute("aria-busy", "true");

    await userEvent.click(row(HAIKU.display_name));
    expect(onPick).toHaveBeenCalledWith(HAIKU.id);
  });

  it("27. chỗ chừa cho cảnh báo capability (T-4.5) có mặt và rỗng", async () => {
    const { container } = render(
      <ModelPicker
        models={FOUR}
        defaultPick={pickDefault(FOUR, { conversation: null, account: null })}
        checkedAtLabel="14:32"
        onRefresh={vi.fn()}
        onPick={vi.fn()}
      />,
    );
    await userEvent.click(within(container).getByRole("button", { name: "Chọn mô hình" }));
    const gate = document.querySelector('[data-slot="capability-warning"]');
    expect(gate).not.toBeNull();
    expect(gate).toBeEmptyDOMElement();
  });

  it("28. KHÔNG có id model nào lọt vào DOM — component chỉ hiện `display_name`", async () => {
    renderView();
    await openPicker();
    for (const m of FOUR) {
      expect(screen.queryByText(m.id)).toBeNull();
    }
  });

  it("29. T-S.4 — lần đọc đầu chưa xong ⇒ 'đang tải', KHÔNG phải 'Chưa có mô hình nào'", async () => {
    renderView({ models: [], loading: true });
    expect(screen.getByRole("button", { name: "Chọn mô hình" })).toHaveTextContent("Đang tải…");
    await openPicker();
    expect(screen.getByRole("status")).toHaveTextContent("Đang tải danh sách mô hình…");
    expect(screen.queryByText("Chưa có mô hình nào")).toBeNull();
  });

  it("30. T-S.4 — đọc xong mà rỗng thật thì vẫn nói rỗng", async () => {
    renderView({ models: [], loading: false });
    await openPicker();
    expect(screen.getByRole("status")).toHaveTextContent("Chưa có mô hình nào");
  });

  it("31. T-S.4 — mỗi lần MỞ gọi `onOpen` đúng một lần; đóng thì không", async () => {
    const { onOpen } = renderView();
    await openPicker();
    expect(onOpen).toHaveBeenCalledTimes(1);
    await userEvent.keyboard("{Escape}");
    expect(onOpen).toHaveBeenCalledTimes(1);
    await openPicker();
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});
