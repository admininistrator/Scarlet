/**
 * Han muc tren man chat — DoD dong 4 cua T-3.11 o DANG MOI cua T-S.10 (DoD
 * dong 5), va ca bon Cam bay cua T-3.11.
 *
 * DoD: *"21% ⇒ khong co dong canh bao; 20% ⇒ co; 0% ⇒ Gui `disabled`. Hai ca
 * o hai ben nguong, khong phai mot ca o giua."* Mot ban viet `<` thay `<=`
 * (hoac nguong lech mot) chi DO o dung cap 20/21 — mot ca 10% thi xanh voi ca
 * hai.
 *
 * T-S.10 (NQ-114): hai thanh cua `QuotaBar` roi man chat; tren o nhap chi con
 * MOT dong (`QuotaNotice`). T-S.11 dung lai hai thanh o tab Muc su dung theo
 * ban T-HD9 (`components/settings/UsagePanel.tsx`) va xoa `QuotaBar`; ca 11–12
 * doi sang `components/settings/Settings.test.tsx` (ca 17, 19).
 *
 * ── Ba tang ──────────────────────────────────────────────────────────────
 *
 * `describe("nguong")` ve `QuotaNotice` TRONG `Composer`, noi voi nhau bang
 * dung `quotaBlock` + `isSendBlocked` ma `ChatScreen` dung — tuc cau "nut co
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
import { useState, type ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listModels: vi.fn(),
      getConversation: vi.fn(),
      sendMessage: vi.fn(),
      listProviderKeys: vi.fn(),
    },
  };
});

/** jsdom khong co `EventSource` — giu `onEvent` de test tu phat `done`. */
const stream: { emit: ((event: StreamEvent) => void) | null } = { emit: null };

vi.mock("../../lib/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/sse")>();
  return {
    ...actual,
    openStream: vi.fn((params: { onEvent: (event: StreamEvent) => void }) => {
      stream.emit = params.onEvent;
      return { close: vi.fn(), cursor: () => "" };
    }),
  };
});

import {
  ApiError,
  api,
  type QuotaWindow,
  type ProfileOut,
  type ConversationDetail,
  type QuotaWarning,
} from "../../lib/api";
import type { StreamEvent } from "../../lib/sse";
import { Composer } from "../../components/chat/Composer";
import { useChat } from "../chat/useChat";
import { QuotaNotice } from "./QuotaNotice";
import {
  byokCovers,
  isSendBlocked,
  mergeReadings,
  quotaBlock,
  selectedProviderId,
  type QuotaReading,
} from "./quotaView";
import { useQuota } from "./useQuota";

/** Nguong cua `.env.example` (`QUOTA_WARN_REMAINING_PCT`) — den qua `/auth/me`. */
const THRESHOLD = 20;
const READ_AT = new Date(2026, 8, 23, 14, 0, 0).getTime();
const PROVIDER = "deepseek";

function quotaWindow(overrides: Partial<QuotaWindow> = {}): QuotaWindow {
  return {
    limit_type: "5h",
    limit_usd: "0.5000",
    spent_usd: "0.1000",
    remaining_usd: "0.4000",
    remaining_pct: 80,
    retry_after: null,
    ...overrides,
  };
}

function readingsAt(...windows: QuotaWindow[]): QuotaReading[] {
  return windows.map((window) => ({ window, readAt: READ_AT }));
}

