/**
 * `ModelPicker` v2 + `pickDefault` — T-3.6, T-S.4, T-S.14.
 *
 * KH tham chieu: §9.3, §9.4, §24.2b·S3, S11, UC-05, RR-5 · tasks.md T-3.6 (DoD
 * dong 3, Cam bay ① va ③), T-S.14 (DoD dong 1) · ADR-16 · B-308.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  ID MODEL CHỈ ĐƯỢC PHÉP SỐNG TRONG FILE TEST                           ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * DoD T-S.14 dòng 5 chạy `grep -rnE '"(deepseek|claude|gpt|gemini|grok|ol)-…"'`
 * trên `frontend/src/` rồi lọc bỏ `.test.`, và kết quả phải rỗng. Vì vậy
 * fixture nằm **trong chính file test** chứ không ở một `*.fixture.ts`.
 *
 * B-308 ①: `Menu` của Radix đóng khi `window` phát `blur`, và jsdom phát
 * `blur` khi tiêu điểm cũ là chính Document. Mọi lần mở menu con ở đây đặt
 * tiêu điểm vào hàng ② TRƯỚC khi bấm (`openEffort`).
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ByokEndpoint, ModelOut } from "../../lib/api";
import { endpointModels } from "./byokModels";
import { pickDefault } from "./defaults";
import { ModelPicker } from "./ModelPicker";
import { effectiveEffort } from "./reasoning";

/** Lý do khoá — câu chung của NQ-119, dài, có dấu (bản T-HD4-v2 mục D). */
const REASON =
  "Nguồn cung cấp model này đang không phản hồi, nên model tạm thời không chọn được. " +
  "Hãy thử lại sau ít phút, hoặc xem mục Hệ thống để biết chi tiết.";

function model(p: Partial<ModelOut> & Pick<ModelOut, "id">): ModelOut {
  return {
    display_name: p.id,
    provider: "Hang",
    provider_id: "hang",
    capabilities: [],
    context_window: 1000,
    max_output: 100,
    default: false,
    badge: null,
    available: true,
    unavailable_reason: null,
    reasoning: null,
    pricing: null,
    pricing_mode: "unmetered",
    checked_at: "2026-09-24T07:32:10Z",
    stale_after_s: 30,
    ...p,
  };
}

const levels = (...ids: string[]) => ids.map((id) => ({ id }));

const DEEPSEEK = model({
  id: "deepseek-flash",
  display_name: "DeepSeek Flash",
  provider: "DeepSeek",
  capabilities: ["tools", "vision", "reasoning"],
  badge: "Mặc định · Rẻ",
  default: true,
  reasoning: { default: "high", options: levels("off", "low", "high", "max") },
  pricing: {
    current: { window: "peak", input_per_1m: "0.30", output_per_1m: "1.20" },
    other: { window: "off_peak", input_per_1m: "0.15", output_per_1m: "0.60" },
    estimated: false,
  },
  pricing_mode: "metered",
});
const HAIKU = model({
  id: "claude-haiku",
  display_name: "Claude Haiku 4.5",
  provider: "Anthropic",
  capabilities: ["tools", "vision"],
  reasoning: { default: "off", options: levels("off", "low", "high") },
  pricing: {
    current: { window: null, input_per_1m: "1.00", output_per_1m: "5.00" },
    other: null,
    estimated: false,
  },
  pricing_mode: "metered",
});
const DISABLED = model({
  id: "nr-gemini-flash",
  display_name: "Gemini Flash",
  provider: "Google AI",
  provider_id: null,
  capabilities: ["tools"],
  available: false,
  unavailable_reason: REASON,
  reasoning: { default: "low", options: levels("low", "high") },
});
const QWEN = model({
  id: "ol-qwen-small",
  display_name: "Qwen2.5 0.5B (Ollama)",
  provider: "Alibaba Qwen",
  badge: "Self-host",
});

