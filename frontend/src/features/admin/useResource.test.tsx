/**
 * `useResource` — luat 3: mo man MOT lan = MOT request, ke ca duoi StrictMode.
 *
 * Do duoc tren stack that 2026-09-23 (T-3.12, DoD dong 1): truoc khi gop,
 * mo man "Nguoi dung" ban HAI `GET /admin/users` + HAI `GET /admin/tiers` —
 * StrictMode (dev) chay effect hai lan tren cung instance — tuc dem "so cau
 * SELECT ⇒ 1" ra 2, va dem "so lan goi `/admin/system`" gap doi.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { useResource, type Resource } from "./useResource";

function Probe({ load, onResource }: { load: () => Promise<string>; onResource: (r: Resource<string>) => void }) {
  const r = useResource(load);
  onResource(r);
  return <p>{r.loading ? "dang tai" : (r.data ?? r.error?.code ?? "")}</p>;
}

describe("useResource", () => {
  it("StrictMode: effect chay hai lan nhung chi MOT request", async () => {
    const load = vi.fn(async () => "xong");

    render(
      <StrictMode>
        <Probe load={load} onResource={() => undefined} />
      </StrictMode>,
    );

    expect(await screen.findByText("xong")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("`reload()` tuong minh thi LUON goi moi", async () => {
    const load = vi.fn(async () => "xong");
    let latest: Resource<string> | null = null;
    render(<Probe load={load} onResource={(r) => (latest = r)} />);
    await screen.findByText("xong");

    await act(async () => {
      await latest!.reload();
    });

    expect(load).toHaveBeenCalledTimes(2);
  });

  it("loi khong xoa du lieu cu", async () => {
    const load = vi
      .fn<() => Promise<string>>()
      .mockResolvedValueOnce("cu")
      .mockRejectedValueOnce(new ApiError(503, "SERVICE_UNAVAILABLE", "x"));
    let latest: Resource<string> | null = null;
    render(<Probe load={load} onResource={(r) => (latest = r)} />);
    await screen.findByText("cu");

    await act(async () => {
      await latest!.reload();
    });

    await waitFor(() => {
      expect(latest!.error?.code).toBe("SERVICE_UNAVAILABLE");
    });
    expect(latest!.data).toBe("cu");
  });
});
