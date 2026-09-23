/**
 * Thanh quota — DoD dong 4 cua T-3.11, va ca bon Cam bay cua task.
 *
 * DoD: *"21% ⇒ khong canh bao; 20% ⇒ canh bao; 0% ⇒ nut `disabled`. Hai ca o
 * hai ben nguong, khong phai mot ca o giua."* Mot ban viet `<` thay `<=` (hoac
 * nguong lech mot) chi DO o dung cap 20/21 — mot ca 10% thi xanh voi ca hai.
 *
 * ── Ba tang ──────────────────────────────────────────────────────────────
 *
 * `describe("nguong")` ve `QuotaBar` CANH `Composer`, noi voi nhau bang dung
 * `quotaBlock` + `isSendBlocked` ma `ChatScreen` dung — tuc cau "nut co
 * disabled khong" duoc hoi o chinh cai nut, khong o mot ham.
 *
 * `describe("hai nguon")` kiem luat ghep `/auth/me` + `202` (Cam bay ④).
 *
 * `describe("nhip lam tuoi")` cam `useChat` that: `done` va `429` phai goi
 * lai `/auth/me`, va nut gui phai tu khoa **ma khong can F5** — DoD dong 1
 * o tang test.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
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
      listProviderKeys: vi.fn(),
    },
  };
});

/** jsdom khong co `EventSource` — giu `onSuKien` de test tu phat `done`. */
const stream: { phat: ((suKien: SuKienStream) => void) | null } = { phat: null };

vi.mock("../../lib/sse", async (importOriginal) => {
  const that = await importOriginal<typeof import("../../lib/sse")>();
  return {
    ...that,
    moStream: vi.fn((thamSo: { onSuKien: (suKien: SuKienStream) => void }) => {
      stream.phat = thamSo.onSuKien;
      return { dong: vi.fn(), cursor: () => "" };
    }),
  };
});

import {
  ApiError,
  api,
  type CuaSoQuota,
  type HoSoRa,
  type HoiThoaiChiTiet,
  type QuotaWarning,
} from "../../lib/api";
import type { SuKienStream } from "../../lib/sse";
import { Composer } from "../../components/chat/Composer";
import { useChat } from "../chat/useChat";
import { QuotaBar } from "./ThanhQuota";
import {
  byokCovers,
  isSendBlocked,
  mergeReadings,
  quotaBlock,
  type QuotaReading,
} from "./quotaView";
import { useQuota } from "./useQuota";

/** Nguong cua `.env.example` (`QUOTA_WARN_REMAINING_PCT`) — den qua `/auth/me`. */
const NGUONG = 20;
const DOC_LUC = new Date(2026, 8, 23, 14, 0, 0).getTime();
const PROVIDER = "deepseek";

function cuaSo(thayDoi: Partial<CuaSoQuota> = {}): CuaSoQuota {
  return {
    limit_type: "5h",
    limit_usd: "0.5000",
    spent_usd: "0.1000",
    remaining_usd: "0.4000",
    remaining_pct: 80,
    retry_after: null,
    ...thayDoi,
  };
}

function docTai(...cacCuaSo: CuaSoQuota[]): QuotaReading[] {
  return cacCuaSo.map((window) => ({ window, readAt: DOC_LUC }));
}

/**
 * `QuotaBar` + `Composer`, noi bang DUNG hai ham cua `ChatScreen`. Nut gui
 * chi bat khi co chu, nen moi ca go san mot cau truoc khi hoi nut.
 */
async function ve(readings: QuotaReading[], byok: ReadonlySet<string> | null = new Set()) {
  const block = quotaBlock(readings);
  render(
    <Composer
      dangChay={false}
      moDuoc
      tranKyTu={null}
      onGui={vi.fn()}
      onDung={vi.fn()}
      quotaBlocked={isSendBlocked(block, byok, PROVIDER)}
      quotaBar={
        <QuotaBar
          readings={readings}
          warnPct={NGUONG}
          block={block}
          byokCovered={byokCovers(byok, PROVIDER)}
          now={DOC_LUC}
        />
      }
    />,
  );
  await userEvent.type(screen.getByRole("textbox"), "cau hoi");
}