/** `QuotaNotice` co `<Link>` sang Muc su dung — can mot router. */
function renderRouted(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

/**
 * `QuotaNotice` trong `Composer`, noi bang DUNG hai ham cua `ChatScreen`. Nut
 * gui chi bat khi co chu, nen moi ca go san mot cau truoc khi hoi nut.
 */
async function renderView(readings: QuotaReading[], byok: ReadonlySet<string> | null = new Set()) {
  const block = quotaBlock(readings);
  renderRouted(
    <Composer
      running={false}
      enabled
      maxChars={null}
      docked
      onSend={vi.fn()}
      onStop={vi.fn()}
      quotaBlocked={isSendBlocked(block, byok, PROVIDER)}
      quotaNotice={
        <QuotaNotice
          readings={readings}
          warnPct={THRESHOLD}
          block={block}
          byokCovered={byokCovers(byok, PROVIDER)}
          now={READ_AT}
        />
      }
    />,
  );
  await userEvent.type(screen.getByRole("textbox"), "cau hoi");
}

const sendButton = () => screen.getByRole("button", { name: "Gửi" });
/** Dong canh bao "Han muc … con N%" (ban T-HD2-v2 muc G4). */
const warning = () => screen.queryByText(/^Hạn mức .* còn/);
/** Dong het han muc (G5). */
const exhausted = () => screen.getByText(/Đã hết hạn mức/);

describe("nguong canh bao va nut gui", () => {
  it("1. con 21% ⇒ KHONG co dong canh bao, nut gui bat", async () => {
    await renderView(readingsAt(quotaWindow({ remaining_pct: 21, remaining_usd: "0.1050" })));

    expect(warning()).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("link", { name: "Xem mức sử dụng" })).toBeNull();
    expect(sendButton()).toBeEnabled();
  });

  it("2. con 20% ⇒ MOT dong canh bao co link sang Muc su dung, va KHONG chan (UC-07 dong 1)", async () => {
    await renderView(readingsAt(quotaWindow({ remaining_pct: 20, remaining_usd: "0.1000" })));

    expect(warning()).not.toBeNull();
    const line = screen.getByRole("status");
    expect(line).toHaveTextContent("Hạn mức 5 giờ còn 20%");
    expect(screen.getByRole("link", { name: "Xem mức sử dụng" })).toHaveAttribute(
      "href",
      "/cai-dat/muc-su-dung",
    );
    // Mot dong, khong hai thanh (NQ-114): khong con `meter` nao tren man chat.
    expect(screen.queryAllByRole("meter")).toHaveLength(0);
    expect(sendButton()).toBeEnabled();
  });

  it("3. con 0% ⇒ nut gui disabled + thoi diem hoan lai CHINH XAC toi giay", async () => {
    // 14:00:00 + 754 s = 14:12:34 — cung phep cong `readAt + retry_after`.
    await renderView(readingsAt(quotaWindow({ remaining_pct: 0, remaining_usd: "0", retry_after: 754 })));

    expect(sendButton()).toBeDisabled();
    const line = screen.getByRole("status");
    expect(line).toHaveTextContent("Đã hết hạn mức 5 giờ");
    expect(line).toHaveTextContent("14:12:34");
    expect(line.querySelector("time")).toHaveAttribute(
      "dateTime",
      new Date(READ_AT + 754_000).toISOString(),
    );
    // Het roi thi khong con "sap het" — mot thong diep, khong hai.
    expect(warning()).toBeNull();
  });

  it("4. het CA HAI cua so ⇒ moc hoan lai la moc MUON NHAT", async () => {
    await renderView(
      readingsAt(
        quotaWindow({ remaining_pct: 0, retry_after: 60 }),
        quotaWindow({ limit_type: "weekly", remaining_pct: 0, retry_after: 7200 }),
      ),
    );

    expect(sendButton()).toBeDisabled();
    expect(exhausted()).toHaveTextContent("5 giờ và 7 ngày");
    expect(exhausted()).toHaveTextContent("16:00:00");
  });

  it("5. het ma KHONG biet luc nao hoan lai ⇒ noi dung nhu vay, khong bia gio", async () => {
    await renderView(readingsAt(quotaWindow({ limit_usd: "0", remaining_pct: 0, retry_after: null })));

    expect(sendButton()).toBeDisabled();
    expect(exhausted()).toHaveTextContent("chưa rõ lúc hoàn lại");
    expect(screen.getByRole("status").querySelector("time")).toBeNull();
  });
});

