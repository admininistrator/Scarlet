/**
 * O nhap — DoD dong 2 cua T-3.4, va ca cac cam bay cua task.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  HAI KHANG DINH NGUOC CHIEU NHAU, VA VI SAO PHAI CO CA HAI             ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * DoD viet ro: *"go → gui hong (mock 500) → bam gui lai ⇒ **cung**
 * `Idempotency-Key`; gui thanh cong → go cau moi ⇒ khoa **khac**. Hai khang
 * dinh nguoc chieu nhau; thieu mot cai thi test xanh ca voi ban sinh khoa moi
 * moi lan goi."*
 *
 * Doc nguoc lai cung dung: chi co ve "khoa khac" thi mot ban **khong bao gio
 * doi khoa** cung xanh. Nen ca 2 va ca 3 phai di cung nhau, va chung duoc
 * viet canh nhau o day de khong ai xoa mot cai ma khong thay cai con lai.
 *
 * ── Hai tang, hai cau hoi khac nhau ──────────────────────────────────────
 *
 * `describe("Composer")` render **mot minh** component va dem khoa o bien
 * `onGui`. No tra loi: *"chu so huu khoa co giu dung ba luat cua C22
 * khong"*.
 *
 * `describe("Composer qua useChat")` cam them `useChat` that va mot
 * `api.guiTinNhan` gia, roi doc **tham so thu ba** cua loi goi ay. No tra
 * loi cau khac han: *"khoa ay co di nguyen ven toi header HTTP khong"* — va
 * do la cho DoD noi "mock 500", vi chi o tang nay moi co mot response de
 * mock. Mot trong hai tang khong du: tang tren khong chung minh gi ve HTTP,
 * tang duoi khong chung minh gi ve luc nao khoa duoc sinh.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const that = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...that,
    api: {
      ...that.api,
      danhSachModel: vi.fn(),
      docHoiThoai: vi.fn(),
      guiTinNhan: vi.fn(),
    },
  };
});

/**
 * jsdom khong co `EventSource`, nen `moStream` that se nem ngay dong dau.
 * Cai dang duoc do o day la khoa, khong phai stream — T-1.14 da do stream.
 *
 * Ban gia van giu lai `onSuKien` cua lan mo gan nhat, vi mot thu can no:
 * sau mot `202` man hinh chuyen sang trang thai "dang chay" va nut Gui bien
 * thanh Dung (UC-02 dong 2). Muon go mot cau THU HAI thi luot sinh thu nhat
 * phai ket thuc, ma §7.4 noi ro chi `done`/`error` dong duoc mot luot —
 * khong mot bo dem thoi gian nao (Cam bay ③). Nen test phai phat `done`.
 */
const suKienCuaStream: { phat: ((suKien: SuKienStream) => void) | null } = { phat: null };

vi.mock("../../lib/sse", async (importOriginal) => {
  const that = await importOriginal<typeof import("../../lib/sse")>();
  return {
    ...that,
    moStream: vi.fn((thamSo: { onSuKien: (suKien: SuKienStream) => void }) => {
      suKienCuaStream.phat = thamSo.onSuKien;
      return { dong: vi.fn(), cursor: () => "" };
    }),
  };
});

import { ApiError, api, type HoiThoaiChiTiet, type TaoMessageRa } from "../../lib/api";
import type { SuKienStream } from "../../lib/sse";
import { useChat, type KetQuaGui } from "../../features/chat/useChat";
import { Composer } from "./Composer";

const TRAN = 24000;
const ID_HOI_THOAI = "11111111-1111-4111-8111-111111111111";

/** Dang cua mot UUID v4 — de khang dinh khoa la khoa chu khong phai chuoi rong. */
const DANG_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function veComposer(
  onGui: (noiDung: string, khoa: string) => Promise<KetQuaGui>,
  thayDoi: Partial<{ dangChay: boolean; moDuoc: boolean; tranKyTu: number | null }> = {},
) {
  const onDung = vi.fn();
  render(
    <Composer
      dangChay={thayDoi.dangChay ?? false}
      moDuoc={thayDoi.moDuoc ?? true}
      tranKyTu={thayDoi.tranKyTu === undefined ? TRAN : thayDoi.tranKyTu}
      onGui={onGui}
      onDung={onDung}
    />,
  );
  return { onDung };
}

const oNhap = () => screen.getByRole("textbox");
const nutGui = () => screen.getByRole("button", { name: "Gửi" });