const nutGui = () => screen.getByRole("button", { name: "Gửi" });
const canhBao = () => screen.queryByText(/Sắp hết hạn mức/);

describe("nguong canh bao va nut gui", () => {
  it("1. con 21% ⇒ KHONG canh bao, nut gui bat", async () => {
    await ve(docTai(cuaSo({ remaining_pct: 21, remaining_usd: "0.1050" })));

    expect(canhBao()).toBeNull();
    expect(screen.getByText("21%").closest("[data-level]")).toHaveAttribute("data-level", "normal");
    expect(nutGui()).toBeEnabled();
  });

  it("2. con 20% ⇒ canh bao, va KHONG chan (UC-07 dong 1)", async () => {
    await ve(docTai(cuaSo({ remaining_pct: 20, remaining_usd: "0.1000" })));

    expect(canhBao()).not.toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("20%");
    expect(screen.getByText("20%").closest("[data-level]")).toHaveAttribute(
      "data-level",
      "warning",
    );
    expect(nutGui()).toBeEnabled();
  });

  it("3. con 0% ⇒ nut gui disabled + thoi diem hoan lai CHINH XAC toi giay", async () => {
    // 14:00:00 + 754 s = 14:12:34 — cung phep cong `readAt + retry_after`.
    await ve(docTai(cuaSo({ remaining_pct: 0, remaining_usd: "0", retry_after: 754 })));

    expect(nutGui()).toBeDisabled();
    const baoHet = screen.getByRole("alert");
    expect(baoHet).toHaveTextContent("Đã dùng hết hạn mức 5 giờ");
    expect(baoHet).toHaveTextContent("14:12:34");
    expect(baoHet.querySelector("time")).toHaveAttribute(
      "dateTime",
      new Date(DOC_LUC + 754_000).toISOString(),
    );
    // Het roi thi khong con "sap het" — mot thong diep, khong hai.
    expect(canhBao()).toBeNull();
  });

  it("4. het CA HAI cua so ⇒ moc hoan lai la moc MUON NHAT", async () => {
    await ve(
      docTai(
        cuaSo({ remaining_pct: 0, retry_after: 60 }),
        cuaSo({ limit_type: "weekly", remaining_pct: 0, retry_after: 7200 }),
      ),
    );

    expect(nutGui()).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("5 giờ và 7 ngày");
    expect(screen.getByRole("alert")).toHaveTextContent("16:00:00");
  });

  it("5. het ma KHONG biet luc nao hoan lai ⇒ noi dung nhu vay, khong bia gio", async () => {
    await ve(docTai(cuaSo({ limit_usd: "0", remaining_pct: 0, retry_after: null })));

    expect(nutGui()).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Chưa xác định");
    expect(screen.getByRole("alert").querySelector("time")).toBeNull();
  });
});

/** Cam bay ① — BYOK van gui duoc khi het quota system key (UC-07 dong 4). */
describe("BYOK", () => {
  it("6. het quota nhung model dang chon di bang khoa rieng ⇒ nut VAN bat", async () => {
    await ve(docTai(cuaSo({ remaining_pct: 0, retry_after: 60 })), new Set([PROVIDER]));

    expect(nutGui()).toBeEnabled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("khoá API riêng");
  });

  it("7. khoa rieng cua provider KHAC ⇒ van khoa", async () => {
    await ve(docTai(cuaSo({ remaining_pct: 0, retry_after: 60 })), new Set(["anthropic"]));

    expect(nutGui()).toBeDisabled();
  });

  it("8. chua biet co khoa rieng hay khong (loi tai) ⇒ KHONG khoa nham", async () => {
    await ve(docTai(cuaSo({ remaining_pct: 0, retry_after: 60 })), null);

    expect(nutGui()).toBeEnabled();
  });
});

