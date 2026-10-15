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

// ─────────────── T-9.8 (B-415) — lam moi phien khi `401` ───────────────

/**
 * May chu gia o tang `fetch`: `session` = cookie phien con song. `/auth/refresh`
 * dem so lan goi va bat lai phien (hoac `401` khi `refreshFails`); route thuong
 * tra `401 <expiredCode>` khi phien chet. Moi response di qua mot vong `await`
 * de cac loi goi song song xen nhau nhu tren mang that.
 */
function fakeServer(opts: {
  expiredCode?: string;
  refreshFails?: boolean;
  /** Route thuong `401` ca sau khi refresh (cookie khong dat duoc). */
  alwaysExpired?: boolean;
}) {
  const state = { session: false, refreshCalls: 0, calls: 0 };
  const unauthorized = (code: string) => respond(401, { error: { code, message: "x" } });
  fakeFetch.mockImplementation(async (url: string, init?: RequestInit) => {
    state.calls += 1;
    if (state.calls > 50) {
      throw new Error("vong lap request");
    }
    await Promise.resolve();
    if (url === "/api/v1/auth/refresh") {
      state.refreshCalls += 1;
      if (opts.refreshFails) {
        return unauthorized("UNAUTHENTICATED");
      }
      state.session = true;
      return respond(200, {});
    }
    if (url === "/api/v1/auth/me") {
      return state.session ? respond(200, {}) : unauthorized("UNAUTHENTICATED");
    }
    if (url === "/api/v1/auth/login") {
      return unauthorized("UNAUTHENTICATED");
    }
    if (!state.session || opts.alwaysExpired) {
      return unauthorized(opts.expiredCode ?? "UNAUTHENTICATED");
    }
    return respond(init?.method === "POST" ? 202 : 200, { ok: url });
  });
  return state;
}

