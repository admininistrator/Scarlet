/**
 * Hang nam nut duoi cau tra loi — DoD dong 1 cua T-3.7.
 *
 * File nay do HAI tang, va chung tra loi hai cau khac nhau:
 *
 *   `describe("hang nut")`   — bam mot nut thi component GOI GI. Spy la
 *                              `vi.fn()`, khong co mang.
 *   `describe("duong ra HTTP")` — cung nhung nut ay, nhung `onThuLai` /
 *                              `onDanhGia` noi vao `api` THAT (chi `fetch` bi
 *                              thay). Day la cho dong DoD *"Retry goi dung
 *                              endpoint"* va *"gui `model_id` khac"* duoc do:
 *                              mot spy khong biet gi ve chuoi URL that.
 *
 * Doan noi o tang hai chep dung mot dong cua `useChat.thuLai`/`danhGia`. No
 * khong the lech trong im lang: `tsc` buoc ca hai ben dung mot chu ky, va chu
 * ky ay (`thuLai(messageId, body, khoa)`) la thu B-231 vua doi.
 *
 * KH tham chieu: UC-02, UC-04, §18.2, §11.4 · tasks.md T-3.7, B-231, B-244.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type DanhGia } from "../../lib/api";
import { NutDuoiCauTraLoi } from "./NutDuoiCauTraLoi";

const MODEL_CU = "model-da-sinh-ra-cau-nay";
const MODEL_DANG_CHON = "model-dang-chon-tren-picker";
const ID = "msg-1";

const ghiClipboard = vi.fn<(chu: string) => Promise<void>>(() => Promise.resolve());

beforeEach(() => {
  // `navigator.clipboard` khong ton tai trong jsdom (cung ly do no khong ton
  // tai ngoai secure context — xem `lib/clipboard.ts`).
  vi.stubGlobal("navigator", { clipboard: { writeText: ghiClipboard } });
});

function ve(chen: Partial<Parameters<typeof NutDuoiCauTraLoi>[0]> = {}) {
  const props = {
    chu: "noi dung cau tra loi",
    feedback: null,
    modelDangDung: MODEL_CU,
    modelDangChon: MODEL_DANG_CHON,
    onDanhGia: vi.fn(),
    onThuLai: vi.fn(),
    onThuLaiModel: vi.fn(),
    ...chen,
  };
  return { ...render(<NutDuoiCauTraLoi {...props} />), props };
}

/**
 * `fireEvent` chu khong `userEvent` — khac voi `Composer.test.tsx`, va co ly do.
 *
 * `userEvent.setup()` **tu dat mot ban gia cua `navigator.clipboard`** de mo
 * phong copy/paste cua ban phim; o file nay chinh `navigator.clipboard` la thu
 * dang duoc do, nen no se do ban gia cua thu vien chu khong phai lan goi cua
 * `lib/clipboard.ts`. `fireEvent` khong cham vao `navigator`.
 */
function bam(ten: string): void {
  fireEvent.click(screen.getByRole("button", { name: ten }));
}