/** Cam bay ④ — hai nguon, MOT con so moi cua so. */
describe("hai nguon", () => {
  const canhBao202: QuotaWarning = {
    limit_type: "5h",
    limit_usd: "0.5000",
    spent_usd: "0.4200",
    remaining_usd: "0.0800",
    remaining_pct: 16,
  };

  it("9. `202` MOI hon `/auth/me` ⇒ thay dung cua so ay, cua so kia giu nguyen", () => {
    const ra = mergeReadings(
      [cuaSo({ remaining_pct: 40 }), cuaSo({ limit_type: "weekly", remaining_pct: 90 })],
      DOC_LUC,
      { "5h": { warning: canhBao202, readAt: DOC_LUC + 5000 } },
    );

    expect(ra.map((r) => r.window.remaining_pct)).toEqual([16, 90]);
    expect(ra[0].readAt).toBe(DOC_LUC + 5000);
    // `202` = da qua cua chan ⇒ khong co gi de cho.
    expect(ra[0].window.retry_after).toBeNull();
  });

  it("10. `202` CU hon lan doc `/auth/me` ⇒ bi bo qua", () => {
    const ra = mergeReadings([cuaSo({ remaining_pct: 12 })], DOC_LUC, {
      "5h": { warning: canhBao202, readAt: DOC_LUC - 1 },
    });

    expect(ra.map((r) => r.window.remaining_pct)).toEqual([12]);
  });

  it("11. man hinh hien MOT con so moi cua so, kem gio doc", async () => {
    await ve(docTai(cuaSo({ remaining_pct: 16, remaining_usd: "0.0800" })));

    expect(screen.getAllByRole("meter")).toHaveLength(1);
    expect(screen.getAllByText("16%")).toHaveLength(1);
    expect(screen.getByText(/Số liệu lúc/)).toHaveTextContent("14:00:00");
  });

  it("12. `quota: null` (Redis chop) ⇒ AN thanh, khong ve mot thanh rong", () => {
    const { container } = render(
      <QuotaBar readings={mergeReadings(null, DOC_LUC, {})} warnPct={NGUONG} block={null} byokCovered={false} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

/* ── Nhip lam tuoi: `done`/`error`/`429`, khong bo dem thoi gian ───────────── */

const ID_HOI_THOAI = "11111111-1111-4111-8111-111111111111";
const HOI_THOAI: HoiThoaiChiTiet = {
  id: ID_HOI_THOAI,
  title: null,
  default_model: null,
  system_prompt_override: null,
  active_leaf_id: null,
  pinned: false,
  created_at: "2026-09-23T00:00:00Z",
  updated_at: "2026-09-23T00:00:00Z",
  path: [],
};

function hoSo(quota: CuaSoQuota[]): HoSoRa {
  return {
    id: "u1",
    email: "a@scarlet.example",
    display_name: null,
    status: "active",
    role: "user",
    tier_name: "free",
    default_model: null,
    quota,
    message_max_chars: 24000,
    quota_warn_remaining_pct: NGUONG,
  };
}

/**
 * Ban thu nho cua `ChatScreen`: `useQuota` + `useChat` + hai component, noi
 * dung nhu ban that. `refreshProfile` doc ho so tiep theo tu `hangDoi`.
 */
const hangDoi: HoSoRa[] = [];
const refreshSpy = vi.fn();

function ManChatCoQuota({ dau }: { dau: HoSoRa }) {
  const [ho, setHo] = useState(dau);
  const [docLuc, setDocLuc] = useState(Date.now());
  const refreshProfile = async () => {
    refreshSpy();
    const ke = hangDoi.shift();
    if (ke !== undefined) {
      setHo(ke);
      setDocLuc(Date.now());
    }
  };
  const quota = useQuota({ hoSo: ho, profileReadAt: docLuc, refreshProfile });
  const chat = useChat({
    models: [],
    modelMacDinhTaiKhoan: null,
    onQuotaWarning: quota.noteWarning,
    onQuotaStale: () => void refreshProfile(),
  });
  return (
    <Composer
      dangChay={chat.dangChay !== null}
      moDuoc={chat.cay.conversationId !== null && !chat.dangBan}
      tranKyTu={null}
      onGui={chat.gui}
      onDung={() => void chat.dung()}
      quotaBlocked={isSendBlocked(quota.block, quota.byokProviders, null)}
      quotaBar={
        <QuotaBar readings={quota.readings} warnPct={quota.warnPct} block={quota.block} byokCovered={false} />
      }
    />
  );
}

describe("nhip lam tuoi", () => {
  beforeEach(async () => {
    stream.phat = null;
    hangDoi.length = 0;
    refreshSpy.mockClear();
    window.history.replaceState(null, "", `/?c=${ID_HOI_THOAI}`);
    vi.mocked(api.docHoiThoai).mockResolvedValue(HOI_THOAI);
    vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [] });
    vi.mocked(api.guiTinNhan).mockReset();
    render(<ManChatCoQuota dau={hoSo([cuaSo({ remaining_pct: 60 })])} />);
    await waitFor(() => {
      expect(screen.getByRole("textbox")).toBeEnabled();
    });
  });

  it("13. `done` ⇒ doc lai `/auth/me` ⇒ nut gui tu khoa, KHONG can F5 (DoD dong 1)", async () => {
    vi.mocked(api.guiTinNhan).mockResolvedValueOnce({
      user_message_id: "m1",
      assistant_message_id: "m2",
      stream_url: "/api/v1/messages/m2/stream",
      branched: false,
      quota_warning: null,
    });
    hangDoi.push(hoSo([cuaSo({ remaining_pct: 0, retry_after: 300 })]));

    await userEvent.type(screen.getByRole("textbox"), "cau hoi");
    await userEvent.click(nutGui());
    await waitFor(() => expect(stream.phat).not.toBeNull());
    expect(refreshSpy).not.toHaveBeenCalled();

    act(() => {
      stream.phat?.({ event: "done", data: { finish_reason: "stop", usage: null } });
    });

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Đã dùng hết"));
    expect(refreshSpy).toHaveBeenCalledTimes(1);
    await userEvent.type(screen.getByRole("textbox"), "cau nua");
    expect(nutGui()).toBeDisabled();
  });

  it("14. `202` mang `quota_warning` ⇒ canh bao hien ngay, truoc ca `done`", async () => {
    vi.mocked(api.guiTinNhan).mockResolvedValueOnce({
      user_message_id: "m1",
      assistant_message_id: "m2",
      stream_url: "/api/v1/messages/m2/stream",
      branched: false,
      quota_warning: {
        limit_type: "5h",
        limit_usd: "0.5000",
        spent_usd: "0.4200",
        remaining_usd: "0.0800",
        remaining_pct: 16,
      },
    });

    await userEvent.type(screen.getByRole("textbox"), "cau hoi");
    await userEvent.click(nutGui());

    await waitFor(() => expect(canhBao()).not.toBeNull());
    expect(screen.getAllByText("16%")).toHaveLength(1);
    expect(screen.queryByText("60%")).toBeNull();
  });

  it("15. `429 QUOTA_EXCEEDED` khi gui ⇒ doc lai `/auth/me` ngay", async () => {
    vi.mocked(api.guiTinNhan).mockRejectedValueOnce(
      new ApiError(429, "QUOTA_EXCEEDED", "het quota", { limit_type: "5h", retry_after: 300 }),
    );
    hangDoi.push(hoSo([cuaSo({ remaining_pct: 0, retry_after: 300 })]));

    await userEvent.type(screen.getByRole("textbox"), "cau hoi");
    await userEvent.click(nutGui());

    await waitFor(() => expect(nutGui()).toBeDisabled());
    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });

  it("16. loi KHAC quota (500) ⇒ KHONG doc lai — nhip lam tuoi khong phai moi loi", async () => {
    vi.mocked(api.guiTinNhan).mockRejectedValueOnce(new ApiError(500, "INTERNAL", "loi"));

    await userEvent.type(screen.getByRole("textbox"), "cau hoi");
    await userEvent.click(nutGui());

    await waitFor(() => expect(api.guiTinNhan).toHaveBeenCalledTimes(1));
    expect(refreshSpy).not.toHaveBeenCalled();
  });
});
