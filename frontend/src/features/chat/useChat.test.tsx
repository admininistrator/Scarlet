/**
 * `Idempotency-Key` cua nut Thu lai — nua FE cua B-231 (NQ-93).
 *
 * Nua backend (route nay tu nay BAT BUOC header, thieu ⇒ `400`) do
 * `backend/tests/api/test_idempotency.py` canh. File nay canh thu ma **chi**
 * FE quyet dinh duoc, va no la thu lam cho lop kia co tac dung: hai lan bam
 * nhanh phai mang CUNG mot khoa. Sinh khoa moi o moi lan bam la dung cai bay
 * C22 ta — luc do Redis thay hai request khac nhau, va nguoi dung tra hai hoa
 * don cho mot lan bam nham.
 *
 * Ba dong luat duoc do rieng tung dong:
 *
 *   1. sinh o lan bam dau cho mot cap `(message, model)`;
 *   2. GIU nguyen qua moi lan hong;
 *   3. BO khi va chi khi `202` ve — lan bam sau la mot anh em that (§8.2).
 *
 * KH tham chieu: §11.4, §8.2, C22, S5 · tasks.md B-231, T-3.7, T-3.4.
 */

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChat } from "./useChat";
import { api, type HoiThoaiChiTiet, type MessageRa } from "../../lib/api";

vi.mock("../../lib/api", async (goc) => {
  const that = await goc<typeof import("../../lib/api")>();
  return {
    ...that,
    api: {
      docHoiThoai: vi.fn(),
      thuLai: vi.fn(),
      danhGia: vi.fn(),
    },
  };
});

/*
  `moStream` mo mot `EventSource` that — thu khong ton tai trong jsdom. Thay
  no bang mot tay cam rong: file nay do chuoi request di ra, khong do stream.
*/
vi.mock("../../lib/sse", async (goc) => {
  const that = await goc<typeof import("../../lib/sse")>();
  return { ...that, moStream: () => ({ dong: () => {}, cursor: () => "" }) };
});

const HOI_THOAI = "conv-1";
const CAU_TRA_LOI = "msg-assistant";
const MODEL_KHAC = "mot-model-khac";

function node(chen: Partial<MessageRa> = {}): MessageRa {
  return {
    id: CAU_TRA_LOI,
    parent_id: "msg-user",
    role: "assistant",
    status: "completed",
    content: "tra loi",
    reasoning: null,
    model_id: "model-cu",
    finish_reason: "stop",
    error_code: null,
    created_at: "2026-09-22T00:00:00Z",
    sibling_index: 0,
    sibling_count: 1,
    feedback: null,
    ...chen,
  };
}

function chiTiet(): HoiThoaiChiTiet {
  return {
    id: HOI_THOAI,
    title: null,
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: CAU_TRA_LOI,
    pinned: false,
    created_at: "2026-09-22T00:00:00Z",
    updated_at: "2026-09-22T00:00:00Z",
    path: [node({ id: "msg-user", role: "user", parent_id: null }), node()],
  };
}

const docHoiThoai = vi.mocked(api.docHoiThoai);
const thuLai = vi.mocked(api.thuLai);
const danhGia = vi.mocked(api.danhGia);

/** Khoa cua lan goi `api.thuLai` thu `n` — tham so thu ba (B-231). */
function khoaLanGoi(n: number): string {
  return thuLai.mock.calls[n][2];
}

beforeEach(() => {
  docHoiThoai.mockResolvedValue(chiTiet());
  thuLai.mockResolvedValue({
    assistant_message_id: "msg-moi",
    stream_url: "/api/v1/messages/msg-moi/stream",
    model_id: "model-cu",
  });
});

/**
 * Treo lan goi `api.thuLai` KE TIEP lai cho toi khi goi `.nha()`.
 *
 * Mot object chu khong mot bien `let`: TypeScript khong theo duoc phep gan
 * xay ra trong mot callback, nen mot bien se bi thu hep ve `null` ngay dong
 * duoi. Thuoc tinh cua object thi khong.
 */
function giuLaiMotLanGoi(): { nha: () => void } {
  const cho = { nha: () => {} };
  thuLai.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        cho.nha = () =>
          resolve({
            assistant_message_id: "msg-moi",
            stream_url: "/api/v1/messages/msg-moi/stream",
            model_id: "model-cu",
          });
      }),
  );
  return cho;
}

/** Mot hook da mo san mot hoi thoai — `thuLai` khong lam gi khi chua mo. */
async function hookDaMoHoiThoai() {
  const { result } = renderHook(() => useChat());
  await act(async () => {
    await result.current.moHoiThoai(HOI_THOAI);
  });
  return result;
}