describe("Composer", () => {
  it("1. sinh khoa khi o nhap chuyen tu rong sang co chu, khong som hon", async () => {
    const khoa: string[] = [];
    veComposer(async (_n, k) => {
      khoa.push(k);
      return "da-gui";
    });

    await userEvent.type(oNhap(), "xin chao");
    await userEvent.click(nutGui());

    expect(khoa).toHaveLength(1);
    expect(khoa[0]).toMatch(DANG_UUID);
  });

  /**
   * Ca am cua DoD, ve thu nhat. Mot ban sinh khoa moi o moi lan `gui()` se
   * DO o dong cuoi — va do la toan bo diem cua C22.
   */
  it("2. gui hong roi bam gui lai ⇒ CUNG mot Idempotency-Key", async () => {
    const khoa: string[] = [];
    let ketQua: KetQuaGui = "hong";
    veComposer(async (_n, k) => {
      khoa.push(k);
      return ketQua;
    });

    await userEvent.type(oNhap(), "1+1 bang may?");
    await userEvent.click(nutGui());
    // Gui hong: chu PHAI con nguyen, neu khong thi khong con gi de bam lan hai.
    expect(oNhap()).toHaveValue("1+1 bang may?");

    ketQua = "da-gui";
    await userEvent.click(nutGui());

    expect(khoa).toHaveLength(2);
    expect(khoa[1]).toBe(khoa[0]);
  });

  /** Ca am cua DoD, ve thu hai. Mot ban khong bao gio doi khoa se DO o day. */
  it("3. gui thanh cong roi go cau moi ⇒ khoa KHAC", async () => {
    const khoa: string[] = [];
    veComposer(async (_n, k) => {
      khoa.push(k);
      return "da-gui";
    });

    await userEvent.type(oNhap(), "cau mot");
    await userEvent.click(nutGui());
    expect(oNhap()).toHaveValue("");

    await userEvent.type(oNhap(), "cau hai");
    await userEvent.click(nutGui());

    expect(khoa).toHaveLength(2);
    expect(khoa[1]).not.toBe(khoa[0]);
  });

  it("4. xoa sach o nhap la bo lan soan thao ⇒ cau sau mang khoa khac", async () => {
    const khoa: string[] = [];
    veComposer(async (_n, k) => {
      khoa.push(k);
      return "hong";
    });

    await userEvent.type(oNhap(), "abc");
    await userEvent.click(nutGui());
    await userEvent.clear(oNhap());
    await userEvent.type(oNhap(), "xyz");
    await userEvent.click(nutGui());

    expect(khoa[1]).not.toBe(khoa[0]);
  });

  /* ── Duong thoat khoi 409 IN_PROGRESS — B-143, Cam bay ① ──────────────── */

  it("5. 409 IN_PROGRESS ⇒ hien duong thoat, va no gui bang khoa MOI", async () => {
    const khoa: string[] = [];
    let ketQua: KetQuaGui = "ket-khoa";
    veComposer(async (_n, k) => {
      khoa.push(k);
      return ketQua;
    });

    await userEvent.type(oNhap(), "cau bi ket");
    await userEvent.click(nutGui());

    const thoat = await screen.findByRole("button", { name: "Gửi lại bằng khoá mới" });
    ketQua = "da-gui";
    await userEvent.click(thoat);

    expect(khoa).toHaveLength(2);
    expect(khoa[1]).not.toBe(khoa[0]);
    expect(khoa[1]).toMatch(DANG_UUID);
    // Da thoat ra that: o nhap sach, bang canh bao bien mat.
    expect(oNhap()).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Gửi lại bằng khoá mới" })).toBeNull();
  });

  it("6. mot loi THUONG (500) KHONG duoc hien duong thoat — C22 van cam doi khoa", async () => {
    veComposer(async () => "hong");

    await userEvent.type(oNhap(), "cau hong");
    await userEvent.click(nutGui());

    expect(screen.queryByRole("button", { name: "Gửi lại bằng khoá mới" })).toBeNull();
  });

  /* ── Dem ky tu — A3/L4, B-205/NQ-78 ──────────────────────────────────── */

  it("7. dem nguoc ve `message_max_chars` lay tu prop, khong mot con so nao o FE", async () => {
    veComposer(async () => "da-gui", { tranKyTu: 10 });

    expect(screen.getByRole("status")).toHaveTextContent("0 / 10");
    await userEvent.type(oNhap(), "abcde");
    expect(screen.getByRole("status")).toHaveTextContent("5 / 10");
  });

  it("8. go vuot tran ⇒ nut Gui `disabled` (DoD dong 5)", async () => {
    veComposer(async () => "da-gui", { tranKyTu: 5 });

    await userEvent.type(oNhap(), "12345");
    expect(nutGui()).toBeEnabled();

    await userEvent.type(oNhap(), "6");
    expect(screen.getByRole("status")).toHaveTextContent("6 / 5");
    expect(nutGui()).toBeDisabled();
  });

  it("9. `tranKyTu === null` la 'chua biet tran', khong phai 'tran = 0'", async () => {
    const khoa: string[] = [];
    veComposer(
      async (_n, k) => {
        khoa.push(k);
        return "da-gui";
      },
      { tranKyTu: null },
    );

    await userEvent.type(oNhap(), "van go duoc");
    expect(screen.queryByRole("status")).toBeNull();
    expect(nutGui()).toBeEnabled();
    await userEvent.click(nutGui());
    expect(khoa).toHaveLength(1);
  });

  /* ── Phim: Enter gui · Shift+Enter xuong dong (chot o T-3.4) ─────────── */

  it("10. Enter gui; Shift+Enter xuong dong chu khong gui", async () => {
    const goi = vi.fn(async (_noiDung: string, _khoa: string) => "da-gui" as KetQuaGui);
    veComposer(goi);

    await userEvent.type(oNhap(), "dong mot{Shift>}{Enter}{/Shift}dong hai");
    expect(goi).not.toHaveBeenCalled();
    expect(oNhap()).toHaveValue("dong mot\ndong hai");

    await userEvent.type(oNhap(), "{Enter}");
    expect(goi).toHaveBeenCalledTimes(1);
    expect(goi.mock.calls[0][0]).toBe("dong mot\ndong hai");
  });

  /**
   * Bo go tieng Viet (Telex/VNI) dung Enter de chot tu dang dung, va su kien
   * ay mang `isComposing = true`. Gui o day la gui nham nua cau.
   */
  it("11. Enter trong luc bo go dang dung tu (`isComposing`) KHONG gui", async () => {
    const goi = vi.fn(async (_noiDung: string, _khoa: string) => "da-gui" as KetQuaGui);
    veComposer(goi);

    await userEvent.type(oNhap(), "tieng viet");
    // `userEvent` khong dung duoc IME, nen ban phim di thang qua `fireEvent`.
    act(() => {
      oNhap().dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true, isComposing: true }),
      );
    });

    expect(goi).not.toHaveBeenCalled();
  });

  /* ── Nut Gui ⇄ Dung (UC-02 dong 2, Cam bay ③) ────────────────────────── */

  it("12. `dangChay` ⇒ nut la Dung, va no goi `onDung`", async () => {
    const { onDung } = veComposer(async () => "da-gui", { dangChay: true });

    expect(screen.queryByRole("button", { name: "Gửi" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Dừng" }));
    expect(onDung).toHaveBeenCalledTimes(1);
  });

  it("13. o nhap rong hoac chua mo hoi thoai ⇒ khong gui duoc", async () => {
    const goi = vi.fn(async (_noiDung: string, _khoa: string) => "da-gui" as KetQuaGui);
    veComposer(goi);

    expect(nutGui()).toBeDisabled();
    // Chi co dau cach cung khong phai mot cau hoi.
    await userEvent.type(oNhap(), "   ");
    expect(nutGui()).toBeDisabled();
    await userEvent.type(oNhap(), "{Enter}");
    expect(goi).not.toHaveBeenCalled();
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   Tang hai: khoa cua `Composer` di toi header HTTP nguyen ven hay khong.
   ══════════════════════════════════════════════════════════════════════════ */

const HOI_THOAI: HoiThoaiChiTiet = {
  id: ID_HOI_THOAI,
  title: null,
  default_model: null,
  system_prompt_override: null,
  active_leaf_id: null,
  pinned: false,
  created_at: "2026-09-22T00:00:00+00:00",
  updated_at: "2026-09-22T00:00:00+00:00",
  path: [],
};

const DA_TAO: TaoMessageRa = {
  user_message_id: "22222222-2222-4222-8222-222222222222",
  assistant_message_id: "33333333-3333-4333-8333-333333333333",
  stream_url: "/api/v1/messages/33333333-3333-4333-8333-333333333333/stream",
  branched: false,
};

/** Dung `useChat` that, nhu `ChatScreen` dung no. */
function ManChatToiThieu() {
  const chat = useChat();
  return (
    <Composer
      dangChay={chat.dangChay !== null}
      moDuoc={chat.cay.conversationId !== null && !chat.dangBan}
      tranKyTu={TRAN}
      onGui={chat.gui}
      onDung={() => void chat.dung()}
    />
  );
}

/** Tham so thu ba cua `api.guiTinNhan` la `Idempotency-Key`. */
function khoaDaGui(lan: number): string {
  return vi.mocked(api.guiTinNhan).mock.calls[lan][2];
}

/** §7.4 — chi `done` dong duoc mot luot sinh, va man hinh doc dung no. */
async function ketThucLuotSinh(): Promise<void> {
  act(() => {
    suKienCuaStream.phat?.({ event: "done", data: { finish_reason: "stop", usage: null } });
  });
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Gửi" })).toBeInTheDocument();
  });
}

describe("Composer qua useChat", () => {
  beforeEach(async () => {
    suKienCuaStream.phat = null;
    window.history.replaceState(null, "", `/?c=${ID_HOI_THOAI}`);
    vi.mocked(api.danhSachModel).mockResolvedValue([]);
    vi.mocked(api.docHoiThoai).mockResolvedValue(HOI_THOAI);
    render(<ManChatToiThieu />);
    // `useChat` mo hoi thoai cua `?c=` luc mount; truoc do `moDuoc` la false.
    await waitFor(() => {
      expect(screen.getByRole("textbox")).toBeEnabled();
    });
  });

  /**
   * DoD dong 2 do dung o day: `500` la mot response that di qua `ApiError`,
   * khong phai mot chuoi `"hong"` do test tu nghi ra.
   */
  it("14. mock 500 roi bam gui lai ⇒ header `Idempotency-Key` khong doi", async () => {
    vi.mocked(api.guiTinNhan)
      .mockRejectedValueOnce(new ApiError(500, "INTERNAL", "loi may chu"))
      .mockResolvedValueOnce(DA_TAO);

    await userEvent.type(oNhap(), "cau hoi");
    await userEvent.click(nutGui());
    await waitFor(() => {
      expect(api.guiTinNhan).toHaveBeenCalledTimes(1);
    });

    await userEvent.click(nutGui());
    await waitFor(() => {
      expect(api.guiTinNhan).toHaveBeenCalledTimes(2);
    });

    expect(khoaDaGui(1)).toBe(khoaDaGui(0));
    expect(khoaDaGui(0)).toMatch(DANG_UUID);
    // Lan hai la lan `202`: o nhap sach, khoa bi bo.
    await waitFor(() => {
      expect(oNhap()).toHaveValue("");
    });

    vi.mocked(api.guiTinNhan).mockResolvedValueOnce(DA_TAO);
    await ketThucLuotSinh();
    await userEvent.type(oNhap(), "cau hoi khac");
    await userEvent.click(nutGui());
    await waitFor(() => {
      expect(api.guiTinNhan).toHaveBeenCalledTimes(3);
    });
    expect(khoaDaGui(2)).not.toBe(khoaDaGui(0));
  });

  it("15. `409 IN_PROGRESS` ⇒ duong thoat hien ra, va no doi khoa", async () => {
    vi.mocked(api.guiTinNhan)
      .mockRejectedValueOnce(new ApiError(409, "IN_PROGRESS", "dang chay"))
      .mockResolvedValueOnce(DA_TAO);

    await userEvent.type(oNhap(), "cau bi ket");
    await userEvent.click(nutGui());

    const thoat = await screen.findByRole("button", { name: "Gửi lại bằng khoá mới" });
    await userEvent.click(thoat);
    await waitFor(() => {
      expect(api.guiTinNhan).toHaveBeenCalledTimes(2);
    });

    expect(khoaDaGui(1)).not.toBe(khoaDaGui(0));
  });

  /**
   * `GENERATION_IN_PROGRESS` (409 cua `retry` — mot MESSAGE dang sinh) khong
   * phai `IN_PROGRESS` (409 cua §11.4 — mot KHOA dang bi giu). Gop hai ma nay
   * lai la mo duong thoat cho mot ca ma doi khoa khong sua duoc gi.
   */
  it("16. `409 GENERATION_IN_PROGRESS` KHONG mo duong thoat", async () => {
    vi.mocked(api.guiTinNhan).mockRejectedValueOnce(
      new ApiError(409, "GENERATION_IN_PROGRESS", "luot cu chua xong"),
    );

    await userEvent.type(oNhap(), "cau hoi");
    await userEvent.click(nutGui());
    await waitFor(() => {
      expect(api.guiTinNhan).toHaveBeenCalledTimes(1);
    });

    expect(screen.queryByRole("button", { name: "Gửi lại bằng khoá mới" })).toBeNull();
  });
});
