/**
 * `useModels` — T-S.4: mo picker chi hoi lai khi `checked_at` da cu.
 *
 * KH tham chieu: §24.2b·S5 · tasks.md T-S.4 (Viec dong 4) · NQ-113 · T-3.6
 * Cam bay ② (noi co dieu kien).
 *
 * Dong ho: `Date.now` bi thay bang mot moc co dinh chu khong bat fake timers —
 * `waitFor` cua testing-library can timer that.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type ModelOut } from "../../lib/api";
import { useModels, type ModelCatalog } from "./useModels";

const NOW = Date.parse("2026-09-24T07:00:00Z");
const TTL_S = 30;

function model(checkedAt: string | null, id = "m1"): ModelOut {
  return {
    id,
    display_name: id,
    provider: "Nhan",
    provider_id: "khoa",
    capabilities: [],
    context_window: 1,
    max_output: 1,
    default: false,
    badge: null,
    available: true,
    unavailable_reason: null,
    reasoning: null,
    pricing: null,
    pricing_mode: "unmetered",
    checked_at: checkedAt,
    stale_after_s: TTL_S,
  };
}

function secondsAgo(s: number): string {
  return new Date(NOW - s * 1000).toISOString();
}

let latest: ModelCatalog | null = null;

function Harness() {
  const catalog = useModels();
  latest = catalog;
  return <p>{catalog.loading ? "dang tai" : catalog.models.map((m) => m.id).join(",")}</p>;
}

async function mountWith(first: ModelOut[]) {
  const listModels = vi.spyOn(api, "listModels").mockResolvedValueOnce(first);
  render(<Harness />);
  await screen.findByText(first.map((m) => m.id).join(","));
  return listModels;
}

beforeEach(() => {
  latest = null;
  vi.spyOn(Date, "now").mockReturnValue(NOW);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useModels.refreshIfStale", () => {
  it("checked_at còn mới ⇒ mở picker KHÔNG gọi API (Cạm bẫy ② T-3.6 vẫn đứng)", async () => {
    const listModels = await mountWith([model(secondsAgo(TTL_S - 1))]);

    act(() => latest!.refreshIfStale());

    expect(listModels).toHaveBeenCalledTimes(1);
  });

  it("checked_at cũ hơn stale_after_s ⇒ hỏi lại NGẦM, danh sách cũ vẫn còn trong lúc chờ", async () => {
    const listModels = await mountWith([model(secondsAgo(TTL_S + 1), "cu")]);
    let resolve: (v: ModelOut[]) => void = () => undefined;
    listModels.mockImplementationOnce(() => new Promise((r) => (resolve = r)));

    act(() => latest!.refreshIfStale());

    expect(listModels).toHaveBeenCalledTimes(2);
    // Ngầm: không quay nút làm mới, không che danh sách.
    expect(latest!.refreshing).toBe(false);
    expect(screen.getByText("cu")).toBeInTheDocument();

    await act(async () => resolve([model(secondsAgo(0), "moi")]));
    await screen.findByText("moi");
    expect(latest!.checkedAt?.getTime()).toBe(NOW);
  });

  it("checked_at null (backend chưa đo xong lượt đầu) ⇒ hỏi lại", async () => {
    const listModels = await mountWith([model(null)]);
    listModels.mockResolvedValueOnce([model(secondsAgo(0))]);

    act(() => latest!.refreshIfStale());

    await waitFor(() => expect(listModels).toHaveBeenCalledTimes(2));
  });

  it("mở/đóng liên tục trong lúc một lần hỏi còn bay ⇒ chỉ MỘT lần hỏi", async () => {
    const listModels = await mountWith([model(secondsAgo(TTL_S * 2))]);
    let resolve: (v: ModelOut[]) => void = () => undefined;
    listModels.mockImplementationOnce(() => new Promise((r) => (resolve = r)));

    act(() => {
      latest!.refreshIfStale();
      latest!.refreshIfStale();
      latest!.refreshIfStale();
    });

    expect(listModels).toHaveBeenCalledTimes(2);
    await act(async () => resolve([model(secondsAgo(0))]));
  });

  it("checkedAt là giờ backend ĐO, không phải giờ FE đọc", async () => {
    await mountWith([model(secondsAgo(12))]);

    expect(latest!.checkedAt?.getTime()).toBe(NOW - 12_000);
  });
});