describe("T-9.8 lam moi phien", () => {
  it("`TOKEN_EXPIRED` ⇒ mot `POST /auth/refresh` roi request goc chay lai, ket qua ve nguoi goi", async () => {
    const server = fakeServer({ expiredCode: "TOKEN_EXPIRED" });

    await expect(api.getConversation("abc")).resolves.toEqual({ ok: "/api/v1/conversations/abc" });

    expect(server.refreshCalls).toBe(1);
    expect(urlOfCall(0)).toBe("/api/v1/conversations/abc");
    expect(urlOfCall(fakeFetch.mock.calls.length - 1)).toBe("/api/v1/conversations/abc");
    expect(initOfCall(2).method).toBe("POST");
  });

  it("`UNAUTHENTICATED` (trinh duyet da xoa cookie phien) ⇒ cung lam moi va thu lai", async () => {
    const server = fakeServer({ expiredCode: "UNAUTHENTICATED" });

    await expect(api.getConversation("abc")).resolves.toEqual({ ok: "/api/v1/conversations/abc" });
    expect(server.refreshCalls).toBe(1);
  });

  it("`TOKEN_REVOKED` ⇒ khong refresh, loi ve nguoi goi", async () => {
    const server = fakeServer({ expiredCode: "TOKEN_REVOKED" });

    await expect(api.getConversation("abc")).rejects.toMatchObject({ status: 401, code: "TOKEN_REVOKED" });
    expect(server.refreshCalls).toBe(0);
    expect(fakeFetch).toHaveBeenCalledTimes(1);
  });

  it("`/auth/login` `401` ⇒ khong refresh", async () => {
    const server = fakeServer({});

    await expect(api.login("a@b.c", "sai")).rejects.toMatchObject({ status: 401 });
    expect(server.refreshCalls).toBe(0);
  });

  it("5 request cung hong ⇒ MOT refresh, ca 5 co ket qua", async () => {
    const server = fakeServer({});
    const ids = ["a", "b", "c", "d", "e"];

    const results = await Promise.all(ids.map((id) => api.getConversation(id)));

    expect(results).toEqual(ids.map((id) => ({ ok: `/api/v1/conversations/${id}` })));
    expect(server.refreshCalls).toBe(1);
  });

  it("refresh `401` ⇒ loi GOC, khong vong lap", async () => {
    const server = fakeServer({ expiredCode: "TOKEN_EXPIRED", refreshFails: true });

    await expect(api.getConversation("abc")).rejects.toMatchObject({ status: 401, code: "TOKEN_EXPIRED" });
    expect(server.refreshCalls).toBe(1);
    // request goc, `me()` trong khoa, `refresh` — het.
    expect(fakeFetch).toHaveBeenCalledTimes(3);
  });

  it("refresh `200` ma request van `401` ⇒ thu lai DUNG mot lan roi dung", async () => {
    const server = fakeServer({ expiredCode: "TOKEN_EXPIRED", alwaysExpired: true });

    await expect(api.getConversation("abc")).rejects.toMatchObject({ status: 401, code: "TOKEN_EXPIRED" });
    expect(server.refreshCalls).toBe(1);
    expect(fakeFetch.mock.calls.filter(([u]) => u === "/api/v1/conversations/abc")).toHaveLength(2);
  });

  it("request thu lai giu nguyen `Idempotency-Key` (A8)", async () => {
    fakeServer({});

    await api.sendMessage("conv", { content: "chao" }, "khoa-1");

    const sends = fakeFetch.mock.calls.filter(([u]) => u === "/api/v1/conversations/conv/messages");
    expect(sends).toHaveLength(2);
    for (const [, init] of sends) {
      expect((init as RequestInit).headers).toMatchObject({ "Idempotency-Key": "khoa-1" });
      expect((init as RequestInit).body).toBe(JSON.stringify({ content: "chao" }));
    }
  });

  describe("hai tab (hai ban module) chung `navigator.locks` gia", () => {
    beforeEach(() => {
      // Khoa noi tiep: callback sau chay khi callback truoc xong — dung hop dong Web Locks.
      let chain: Promise<unknown> = Promise.resolve();
      const locks = {
        request: (_name: string, callback: () => Promise<unknown>) => {
          const run = chain.then(callback);
          chain = run.catch(() => undefined);
          return run;
        },
      };
      Object.defineProperty(navigator, "locks", { value: locks, configurable: true });
    });

    afterEach(() => {
      Reflect.deleteProperty(navigator, "locks");
      vi.resetModules();
    });

    it("mot refresh; tab thu hai thay `me()` `200` ⇒ khong refresh", async () => {
      const server = fakeServer({});
      vi.resetModules();
      const tabA = (await import("./api")).api;
      vi.resetModules();
      const tabB = (await import("./api")).api;
      expect(tabA).not.toBe(tabB);

      await Promise.all([tabA.getConversation("a"), tabB.getConversation("b")]);

      expect(server.refreshCalls).toBe(1);
      // Moi tab hoi `me()` trong khoa: tab A thay `401` ⇒ refresh, tab B thay `200`.
      expect(fakeFetch.mock.calls.filter(([u]) => u === "/api/v1/auth/me")).toHaveLength(2);
    });
  });

  it("SSE loi luc phien het han ⇒ refresh roi mo lai voi cursor cuoi", async () => {
    const server = fakeServer({});
    const order: string[] = [];
    class FakeEventSource extends EventTarget {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      static all: FakeEventSource[] = [];
      readyState = FakeEventSource.CONNECTING;
      constructor(readonly url: string) {
        super();
        FakeEventSource.all.push(this);
        order.push(`es:${url}`);
      }
      close() {
        this.readyState = FakeEventSource.CLOSED;
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource);
    const serve = fakeFetch.getMockImplementation();
    fakeFetch.mockImplementation((url: string, init?: RequestInit) => {
      order.push(url);
      return serve?.(url, init);
    });
    const { openStream } = await import("./sse");
    const deltas: string[] = [];

    const handle = openStream({
      url: "/api/v1/messages/m/stream",
      beforeReconnect: api.me,
      onEvent: (e) => {
        if (e.event === "delta") deltas.push(e.data.t);
      },
    });
    const first = FakeEventSource.all[0];
    first.dispatchEvent(new MessageEvent("delta", { data: JSON.stringify({ t: "Xin " }), lastEventId: "5-0" }));
    // Phien het han: server `401`, trinh duyet bo cuoc — chi la `error` khong `data` (Cam bay ⑥).
    first.readyState = FakeEventSource.CLOSED;
    first.dispatchEvent(new Event("error"));

    await vi.waitFor(() => expect(FakeEventSource.all).toHaveLength(2), { timeout: 3000 });
    const second = FakeEventSource.all[1];
    second.dispatchEvent(new MessageEvent("delta", { data: JSON.stringify({ t: "chao" }), lastEventId: "6-0" }));
    handle.close();

    expect(server.refreshCalls).toBe(1);
    expect(second.url).toBe("/api/v1/messages/m/stream?cursor=5-0");
    expect(order.indexOf("/api/v1/auth/refresh")).toBeLessThan(order.indexOf(`es:${second.url}`));
    // Khong mat chu, khong lap chu.
    expect(deltas).toEqual(["Xin ", "chao"]);
  });
});
