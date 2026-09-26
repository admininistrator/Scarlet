/**
 * Ba loi goi hoi thoai ma T-3.3 them/sua — do o TANG DAY, khong o tang `api`.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO CAN FILE NAY KHI `Sidebar.test.tsx` DA MOCK `api`               ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `Sidebar.test.tsx` thay ca doi tuong `api`, nen no chung minh duoc *sidebar
 * goi dung ham voi dung tham so* — va khong chung minh duoc gi ve **chuoi URL
 * that di ra day**. Do dung la thu DoD dong 3 cua T-3.3 nhin vao:
 *
 *     DevTools → Network thay dung `?updated_before=<con tro cua trang truoc>`
 *
 * `next_cursor` la mot `datetime` co mui gio, tuc no chua dau `+`. Noi thang
 * vao URL thi server doc `+` thanh mot **dau cach** va tra `422` — mot loi chi
 * hien ra o trinh duyet that, dung luc nguoi dung bam "Tai them" lan dau.
 *
 * `fetch` bi thay chu khong phai mot may chu that: cai dang do la **request
 * FE dung len**, khong phai cau tra loi cua backend (`tests/api/` cua backend
 * lo phan ay).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

const fakeFetch = vi.fn();

function respond(status: number, body: unknown = null): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

/** URL cua lan goi `fetch` thu `n` (dem tu 0). */
function urlOfCall(n: number): string {
  return String(fakeFetch.mock.calls[n][0]);
}

function initOfCall(n: number): RequestInit {
  return fakeFetch.mock.calls[n][1] as RequestInit;
}

beforeEach(() => {
  vi.stubGlobal("fetch", fakeFetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("danhSachHoiThoai", () => {
  const empty = { items: [], next_cursor: null, truncated: false };

  it("T-S.13: hai nguon — `?pinned=true` (du, khong trang) va `?pinned=false` (trang dau)", async () => {
    fakeFetch.mockResolvedValue(respond(200, empty));

    await api.listConversations({ pinned: true });
    await api.listConversations({ pinned: false });

    expect(urlOfCall(0)).toBe("/api/v1/conversations?pinned=true");
    expect(urlOfCall(1)).toBe("/api/v1/conversations?pinned=false");
  });

  it("co con tro ⇒ `?updated_before=`, va dau `+` cua mui gio duoc ma hoa", async () => {
    fakeFetch.mockResolvedValue(respond(200, empty));

    await api.listConversations({
      pinned: false,
      updatedBefore: "2026-09-02T03:04:05.678901+00:00",
    });

    // `+` ⇒ `%2B`. Khong ma hoa thi server doc ra mot dau cach va tra 422.
    expect(urlOfCall(0)).toBe(
      "/api/v1/conversations?pinned=false&updated_before=2026-09-02T03%3A04%3A05.678901%2B00%3A00",
    );
  });

  it("`null` duoc doi xu nhu vang mat (khong gui `updated_before=null`)", async () => {
    fakeFetch.mockResolvedValue(respond(200, empty));

    await api.listConversations({ pinned: false, updatedBefore: null });

    expect(urlOfCall(0)).toBe("/api/v1/conversations?pinned=false");
  });
});

describe("titleStreamUrl", () => {
  it("T-S.13: duong SSE cua tieu de nam duoi `/api/v1` — khop location SSE cua nginx", () => {
    expect(api.titleStreamUrl("abc")).toBe("/api/v1/conversations/abc/title/stream");
    expect(fakeFetch).not.toHaveBeenCalled();
  });
});

describe("suaHoiThoai", () => {
  it("chi gui DUNG nhung truong nguoi goi dat — vang mat khac `null`", async () => {
    fakeFetch.mockResolvedValue(respond(200, {}));

    await api.updateConversation("abc", { pinned: true });
    expect(initOfCall(0).method).toBe("PATCH");
    expect(JSON.parse(String(initOfCall(0).body))).toEqual({ pinned: true });

    await api.updateConversation("abc", { title: null });
    // `title: null` = "xoa tieu de". No PHAI di ra day, khong bi `JSON.stringify`
    // bo mat — do la khac biet giua "xoa tieu de" va "dung dung toi tieu de".
    expect(JSON.parse(String(initOfCall(1).body))).toEqual({ title: null });

    await api.updateConversation("abc", { default_model: "mot-model" });
    expect(JSON.parse(String(initOfCall(2).body))).toEqual({ default_model: "mot-model" });
  });
});

describe("xoaHoiThoai", () => {
  it("`DELETE` va nuot duoc `204` (khong body de `json()` doc)", async () => {
    fakeFetch.mockResolvedValue(respond(204));

    await expect(api.deleteConversation("abc")).resolves.toBeUndefined();

    expect(urlOfCall(0)).toBe("/api/v1/conversations/abc");
    expect(initOfCall(0).method).toBe("DELETE");
  });

  it("`404` (xoa lan hai) ⇒ `ApiError` mang `code` cua §18", async () => {
    fakeFetch.mockResolvedValue(
      respond(404, { error: { code: "CONVERSATION_NOT_FOUND", message: "khong tim thay" } }),
    );

    await expect(api.deleteConversation("abc")).rejects.toMatchObject({
      status: 404,
      code: "CONVERSATION_NOT_FOUND",
    });
  });
});