/** Cam bay ① — BYOK van gui duoc khi het quota system key (UC-07 dong 4). */
describe("BYOK", () => {
  it("6. het quota nhung model dang chon di bang khoa rieng ⇒ nut VAN bat", async () => {
    await renderView(readingsAt(quotaWindow({ remaining_pct: 0, retry_after: 60 })), new Set([PROVIDER]));

    expect(sendButton()).toBeEnabled();
    expect(screen.getByRole("status")).toHaveTextContent("dùng khoá riêng của bạn");
    // Khong noi "hoan lai luc" cho mot nguoi dang gui duoc.
    expect(screen.getByRole("status").querySelector("time")).toBeNull();
  });

  it("7. khoa rieng cua provider KHAC ⇒ van khoa", async () => {
    await renderView(readingsAt(quotaWindow({ remaining_pct: 0, retry_after: 60 })), new Set(["anthropic"]));

    expect(sendButton()).toBeDisabled();
  });

  it("8. chua biet co khoa rieng hay khong (loi tai) ⇒ KHONG khoa nham", async () => {
    await renderView(readingsAt(quotaWindow({ remaining_pct: 0, retry_after: 60 })), null);

    expect(sendButton()).toBeEnabled();
  });

  /*
    B-257 — ba ca tren dua THANG `PROVIDER` vao `isSendBlocked`, nen chung khong
    do duoc cho `ChatScreen` lay provider tu dau. Ca nay di dung duong ay: mot
    `ModelOut` hinh dang that cua `GET /models` (nhan KHAC khoa) va mot tap
    khoa BYOK hinh dang that cua `GET /settings/keys` (khoa catalog).
  */
  it("8b. provider cua model lay theo KHOA catalog, khong theo nhan (B-257)", () => {
    const models = [
      { id: "deepseek-flash", provider: "DeepSeek AI", provider_id: "deepseek" },
      { id: "claude-haiku", provider: "Anthropic", provider_id: "anthropic" },
    ];
    const byokProviders = new Set(["deepseek"]);
    const block = quotaBlock(readingsAt(quotaWindow({ remaining_pct: 0, retry_after: 60 })));

    const provider = selectedProviderId(models, "deepseek-flash");

    expect(provider).toBe("deepseek");
    expect(isSendBlocked(block, byokProviders, provider)).toBe(false);
    expect(byokCovers(byokProviders, provider)).toBe(true);
    // Doi chung: model cua provider KHONG co khoa rieng thi van khoa.
    expect(isSendBlocked(block, byokProviders, selectedProviderId(models, "claude-haiku"))).toBe(true);
    // Model khong co trong danh muc ⇒ khong biet provider ⇒ khoa (server se `429`).
    expect(selectedProviderId(models, "khong-co")).toBeNull();
  });
});

/** Cam bay ④ — hai nguon, MOT con so moi cua so. */
describe("hai nguon", () => {
  const warning202: QuotaWarning = {
    limit_type: "5h",
    limit_usd: "0.5000",
    spent_usd: "0.4200",
    remaining_usd: "0.0800",
    remaining_pct: 16,
  };

  it("9. `202` MOI hon `/auth/me` ⇒ thay dung cua so ay, cua so kia giu nguyen", () => {
    const output = mergeReadings(
      [quotaWindow({ remaining_pct: 40 }), quotaWindow({ limit_type: "weekly", remaining_pct: 90 })],
      READ_AT,
      { "5h": { warning: warning202, readAt: READ_AT + 5000 } },
    );

    expect(output.map((r) => r.window.remaining_pct)).toEqual([16, 90]);
    expect(output[0].readAt).toBe(READ_AT + 5000);
    // `202` = da qua cua chan ⇒ khong co gi de cho.
    expect(output[0].window.retry_after).toBeNull();
  });

  it("10. `202` CU hon lan doc `/auth/me` ⇒ bi bo qua", () => {
    const output = mergeReadings([quotaWindow({ remaining_pct: 12 })], READ_AT, {
      "5h": { warning: warning202, readAt: READ_AT - 1 },
    });

    expect(output.map((r) => r.window.remaining_pct)).toEqual([12]);
  });
});

/* ── Nhip lam tuoi: `done`/`error`/`429`, khong bo dem thoi gian ───────────── */

const CONVERSATION_ID = "11111111-1111-4111-8111-111111111111";
const CONVERSATION: ConversationDetail = {
  id: CONVERSATION_ID,
  title: null,
  default_model: null,
  system_prompt_override: null,
  active_leaf_id: null,
  pinned: false,
  created_at: "2026-09-23T00:00:00Z",
  updated_at: "2026-09-23T00:00:00Z",
  path: [],
};

function profile(quota: QuotaWindow[]): ProfileOut {
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
    quota_warn_remaining_pct: THRESHOLD,
    last_login_at: null,
    limits_cache_ttl_s: 60,
    stream_ttl_s: 3600,
    display_name_max_chars: 64,
    avatar_color: null,
    reasoning_prefs: {},
    max_upload_mb: 10,
    max_attachments: 5,
    allowed_upload_mime: ["image/png", "image/jpeg", "application/pdf", "text/plain"],
  };
}

/**
 * Ban thu nho cua `ChatScreen`: `useQuota` + `useChat` + hai component, noi
 * dung nhu ban that. `refreshProfile` doc ho so tiep theo tu `queue`.
 */
const queue: ProfileOut[] = [];
const refreshSpy = vi.fn();