describe("hang nut", () => {
  it("Copy dua DUNG noi dung cau tra loi vao clipboard", async () => {
    ve({ chu: "hai dong\nva mot `code`" });

    bam("Sao chép");
    await vi.waitFor(() => expect(ghiClipboard).toHaveBeenCalledWith("hai dong\nva mot `code`"));
    await screen.findByRole("button", { name: "Đã sao chép" });
  });

  it("Thich lan dau gui 'like'", () => {
    const { props } = ve({ feedback: null });

    bam("Thích");

    expect(props.onDanhGia).toHaveBeenCalledWith("like");
  });

  it("bam Thich HAI lan ⇒ lan hai GO danh gia (`null`)", () => {
    /*
      Trang thai di vong qua chinh `feedback` cua props — dung duong ma
      `MessageRa` di qua that. Mot `useState` ben trong component se lam ca
      nay xanh ma van sai: F5 se tat nut vua bam.
    */
    const daGui: (DanhGia | null)[] = [];
    function Bao() {
      const [gia, setGia] = useState<DanhGia | null>(null);
      return (
        <NutDuoiCauTraLoi
          chu="x"
          feedback={gia}
          modelDangDung={MODEL_CU}
          modelDangChon={null}
          onDanhGia={(moi) => {
            daGui.push(moi);
            setGia(moi);
          }}
          onThuLai={vi.fn()}
          onThuLaiModel={vi.fn()}
        />
      );
    }
    render(<Bao />);

    bam("Thích");
    bam("Đã thích");

    expect(daGui).toEqual(["like", null]);
  });

  it("dang Thich ma bam Khong thich ⇒ DOI gia tri, khong go", () => {
    const { props } = ve({ feedback: "like" });

    bam("Không thích");

    expect(props.onDanhGia).toHaveBeenCalledWith("dislike");
  });

  it("nut sang/toi doc tu prop `feedback`, khong tu state rieng", () => {
    const { rerender } = ve({ feedback: null });
    expect(screen.getByRole("button", { name: "Thích" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    rerender(
      <NutDuoiCauTraLoi
        chu="x"
        feedback="like"
        modelDangDung={MODEL_CU}
        modelDangChon={null}
        onDanhGia={vi.fn()}
        onThuLai={vi.fn()}
        onThuLaiModel={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Đã thích" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("Thu lai tron KHONG kem model nao", () => {
    const { props } = ve();

    bam("Thử lại");

    expect(props.onThuLai).toHaveBeenCalledTimes(1);
    expect(props.onThuLai).toHaveBeenCalledWith();
    expect(props.onThuLaiModel).not.toHaveBeenCalled();
  });

  it("'Doi model & thu lai' gui model KHAC model da sinh ra cau tra loi", () => {
    const { props } = ve({ modelDangDung: MODEL_CU, modelDangChon: MODEL_DANG_CHON });

    bam("Đổi model & thử lại");

    expect(props.onThuLaiModel).toHaveBeenCalledWith(MODEL_DANG_CHON);
    expect(props.onThuLaiModel).not.toHaveBeenCalledWith(MODEL_CU);
  });

  it("nut doi model TAT khi picker dang chi dung model cu", () => {
    ve({ modelDangDung: MODEL_CU, modelDangChon: MODEL_CU });

    expect(screen.getByRole("button", { name: "Đổi model & thử lại" })).toBeDisabled();
  });

  it("nut doi model TAT khi chua biet model nao dang chon", () => {
    ve({ modelDangChon: null });

    expect(screen.getByRole("button", { name: "Đổi model & thử lại" })).toBeDisabled();
  });
});

// ────────────────── tang hai: chuoi URL that di ra day ──────────────────

const fetchGia = vi.fn();

function traVe(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function initLanGoi(n: number): RequestInit {
  return fetchGia.mock.calls[n][1] as RequestInit;
}

describe("duong ra HTTP", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchGia);
    fetchGia.mockResolvedValue(traVe(202, {}));
  });

  afterEach(() => {
    fetchGia.mockReset();
  });

  /** Noi y het `useChat`: nut tron khong truyen model, nut kia truyen. */
  function veThat(feedback: DanhGia | null = null) {
    return render(
      <NutDuoiCauTraLoi
        chu="x"
        feedback={feedback}
        modelDangDung={MODEL_CU}
        modelDangChon={MODEL_DANG_CHON}
        onDanhGia={(gia) => void api.danhGia(ID, gia)}
        onThuLai={() => void api.thuLai(ID, {}, "khoa-cua-lan-bam")}
        onThuLaiModel={(modelId) => void api.thuLai(ID, { model_id: modelId }, "khoa-cua-lan-bam")}
      />,
    );
  }

  it("Thu lai ⇒ `POST /messages/{id}/retry` kem `Idempotency-Key` (B-231)", () => {
    veThat();

    bam("Thử lại");

    expect(String(fetchGia.mock.calls[0][0])).toBe(`/api/v1/messages/${ID}/retry`);
    const init = initLanGoi(0);
    expect(init.method).toBe("POST");
    // Thieu header nay la `400 IDEMPOTENCY_KEY_REQUIRED` ke tu NQ-93.
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBe("khoa-cua-lan-bam");
    expect(init.body).toBe("{}");
  });

  it("'Doi model & thu lai' ⇒ cung endpoint, body mang `model_id` KHAC", () => {
    veThat();

    bam("Đổi model & thử lại");

    expect(String(fetchGia.mock.calls[0][0])).toBe(`/api/v1/messages/${ID}/retry`);
    const daGui = JSON.parse(String(initLanGoi(0).body)) as { model_id: string };
    expect(daGui.model_id).toBe(MODEL_DANG_CHON);
    expect(daGui.model_id).not.toBe(MODEL_CU);
  });

  it("Thich ⇒ `POST /messages/{id}/feedback` `{value:'like'}`, KHONG khoa §11.4", () => {
    fetchGia.mockResolvedValue(traVe(200, { message_id: ID, feedback: "like", feedback_reason: null }));
    veThat();

    bam("Thích");

    expect(String(fetchGia.mock.calls[0][0])).toBe(`/api/v1/messages/${ID}/feedback`);
    expect(initLanGoi(0).body).toBe('{"value":"like"}');
    // A8 noi ve POST **tao tai nguyen**; day la `UPDATE` hai cot tren mot hang
    // da co, nen no khong vao `ROUTE_BAT_BUOC_IDEMPOTENCY` (T-3.7a).
    expect(initLanGoi(0).headers).not.toHaveProperty("Idempotency-Key");
  });

  it("go danh gia ⇒ `{value:null}` TUONG MINH, khong phai body rong", () => {
    fetchGia.mockResolvedValue(traVe(200, { message_id: ID, feedback: null, feedback_reason: null }));
    veThat("like");

    bam("Đã thích");

    // Backend khai `value` la truong bat buoc: mot body rong la `422`, va do
    // la co y — xem `DanhGiaRequest` cua T-3.7a.
    expect(initLanGoi(0).body).toBe('{"value":null}');
  });
});