describe("khoa idempotency cua nut Thu lai (B-231)", () => {
  it("1 — moi lan goi deu MANG mot khoa (route nay bat buoc tu NQ-93)", async () => {
    const result = await hookDaMoHoiThoai();

    await act(async () => {
      await result.current.thuLai(CAU_TRA_LOI);
    });

    expect(thuLai).toHaveBeenCalledTimes(1);
    expect(khoaLanGoi(0)).toMatch(/\S/);
  });

  it("2 — hai lan bam CHONG LAN dung cung mot khoa (S5, C22)", async () => {
    const result = await hookDaMoHoiThoai();
    /*
      Ca that: nguoi dung bam hai lan truoc khi request dau tra ve. Khoa phai
      la mot — do la toan bo ly do §11.4 ton tai. Giu request dau treo bang
      mot promise chua resolve, dung nhu mang cham.

      Khong can `waitFor`: than mot `async function` chay DONG BO toi `await`
      dau tien, ma `await api.thuLai(...)` la dong ay — nen ca hai lan goi da
      toi noi truoc khi dong lenh ke tiep chay.
    */
    const treo = giuLaiMotLanGoi();

    await act(async () => {
      void result.current.thuLai(CAU_TRA_LOI);
      void result.current.thuLai(CAU_TRA_LOI);
      treo.nha();
    });

    expect(thuLai).toHaveBeenCalledTimes(2);
    expect(khoaLanGoi(0)).toBe(khoaLanGoi(1));
  });

  it("3 — sau `202` thi khoa duoc BO: lan bam sau la mot anh em that (§8.2)", async () => {
    const result = await hookDaMoHoiThoai();

    await act(async () => {
      await result.current.thuLai(CAU_TRA_LOI);
    });
    await act(async () => {
      await result.current.thuLai(CAU_TRA_LOI);
    });

    expect(khoaLanGoi(0)).not.toBe(khoaLanGoi(1));
  });

  it("4 — HONG thi GIU khoa: bam lai van la cung mot y dinh (luat 2)", async () => {
    const result = await hookDaMoHoiThoai();
    thuLai.mockRejectedValueOnce(new Error("mang rot"));

    await act(async () => {
      await result.current.thuLai(CAU_TRA_LOI);
    });
    await act(async () => {
      await result.current.thuLai(CAU_TRA_LOI);
    });

    expect(khoaLanGoi(0)).toBe(khoaLanGoi(1));
  });

  it("5 — hai model KHAC nhau la hai y dinh, tuc hai khoa", async () => {
    const result = await hookDaMoHoiThoai();
    const treo = giuLaiMotLanGoi();

    await act(async () => {
      void result.current.thuLai(CAU_TRA_LOI);
      void result.current.thuLai(CAU_TRA_LOI, MODEL_KHAC);
      treo.nha();
    });

    // Cung mot khoa se lam lan goi thu hai nhan BAN PHAT LAI cua lan dau, tuc
    // "Doi model & thu lai" khong doi duoc model nao ca.
    expect(khoaLanGoi(0)).not.toBe(khoaLanGoi(1));
  });
});

describe("hai nut Thu lai gui hai body khac nhau (T-3.7)", () => {
  it("nut tron KHONG gui `model_id` — backend dung lai model cu", async () => {
    const result = await hookDaMoHoiThoai();

    await act(async () => {
      await result.current.thuLai(CAU_TRA_LOI);
    });

    expect(thuLai.mock.calls[0][1]).toEqual({});
  });

  it("nut 'Doi model' gui dung id duoc truyen vao", async () => {
    const result = await hookDaMoHoiThoai();

    await act(async () => {
      await result.current.thuLai(CAU_TRA_LOI, MODEL_KHAC);
    });

    expect(thuLai.mock.calls[0][1]).toEqual({ model_id: MODEL_KHAC });
  });
});

describe("danhGia doc lai duong di tu server (T-3.7)", () => {
  it("ghi xong thi `GET /conversations/{id}` chay lai — khong tu va vao state", async () => {
    const result = await hookDaMoHoiThoai();
    danhGia.mockResolvedValue({
      message_id: CAU_TRA_LOI,
      feedback: "like",
      feedback_reason: null,
    });
    docHoiThoai.mockClear();

    await act(async () => {
      await result.current.danhGia(CAU_TRA_LOI, "like");
    });

    expect(danhGia).toHaveBeenCalledWith(CAU_TRA_LOI, "like");
    expect(docHoiThoai).toHaveBeenCalledWith(HOI_THOAI);
  });
});