function ChatWithQuota({ initial }: { initial: ProfileOut }) {
  const [currentProfile, setCurrentProfile] = useState(initial);
  const [loadedAt, setLoadedAt] = useState(Date.now());
  const refreshProfile = async () => {
    refreshSpy();
    const next = queue.shift();
    if (next !== undefined) {
      setCurrentProfile(next);
      setLoadedAt(Date.now());
    }
  };
  const quota = useQuota({ profile: currentProfile, profileReadAt: loadedAt, refreshProfile });
  const chat = useChat({
    models: [],
    accountDefaultModel: null,
    onQuotaWarning: quota.noteWarning,
    onQuotaStale: () => void refreshProfile(),
  });
  return (
    <Composer
      running={chat.running !== null}
      enabled={!chat.busy}
      maxChars={null}
      docked={chat.phase !== "draft"}
      onSend={chat.send}
      onStop={() => void chat.stop()}
      quotaBlocked={isSendBlocked(quota.block, quota.byokProviders, null)}
      quotaNotice={
        <QuotaNotice readings={quota.readings} warnPct={quota.warnPct} block={quota.block} byokCovered={false} />
      }
    />
  );
}

describe("nhip lam tuoi", () => {
  beforeEach(async () => {
    stream.emit = null;
    queue.length = 0;
    refreshSpy.mockClear();
    window.history.replaceState(null, "", `/?c=${CONVERSATION_ID}`);
    vi.mocked(api.getConversation).mockResolvedValue(CONVERSATION);
    vi.mocked(api.listProviderKeys).mockResolvedValue({ keys: [], byok_providers: [] });
    vi.mocked(api.sendMessage).mockReset();
    renderRouted(<ChatWithQuota initial={profile([quotaWindow({ remaining_pct: 60 })])} />);
    await waitFor(() => {
      expect(api.getConversation).toHaveBeenCalled();
    });
  });

  it("13. `done` ⇒ doc lai `/auth/me` ⇒ nut gui tu khoa, KHONG can F5 (DoD dong 1)", async () => {
    vi.mocked(api.sendMessage).mockResolvedValueOnce({
      user_message_id: "m1",
      assistant_message_id: "m2",
      stream_url: "/api/v1/messages/m2/stream",
      branched: false,
      quota_warning: null,
    });
    queue.push(profile([quotaWindow({ remaining_pct: 0, retry_after: 300 })]));

    await userEvent.type(screen.getByRole("textbox"), "cau hoi");
    await userEvent.click(sendButton());
    await waitFor(() => expect(stream.emit).not.toBeNull());
    expect(refreshSpy).not.toHaveBeenCalled();

    act(() => {
      stream.emit?.({ event: "done", data: { finish_reason: "stop", usage: null } });
    });

    await waitFor(() => expect(exhausted()).toHaveTextContent("Đã hết hạn mức 5 giờ"));
    expect(refreshSpy).toHaveBeenCalledTimes(1);
    await userEvent.type(screen.getByRole("textbox"), "cau nua");
    expect(sendButton()).toBeDisabled();
  });

  it("14. `202` mang `quota_warning` ⇒ canh bao hien ngay, truoc ca `done`", async () => {
    vi.mocked(api.sendMessage).mockResolvedValueOnce({
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
    await userEvent.click(sendButton());

    await waitFor(() => expect(warning()).not.toBeNull());
    expect(screen.getAllByText("16%")).toHaveLength(1);
    expect(screen.queryByText("60%")).toBeNull();
  });

  it("15. `429 QUOTA_EXCEEDED` khi gui ⇒ doc lai `/auth/me` ngay", async () => {
    vi.mocked(api.sendMessage).mockRejectedValueOnce(
      new ApiError(429, "QUOTA_EXCEEDED", "het quota", { limit_type: "5h", retry_after: 300 }),
    );
    queue.push(profile([quotaWindow({ remaining_pct: 0, retry_after: 300 })]));

    await userEvent.type(screen.getByRole("textbox"), "cau hoi");
    await userEvent.click(sendButton());

    await waitFor(() => expect(sendButton()).toBeDisabled());
    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });

  it("16. loi KHAC quota (500) ⇒ KHONG doc lai — nhip lam tuoi khong phai moi loi", async () => {
    vi.mocked(api.sendMessage).mockRejectedValueOnce(new ApiError(500, "INTERNAL", "loi"));

    await userEvent.type(screen.getByRole("textbox"), "cau hoi");
    await userEvent.click(sendButton());

    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(1));
    expect(refreshSpy).not.toHaveBeenCalled();
  });
});