const FOUR = [DEEPSEEK, HAIKU, DISABLED, QWEN];

function renderView(
  options: {
    models?: ModelOut[];
    conversation?: string | null;
    account?: string | null;
    effort?: string | null;
    refreshing?: boolean;
    loading?: boolean;
  } = {},
) {
  const models = options.models ?? FOUR;
  const defaultPick = pickDefault(models, {
    conversation: options.conversation ?? null,
    account: options.account ?? null,
  });
  const onPick = vi.fn();
  const onPickEffort = vi.fn();
  const onRefresh = vi.fn();
  const onOpen = vi.fn();
  const selected = models.find((m) => m.id === defaultPick.modelId);
  render(
    <ModelPicker
      models={models}
      defaultPick={defaultPick}
      effort={options.effort === undefined ? effectiveEffort(selected, {}) : options.effort}
      checkedAtLabel="14:32"
      loading={options.loading}
      refreshing={options.refreshing}
      onRefresh={onRefresh}
      onPick={onPick}
      onPickEffort={onPickEffort}
      onOpen={onOpen}
    />,
  );
  return { onPick, onPickEffort, onRefresh, onOpen };
}

const trigger = () => screen.getByRole("button", { name: /^Chọn mô hình/ });
const effortRow = () => screen.getByRole("button", { name: /^Thinking Effort/ });
const moreRow = () => screen.getByRole("button", { name: /^More models/ });
/** Bảng chọn desktop — `Popover.Content` là `role="dialog"`. */
const pickerPanel = () => screen.queryByRole("dialog", { name: "Chọn mô hình" });

async function openPicker(): Promise<void> {
  await userEvent.click(trigger());
}

async function openEffort(): Promise<void> {
  await openPicker();
  // B-308 ① — tiêu điểm TRƯỚC khi bấm, không thì menu tự đóng khi `window` blur.
  act(() => effortRow().focus());
  await userEvent.click(effortRow());
  await screen.findByRole("menu");
}

async function openMoreModels(): Promise<void> {
  await openPicker();
  await userEvent.click(moreRow());
  await screen.findByRole("listbox");
}

/**
 * Hàng của một model trong "More models", tìm theo TÊN HIỂN THỊ.
 *
 * Không dựng `RegExp` từ tên: `Qwen2.5 0.5B (Ollama)` có dấu ngoặc — ký tự CÓ
 * NGHĨA trong biểu thức chính quy.
 */
function row(name: string): HTMLElement {
  const o = within(screen.getByRole("listbox")).getByText(name).closest('[role="option"]');
  if (o === null) {
    throw new Error(`khong tim thay hang cho "${name}"`);
  }
  return o as HTMLElement;
}

function narrowScreen(): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: true,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

