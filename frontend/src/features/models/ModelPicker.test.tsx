/**
 * `ModelPicker` + `chonMacDinh` — T-3.6.
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

import type { ModelRa } from "../../lib/api";
import { chonMacDinh } from "./macDinh";
import { ModelPicker } from "./ModelPicker";

/** Lý do khoá — dài, có dấu, đúng hình dạng câu server trả (bản T-HD4). */
const LY_DO =
  "9Router (local) đang không phản hồi, nên các model của nguồn này tạm thời " +
  "không chọn được. Hãy thử lại sau ít phút, hoặc xem mục Hệ thống để biết chi tiết.";

function model(p: Partial<ModelRa> & Pick<ModelRa, "id">): ModelRa {
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
const TAT = model({
  id: "nr-gemini-flash",
  display_name: "Gemini Flash (qua 9Router)",
  provider: "9Router (local)",
  capabilities: ["tools"],
  badge: "9Router",
  available: false,
  unavailable_reason: LY_DO,
});
const QWEN = model({
  id: "ol-qwen-small",
  display_name: "Qwen2.5 0.5B (Ollama)",
  provider: "Ollama (self-host)",
  badge: "Self-host",
});

const BON = [RE, HAIKU, TAT, QWEN];

function ve(
  tuyChon: {
    models?: ModelRa[];
    hoiThoai?: string | null;
    taiKhoan?: string | null;
    dangLamMoi?: boolean;
  } = {},
) {
  const models = tuyChon.models ?? BON;
  const onChon = vi.fn();
  const onLamMoi = vi.fn();
  render(
    <ModelPicker
      models={models}
      macDinh={chonMacDinh(models, {
        hoiThoai: tuyChon.hoiThoai ?? null,
        taiKhoan: tuyChon.taiKhoan ?? null,
      })}
      nhanDocLuc="14:32"
      dangLamMoi={tuyChon.dangLamMoi}
      onLamMoi={onLamMoi}
      onChon={onChon}
    />,
  );
  return { onChon, onLamMoi };
}

async function moPicker(): Promise<void> {
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
function hang(ten: string): HTMLElement {
  // Bó trong `listbox`: nút mở picker CŨNG in tên model đang chọn, nên một
  // `getByText` trên cả màn hình khớp hai phần tử cho đúng model ấy.
  const o = within(screen.getByRole("listbox")).getByText(ten).closest('[role="option"]');
  if (o === null) {
    throw new Error(`khong tim thay hang cho "${ten}"`);
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

// ───────────────────── `chonMacDinh` — ba tầng (UC-05 dòng 4) ────────────────

describe("chonMacDinh — ba tầng", () => {
  it("1. không tầng nào đặt ⇒ rơi về `default: true` của catalog", () => {
    const r = chonMacDinh(BON, { hoiThoai: null, taiKhoan: null });
    expect(r.modelId).toBe(RE.id);
    expect(r.tang).toBe("catalog");
  });

  it("2. chỉ tầng tài khoản ⇒ tài khoản thắng catalog", () => {
    const r = chonMacDinh(BON, { hoiThoai: null, taiKhoan: QWEN.id });
    expect(r.modelId).toBe(QWEN.id);
    expect(r.tang).toBe("taiKhoan");
  });

  it("3. cả hai tầng ⇒ hội thoại thắng tài khoản", () => {
    const r = chonMacDinh(BON, { hoiThoai: HAIKU.id, taiKhoan: QWEN.id });
    expect(r.modelId).toBe(HAIKU.id);
    expect(r.tang).toBe("hoiThoai");
  });

  it("4. Cạm bẫy ① — `default_model` của user trỏ vào model đã biến mất khỏi catalog ⇒ rơi về catalog, KHÔNG trả id trần", () => {
    const r = chonMacDinh(BON, { hoiThoai: null, taiKhoan: "model-da-bi-xoa" });
    expect(r.modelId).toBe(RE.id);
    expect(r.tang).toBe("catalog");
    expect(r.theoTang.taiKhoan).toBeNull();
  });

  it("5. Cạm bẫy ① — `default_model` của HỘI THOẠI biến mất ⇒ rơi xuống tầng tài khoản chứ không xuống thẳng catalog", () => {
    const r = chonMacDinh(BON, { hoiThoai: "model-da-bi-xoa", taiKhoan: QWEN.id });
    expect(r.modelId).toBe(QWEN.id);
    expect(r.tang).toBe("taiKhoan");
  });

  it("6. model không khả dụng VẪN được chọn làm mặc định (Cạm bẫy ③ — 9Router bật lại sau vài phút)", () => {
    const r = chonMacDinh(BON, { hoiThoai: TAT.id, taiKhoan: null });
    expect(r.modelId).toBe(TAT.id);
    expect(r.tang).toBe("hoiThoai");
  });

  it("7. catalog không có `default` nào ⇒ lấy model đầu tiên theo `order`, không trả `null`", () => {
    const r = chonMacDinh([HAIKU, QWEN], { hoiThoai: null, taiKhoan: null });
    expect(r.modelId).toBe(HAIKU.id);
    expect(r.tang).toBeNull();
  });

  it("8. danh sách rỗng ⇒ `null`, không ném", () => {
    const r = chonMacDinh([], { hoiThoai: "bat-ky", taiKhoan: "bat-ky" });
    expect(r.modelId).toBeNull();
    expect(r.tang).toBeNull();
  });
});

// ──────────────── Hàng `available: false` — DoD dòng 3 ───────────────────────

describe("model không khả dụng", () => {
  it("9. mục đó `aria-disabled`", async () => {
    ve();
    await moPicker();
    expect(hang(TAT.display_name)).toHaveAttribute("aria-disabled", "true");
  });

  it("10. bấm KHÔNG đổi model", async () => {
    const { onChon } = ve();
    await moPicker();
    await userEvent.click(hang(TAT.display_name));
    expect(onChon).not.toHaveBeenCalled();
  });

  it("11. Enter và Space cũng KHÔNG đổi model (Cạm bẫy ③ — không chỉ mờ đi)", async () => {
    const { onChon } = ve();
    await moPicker();
    hang(TAT.display_name).focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onChon).not.toHaveBeenCalled();
  });

  it("12. hover ⇒ tooltip là `unavailable_reason` NGUYÊN VĂN, không cắt", async () => {
    ve();
    await moPicker();
    await userEvent.hover(hang(TAT.display_name));
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(LY_DO);
  });

  it("13. desktop — `aria-describedby` chỉ tồn tại khi tooltip MỞ, và nó trỏ vào một `id` CÓ THẬT", async () => {
    ve();
    await moPicker();
    // Đóng: không được trỏ vào một id không có trong DOM.
    expect(hang(TAT.display_name)).not.toHaveAttribute("aria-describedby");

    await userEvent.hover(hang(TAT.display_name));
    await screen.findByRole("tooltip");
    const id = hang(TAT.display_name).getAttribute("aria-describedby");
    expect(id).not.toBeNull();
    expect(document.getElementById(id as string)).toHaveTextContent(LY_DO);
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
    ve();
    await moPicker();

    const h = hang(TAT.display_name);
    const id = h.getAttribute("aria-describedby");
    expect(id).not.toBeNull();
    expect(document.getElementById(id as string)).toHaveTextContent(LY_DO);
  });

  it("15. hàng khoá vẫn nằm trong tab order (`tabIndex 0`, KHÔNG `disabled`)", async () => {
    ve();
    await moPicker();
    expect(hang(TAT.display_name)).toHaveAttribute("tabindex", "0");
  });

  it("16. model khả dụng thì bấm ĐỔI được — phép kiểm ngược của ca 10", async () => {
    const { onChon } = ve();
    await moPicker();
    await userEvent.click(hang(HAIKU.display_name));
    expect(onChon).toHaveBeenCalledWith(HAIKU.id);
  });
});

// ───────────────────────── Badge capability (§9.4) ──────────────────────────

describe("badge và capability", () => {
  it("17. ba capability của §9.4 hiện bằng nhãn tiếng Việt", async () => {
    ve();
    await moPicker();
    const h = within(hang(RE.display_name));
    expect(h.getByText("Công cụ")).toBeInTheDocument();
    expect(h.getByText("Hình ảnh")).toBeInTheDocument();
    expect(h.getByText("Suy luận")).toBeInTheDocument();
  });

  it("18. `badge` của catalog hiện NGUYÊN VĂN, không dịch", async () => {
    ve();
    await moPicker();
    expect(within(hang(RE.display_name)).getByText("Mặc định · Rẻ")).toBeInTheDocument();
  });

  it("19. model không có capability nào ⇒ nói ra, không để trống", async () => {
    ve();
    await moPicker();
    expect(
      within(hang(QWEN.display_name)).getByText("Không có khả năng đặc biệt"),
    ).toBeInTheDocument();
  });

  it("20. capability lạ (catalog sửa nóng) hiện chuỗi thô chứ không làm vỡ hàng", async () => {
    const la = model({ id: "x-la", display_name: "Model la", capabilities: ["telepathy"] });
    ve({ models: [la] });
    await moPicker();
    expect(within(hang("Model la")).getByText("telepathy")).toBeInTheDocument();
  });
});

// ──────────────────── Chip tầng + strip trạng thái (T-HD4) ──────────────────

describe("tầng mặc định và strip trạng thái", () => {
  it("21. ba tầng vẽ ba chip khác nhau, đúng hàng", async () => {
    ve({ hoiThoai: HAIKU.id, taiKhoan: QWEN.id });
    await moPicker();
    expect(within(hang(HAIKU.display_name)).getByText("Mặc định hội thoại")).toBeInTheDocument();
    expect(within(hang(QWEN.display_name)).getByText("Mặc định tài khoản")).toBeInTheDocument();
    expect(within(hang(RE.display_name)).getByText("Mặc định catalog")).toBeInTheDocument();
  });

  it("22. dấu tích theo model ĐANG CHỌN, chip theo TẦNG — hai thông tin tách nhau", async () => {
    ve({ hoiThoai: HAIKU.id, taiKhoan: QWEN.id });
    await moPicker();
    expect(hang(HAIKU.display_name)).toHaveAttribute("aria-selected", "true");
    expect(hang(QWEN.display_name)).toHaveAttribute("aria-selected", "false");
    // QWEN có chip (tầng tài khoản) mà KHÔNG được chọn — đúng ca bản T-HD4 mô tả.
    expect(within(hang(QWEN.display_name)).getByText("Mặc định tài khoản")).toBeInTheDocument();
  });

  it("23. nút mở in tầng của model đang dùng ở dòng thứ hai", () => {
    ve({ hoiThoai: HAIKU.id });
    const nut = screen.getByRole("button", { name: "Chọn mô hình" });
    expect(within(nut).getByText("Claude Haiku 4.5")).toBeInTheDocument();
    expect(within(nut).getByText("Mặc định hội thoại")).toBeInTheDocument();
  });

  it("24. mốc giờ và câu chữ là HAI phần tử cạnh nhau, không phải một chuỗi ghép", async () => {
    ve();
    await moPicker();
    expect(screen.getByText("Trạng thái kiểm lúc")).toBeInTheDocument();
    expect(screen.getByText("14:32")).toBeInTheDocument();
  });

  it("25. bấm nút làm mới gọi `onLamMoi` đúng một lần", async () => {
    const { onLamMoi } = ve();
    await moPicker();
    await userEvent.click(screen.getByRole("button", { name: "Kiểm lại trạng thái" }));
    expect(onLamMoi).toHaveBeenCalledTimes(1);
  });

  it("26. đang làm mới ⇒ `aria-busy` + nhãn đổi, và danh sách VẪN bấm được", async () => {
    const { onChon } = ve({ dangLamMoi: true });
    await moPicker();
    const nut = screen.getByRole("button", { name: "Đang kiểm lại trạng thái" });
    expect(nut).toHaveAttribute("aria-busy", "true");

    await userEvent.click(hang(HAIKU.display_name));
    expect(onChon).toHaveBeenCalledWith(HAIKU.id);
  });

  it("27. chỗ chừa cho cảnh báo capability (T-4.5) có mặt và rỗng", async () => {
    const { container } = render(
      <ModelPicker
        models={BON}
        macDinh={chonMacDinh(BON, { hoiThoai: null, taiKhoan: null })}
        nhanDocLuc="14:32"
        onLamMoi={vi.fn()}
        onChon={vi.fn()}
      />,
    );
    await userEvent.click(within(container).getByRole("button", { name: "Chọn mô hình" }));
    const cho = document.querySelector('[data-slot="capability-warning"]');
    expect(cho).not.toBeNull();
    expect(cho).toBeEmptyDOMElement();
  });

  it("28. KHÔNG có id model nào lọt vào DOM — component chỉ hiện `display_name`", async () => {
    ve();
    await moPicker();
    for (const m of BON) {
      expect(screen.queryByText(m.id)).toBeNull();
    }
  });
});