beforeEach(() => {
  /*
    jsdom không có `matchMedia`. Trả `matches: false` = bề rộng desktop, tức
    nhánh Popover + tooltip — đúng nhánh mà DoD T-3.6 dòng 3 đo.
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
    expect(r.modelId).toBe(DEEPSEEK.id);
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
    expect(r.modelId).toBe(DEEPSEEK.id);
    expect(r.tier).toBe("catalog");
    expect(r.byTier.account).toBeNull();
  });

  it("5. Cạm bẫy ① — `default_model` của HỘI THOẠI biến mất ⇒ rơi xuống tầng tài khoản chứ không xuống thẳng catalog", () => {
    const r = pickDefault(FOUR, { conversation: "model-da-bi-xoa", account: QWEN.id });
    expect(r.modelId).toBe(QWEN.id);
    expect(r.tier).toBe("account");
  });

  it("6. model không khả dụng VẪN được chọn làm mặc định (Cạm bẫy ③ — nguồn bật lại sau vài phút)", () => {
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

// ────────── Hàng `available: false` trong More models — T-3.6 DoD dòng 3 ─────────

describe("model không khả dụng (More models)", () => {
  it("9. mục đó `aria-disabled`", async () => {
    renderView();
    await openMoreModels();
    expect(row(DISABLED.display_name)).toHaveAttribute("aria-disabled", "true");
  });

  it("10. bấm KHÔNG đổi model, và bảng chọn vẫn mở", async () => {
    const { onPick } = renderView();
    await openMoreModels();
    await userEvent.click(row(DISABLED.display_name));
    expect(onPick).not.toHaveBeenCalled();
    expect(pickerPanel()).not.toBeNull();
  });

  it("11. Enter và Space cũng KHÔNG đổi model (Cạm bẫy ③ — không chỉ mờ đi)", async () => {
    const { onPick } = renderView();
    await openMoreModels();
    act(() => row(DISABLED.display_name).focus());
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onPick).not.toHaveBeenCalled();
  });

  it("12. hover ⇒ tooltip là `unavailable_reason` NGUYÊN VĂN, không cắt", async () => {
    renderView();
    await openMoreModels();
    await userEvent.hover(row(DISABLED.display_name));
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(REASON);
  });

  it("13. desktop — `aria-describedby` chỉ tồn tại khi tooltip MỞ, và nó trỏ vào một `id` CÓ THẬT", async () => {
    renderView();
    await openMoreModels();
    expect(row(DISABLED.display_name)).not.toHaveAttribute("aria-describedby");

    await userEvent.hover(row(DISABLED.display_name));
    await screen.findByRole("tooltip");
    const id = row(DISABLED.display_name).getAttribute("aria-describedby");
    expect(id).not.toBeNull();
    expect(document.getElementById(id as string)).toHaveTextContent(REASON);
  });

  it("14. 375 px — không có hover nên lý do nằm THẲNG trong hàng, gắn bằng `aria-describedby`", async () => {
    narrowScreen();
    renderView();
    await openPicker();
    await userEvent.click(moreRow());

    const h = row(DISABLED.display_name);
    const id = h.getAttribute("aria-describedby");
    expect(id).not.toBeNull();
    expect(document.getElementById(id as string)).toHaveTextContent(REASON);
  });

  it("15. hàng khoá vẫn nằm trong tab order (`tabIndex 0`, KHÔNG `disabled`)", async () => {
    renderView();
    await openMoreModels();
    expect(row(DISABLED.display_name)).toHaveAttribute("tabindex", "0");
  });

  it("16. model khả dụng thì bấm ĐỔI được — phép kiểm ngược của ca 10 — và đóng CẢ picker (bản D)", async () => {
    const { onPick } = renderView();
    await openMoreModels();
    await userEvent.click(row(HAIKU.display_name));
    expect(onPick).toHaveBeenCalledWith(HAIKU.id);
    await waitFor(() => expect(pickerPanel()).toBeNull());
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });
});

// ───────────────────────── Badge capability (§9.4) ──────────────────────────

describe("badge và capability", () => {
  it("17. ba capability của §9.4 hiện bằng nhãn tiếng Việt", async () => {
    renderView();
    await openMoreModels();
    const h = within(row(DEEPSEEK.display_name));
    expect(h.getByText("Công cụ")).toBeInTheDocument();
    expect(h.getByText("Hình ảnh")).toBeInTheDocument();
    expect(h.getByText("Suy luận")).toBeInTheDocument();
  });

  it("18. `badge` của catalog hiện NGUYÊN VĂN, không dịch", async () => {
    renderView();
    await openMoreModels();
    expect(within(row(DEEPSEEK.display_name)).getByText("Mặc định · Rẻ")).toBeInTheDocument();
  });

  it("19. model không có capability nào ⇒ nói ra, không để trống", async () => {
    renderView();
    await openMoreModels();
    expect(
      within(row(QWEN.display_name)).getByText("Không có khả năng mở rộng"),
    ).toBeInTheDocument();
  });

  it("20. capability lạ (catalog sửa nóng) hiện chuỗi thô chứ không làm vỡ hàng", async () => {
    const unknown = model({ id: "x-la", display_name: "Model la", capabilities: ["telepathy"] });
    renderView({ models: [unknown] });
    await openMoreModels();
    expect(within(row("Model la")).getByText("telepathy")).toBeInTheDocument();
  });
});

// ──────────────────── Chip tầng + strip trạng thái (T-HD4) ──────────────────

describe("tầng mặc định và strip trạng thái", () => {
  it("21. ba tầng vẽ ba chip khác nhau, đúng hàng", async () => {
    renderView({ conversation: HAIKU.id, account: QWEN.id });
    await openMoreModels();
    expect(within(row(HAIKU.display_name)).getByText("Mặc định hội thoại")).toBeInTheDocument();
    expect(within(row(QWEN.display_name)).getByText("Mặc định tài khoản")).toBeInTheDocument();
    expect(within(row(DEEPSEEK.display_name)).getByText("Mặc định catalog")).toBeInTheDocument();
  });

  it("22. dấu tích theo model ĐANG CHỌN, chip theo TẦNG — hai thông tin tách nhau", async () => {
    renderView({ conversation: HAIKU.id, account: QWEN.id });
    await openMoreModels();
    expect(row(HAIKU.display_name)).toHaveAttribute("aria-selected", "true");
    expect(row(QWEN.display_name)).toHaveAttribute("aria-selected", "false");
    expect(within(row(QWEN.display_name)).getByText("Mặc định tài khoản")).toBeInTheDocument();
  });

  it("23. v2 — nút mở chỉ là TÊN model (chữ trơn); tầng nằm ở khối ① 'Đang dùng'", async () => {
    renderView({ conversation: HAIKU.id });
    expect(trigger()).toHaveTextContent("Claude Haiku 4.5");
    expect(within(trigger()).queryByText("Mặc định hội thoại")).toBeNull();

    await openPicker();
    const panel = within(pickerPanel() as HTMLElement);
    expect(panel.getByText("Đang dùng")).toBeInTheDocument();
    expect(panel.getByText("Claude Haiku 4.5")).toBeInTheDocument();
    expect(panel.getByText("Anthropic")).toBeInTheDocument();
    expect(panel.getByText("Mặc định hội thoại")).toBeInTheDocument();
    expect(panel.getByText("Thứ tự thắng: hội thoại › tài khoản › catalog")).toBeInTheDocument();
  });

  it("24. mốc giờ và câu chữ là HAI phần tử cạnh nhau, không phải một chuỗi ghép", async () => {
    renderView();
    await openMoreModels();
    expect(screen.getByText("Trạng thái kiểm lúc")).toBeInTheDocument();
    expect(screen.getByText("14:32")).toBeInTheDocument();
  });

  it("25. bấm nút làm mới gọi `onRefresh` đúng một lần", async () => {
    const { onRefresh } = renderView();
    await openMoreModels();
    await userEvent.click(screen.getByRole("button", { name: "Kiểm lại trạng thái" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("26. đang làm mới ⇒ `aria-busy` + nhãn đổi, và danh sách VẪN bấm được", async () => {
    const { onPick } = renderView({ refreshing: true });
    await openMoreModels();
    const button = screen.getByRole("button", { name: "Đang kiểm lại trạng thái" });
    expect(button).toHaveAttribute("aria-busy", "true");

    await userEvent.click(row(HAIKU.display_name));
    expect(onPick).toHaveBeenCalledWith(HAIKU.id);
  });

  it("27. chỗ chừa cho cảnh báo capability (T-4.5) có mặt trong khối ① và rỗng", async () => {
    renderView();
    await openPicker();
    const gate = (pickerPanel() as HTMLElement).querySelector('[data-slot="capability-warning"]');
    expect(gate).not.toBeNull();
    expect(gate).toBeEmptyDOMElement();
  });

  it("28. KHÔNG có id model nào lọt vào DOM — component chỉ hiện `display_name`", async () => {
    renderView();
    await openMoreModels();
    for (const m of FOUR) {
      expect(screen.queryByText(m.id)).toBeNull();
      expect(document.body.innerHTML).not.toContain(`"${m.id}"`);
    }
  });

  it("29. T-S.4 — lần đọc đầu chưa xong ⇒ 'đang tải', KHÔNG phải 'Chưa có mô hình nào'", async () => {
    renderView({ models: [], loading: true });
    expect(trigger()).toHaveTextContent("Đang tải…");
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

// ─────────────────────── Thinking Effort ›  (T-S.14) ─────────────────────────

describe("Thinking Effort", () => {
  it("32. DoD — model không có `reasoning` ⇒ hàng `aria-disabled`, không in giá trị, bấm KHÔNG mở menu con", async () => {
    renderView({ account: QWEN.id });
    await openPicker();
    const r = effortRow();
    expect(r).toHaveAttribute("aria-disabled", "true");
    expect(r).not.toHaveAttribute("disabled");
    expect(r).toHaveClass("control-disabled");
    expect(r).toHaveTextContent(/^Thinking Effort$/);

    await userEvent.click(r);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("33. hàng mờ ⇒ tooltip 'Model này không có tuỳ chọn suy luận' (hover và bàn phím)", async () => {
    renderView({ account: QWEN.id });
    await openPicker();
    await userEvent.hover(effortRow());
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Model này không có tuỳ chọn suy luận",
    );
  });

  it("34. hàng ② in nhãn tiếng Anh của mức hiệu lực", async () => {
    renderView({ effort: "max" });
    await openPicker();
    expect(effortRow()).toHaveTextContent("Thinking EffortMax");
  });

  it("35. menu con chỉ có mức của MODEL NÀY, đúng thứ tự catalog; mức hiệu lực `aria-checked`", async () => {
    renderView();
    await openEffort();
    const items = screen.getAllByRole("menuitemradio");
    expect(items.map((i) => i.textContent)).toEqual(["Off", "Low", "High", "Max"]);
    expect(screen.getByRole("menuitemradio", { name: "High" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: "Low" })).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("menuitemradio", { name: "Medium" })).toBeNull();
  });

  it("36. chọn một mức ⇒ `onPickEffort(id)` đúng một lần; menu con đóng, bảng chọn vẫn mở", async () => {
    const { onPickEffort, onPick } = renderView();
    await openEffort();
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Low" }));
    expect(onPickEffort).toHaveBeenCalledTimes(1);
    expect(onPickEffort).toHaveBeenCalledWith("low");
    expect(onPick).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(pickerPanel()).not.toBeNull();
  });

  it("37. bàn phím — → mở menu con; ← đóng và trả tiêu điểm về hàng ②", async () => {
    renderView();
    await openPicker();
    act(() => effortRow().focus());
    await userEvent.keyboard("{ArrowRight}");
    expect(await screen.findByRole("menu")).toBeInTheDocument();

    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(effortRow()).toHaveFocus();
    expect(pickerPanel()).not.toBeNull();
  });

  it("38. Esc trong menu con chỉ đóng MENU CON — bảng chọn vẫn mở, tiêu điểm về hàng ②", async () => {
    renderView();
    await openEffort();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(pickerPanel()).not.toBeNull();
    expect(effortRow()).toHaveFocus();
  });

  it("39. Cạm bẫy ② (tầng hàm) — mức nhớ THEO MODEL: model khác không mượn mức của model này", () => {
    const prefs = { [DEEPSEEK.id]: "max" };
    expect(effectiveEffort(DEEPSEEK, prefs)).toBe("max");
    expect(effectiveEffort(HAIKU, prefs)).toBe("off");
    expect(effectiveEffort(HAIKU, { ...prefs, [HAIKU.id]: "low" })).toBe("low");
  });

  it("40. mức đã nhớ không còn trong `options` (catalog vừa bớt) ⇒ rơi về `reasoning.default`", () => {
    expect(effectiveEffort(DEEPSEEK, { [DEEPSEEK.id]: "medium" })).toBe("high");
  });

  it("41. model không có `reasoning` ⇒ `null` dù `prefs` có khoá của nó", () => {
    expect(effectiveEffort(QWEN, { [QWEN.id]: "high" })).toBeNull();
    expect(effectiveEffort(undefined, {})).toBeNull();
  });
});

// ───────────────────────────── More models › ────────────────────────────────

describe("More models", () => {
  it("42. bàn phím — → trên hàng ③ mở danh sách; Esc đóng RIÊNG danh sách, tiêu điểm về hàng ③", async () => {
    renderView();
    await openPicker();
    act(() => moreRow().focus());
    await userEvent.keyboard("{ArrowRight}");
    expect(await screen.findByRole("listbox")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    expect(pickerPanel()).not.toBeNull();
    expect(moreRow()).toHaveFocus();
  });

  it("43. danh sách là danh sách v1: 64 px, ✓ đúng model đang chọn, hãng là hãng gốc", async () => {
    renderView();
    await openMoreModels();
    expect(screen.getAllByRole("option")).toHaveLength(4);
    expect(row(DEEPSEEK.display_name)).toHaveClass("min-h-row-model");
    expect(row(DEEPSEEK.display_name)).toHaveAttribute("aria-selected", "true");
    expect(within(row(DISABLED.display_name)).getByText("Google AI")).toBeInTheDocument();
  });
});

// ─────────────────────────────── Giá (khối ④) ────────────────────────────────

describe("giá", () => {
  function priceBlock(): HTMLElement {
    const label = within(pickerPanel() as HTMLElement).getByText("Giá");
    return label.parentElement as HTMLElement;
  }

  it("44. giờ cao điểm ⇒ dòng chính là giá niêm yết + chip 'Đang áp dụng · Cao điểm'; dòng thấp điểm không chip", async () => {
    renderView();
    await openPicker();
    const block = within(priceBlock());
    expect(priceBlock()).toHaveTextContent("Vào $0.30 · Ra $1.20 / 1M token");
    const chip = block.getByText("Đang áp dụng · Cao điểm");
    expect(chip.parentElement).toHaveTextContent("$0.30");
    const offPeak = block.getByText(/^Giờ thấp điểm:/);
    expect(offPeak).toHaveTextContent("Giờ thấp điểm: Vào $0.15 · Ra $0.60");
    expect(offPeak.parentElement).not.toHaveTextContent("Đang áp dụng");
    expect(block.getByText("Suy luận được tính như token ra.")).toBeInTheDocument();
  });

  it("45. giờ thấp điểm (backend chọn) ⇒ chip chuyển xuống dòng thấp điểm; dòng chính giữ giá niêm yết", async () => {
    const offPeakNow = {
      ...DEEPSEEK,
      pricing: {
        current: { window: "off_peak" as const, input_per_1m: "0.15", output_per_1m: "0.60" },
        other: { window: "peak" as const, input_per_1m: "0.30", output_per_1m: "1.20" },
        estimated: false,
      },
    };
    renderView({ models: [offPeakNow, HAIKU] });
    await openPicker();
    const block = within(priceBlock());
    const chip = block.getByText("Đang áp dụng · Thấp điểm");
    expect(chip.parentElement).toHaveTextContent("Giờ thấp điểm: Vào $0.15 · Ra $0.60");
    expect(block.queryByText("Đang áp dụng · Cao điểm")).toBeNull();
    expect(priceBlock()).toHaveTextContent("Vào $0.30 · Ra $1.20 / 1M token");
  });

  it("46. một giá (không khung giờ) ⇒ không chip, không dòng thấp điểm", async () => {
    renderView({ account: HAIKU.id });
    await openPicker();
    expect(priceBlock()).toHaveTextContent("Vào $1.00 · Ra $5.00 / 1M token");
    expect(within(priceBlock()).queryByText(/Đang áp dụng/)).toBeNull();
    expect(within(priceBlock()).queryByText(/Giờ thấp điểm/)).toBeNull();
  });

  it("47. giá từ `manual_pricing` ⇒ chữ 'ước lượng' gắn sau giá", async () => {
    const estimated = {
      ...HAIKU,
      pricing: { ...(HAIKU.pricing as NonNullable<ModelOut["pricing"]>), estimated: true },
    };
    renderView({ models: [estimated], account: HAIKU.id });
    await openPicker();
    expect(priceBlock()).toHaveTextContent("Vào $1.00 · Ra $5.00 / 1M token · ước lượng");
  });

  it("48. không tính theo token (`pricing: null`) ⇒ 'Không tính phí theo token', KHÔNG dòng suy luận", async () => {
    renderView({ account: QWEN.id });
    await openPicker();
    expect(within(priceBlock()).getByText("Không tính phí theo token")).toBeInTheDocument();
    expect(within(priceBlock()).queryByText("Suy luận được tính như token ra.")).toBeNull();
  });
});

// ───────────────────────── 375 px — một sheet, ba màn ─────────────────────────

describe("375 px — sheet ba màn", () => {
  beforeEach(narrowScreen);

  it("49. màn chính có đủ bốn khối; Thinking Effort › là màn con có nút quay lại, tên model ở trên", async () => {
    renderView();
    await openPicker();
    const sheet = within(screen.getByRole("dialog"));
    expect(sheet.getByRole("heading", { name: "Chọn mô hình" })).toBeInTheDocument();
    expect(sheet.getByText("Đang dùng")).toBeInTheDocument();
    expect(sheet.getByText("Giá")).toBeInTheDocument();

    await userEvent.click(effortRow());
    expect(sheet.getByRole("heading", { name: "Thinking Effort" })).toBeInTheDocument();
    expect(sheet.getByText("DeepSeek Flash")).toBeInTheDocument();
    expect(sheet.getByRole("button", { name: "Quay lại" })).toHaveFocus();
    expect(sheet.getByRole("menuitemradio", { name: "High" })).toHaveAttribute("aria-checked", "true");

    await userEvent.click(sheet.getByRole("button", { name: "Quay lại" }));
    expect(sheet.getByRole("heading", { name: "Chọn mô hình" })).toBeInTheDocument();
    expect(effortRow()).toHaveFocus();
  });

  it("50. chọn mức ở màn Thinking Effort ⇒ `onPickEffort` + về màn chính, tiêu điểm ở hàng ②", async () => {
    const { onPickEffort } = renderView();
    await openPicker();
    await userEvent.click(effortRow());
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Max" }));
    expect(onPickEffort).toHaveBeenCalledWith("max");
    expect(screen.getByRole("heading", { name: "Chọn mô hình" })).toBeInTheDocument();
    expect(effortRow()).toHaveFocus();
    // Sheet vẫn mở: đổi mức không phải đổi model.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("51. More models › là màn con; quay lại ⇒ tiêu điểm về hàng ③; chọn model ⇒ đóng sheet", async () => {
    const { onPick } = renderView();
    await openPicker();
    await userEvent.click(moreRow());
    expect(screen.getByRole("heading", { name: "More models" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Quay lại" }));
    expect(moreRow()).toHaveFocus();

    await userEvent.click(moreRow());
    await userEvent.click(row(HAIKU.display_name));
    expect(onPick).toHaveBeenCalledWith(HAIKU.id);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("52. model không có `reasoning` ⇒ hàng ② `aria-disabled`, lý do in THẲNG dưới nhãn, bấm không sang màn con", async () => {
    renderView({ account: QWEN.id });
    await openPicker();
    const r = effortRow();
    expect(r).toHaveAttribute("aria-disabled", "true");
    expect(r).toHaveTextContent("Model này không có tuỳ chọn suy luận");
    await userEvent.click(r);
    expect(screen.getByRole("heading", { name: "Chọn mô hình" })).toBeInTheDocument();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("53. sheet giữ MỘT chiều cao cho cả ba màn (`h-sheet-screen`, trần `max-h-sheet-max`)", async () => {
    renderView();
    await openPicker();
    const sheet = screen.getByRole("dialog");
    expect(sheet).toHaveClass("h-sheet-screen", "max-h-sheet-max");
    await userEvent.click(effortRow());
    expect(screen.getByRole("dialog")).toBe(sheet);
  });
});

// ───────────── Khoá riêng — model của endpoint tự nhập (T-S.19c, bản T-HD10 4a/4b) ─────────────

describe("Khoá riêng", () => {
  const ENDPOINT: ByokEndpoint = {
    id: "e1d2c3b4-0000-4000-8000-000000000001",
    label: "Groq nhóm dữ liệu",
    base_url: "https://api.groq.com/openai/v1",
    masked_key: "gsk_...4321",
    models: ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"],
    verified_at: null,
    created_at: "2026-10-01T02:00:00Z",
    usable: true,
    prompt_tokens: 0,
    completion_tokens: 0,
  };
  const OWN = endpointModels([ENDPOINT, { ...ENDPOINT, id: "hong", label: "Hỏng", usable: false }]);
  const LLAMA = `byok:${ENDPOINT.id}/llama-3.3-70b-versatile`;

  it("54. nhóm 'Khoá riêng' xếp CUỐI More models: tên model + tên endpoint, không host; endpoint hỏng khoá bị bỏ", async () => {
    const { onPick } = renderView({ models: [...FOUR, ...OWN] });
    await openMoreModels();

    const list = screen.getByRole("listbox");
    const group = within(list).getByRole("group", { name: "Khoá riêng" });
    const own = within(group).getAllByRole("option");
    expect(own.map((o) => o.textContent)).toEqual([
      "llama-3.3-70b-versatileGroq nhóm dữ liệu",
      "openai/gpt-oss-120bGroq nhóm dữ liệu",
    ]);
    expect(list.textContent).not.toContain("api.groq.com");
    expect(list.textContent).not.toContain("Hỏng");
    expect(within(list).getAllByRole("option").indexOf(own[0])).toBe(FOUR.length);

    await userEvent.click(own[0]);
    expect(onPick).toHaveBeenCalledWith(LLAMA);
  });

  it("55. đang dùng model khoá riêng: khối Giá thành MỘT dòng; Thinking Effort mờ, tooltip nêu lý do", async () => {
    renderView({ models: [...FOUR, ...OWN], conversation: LLAMA });
    await openPicker();

    const panel = pickerPanel() as HTMLElement;
    expect(within(panel).getByText("Khoá riêng — không tính phí")).toBeInTheDocument();
    expect(within(panel).queryByText("Giá")).toBeNull();
    expect(panel.textContent).not.toContain("$");
    expect(within(panel).getByText("Groq nhóm dữ liệu")).toBeInTheDocument();
    expect(effortRow()).toHaveAttribute("aria-disabled", "true");
    await userEvent.hover(effortRow());
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Scarlet không gửi mức suy luận tới endpoint tuỳ chỉnh",
    );
  });

  it("56. 375 px: lý do in thẳng dưới nhãn Thinking Effort, khối Giá một dòng", async () => {
    narrowScreen();
    renderView({ models: [...FOUR, ...OWN], conversation: LLAMA });
    await openPicker();

    expect(effortRow()).toHaveTextContent("Scarlet không gửi mức suy luận tới endpoint tuỳ chỉnh");
    expect(screen.getByText("Khoá riêng — không tính phí")).toBeInTheDocument();
  });
});
