/**
 * `dayGroups.ts` — ham thuan, gio +07 (DoD dong 1 cua T-S.13).
 *
 * Ca render (headings that trong sidebar) o `Sidebar.test.tsx` ca 14–15; o day
 * la cac bien cua phep tinh ngay: nua dem, ngay doi thang, moc tuong lai, va
 * thu tu cac nhom.
 */

import { afterAll, describe, expect, it } from "vitest";

import type { ConversationOut } from "../../lib/api";
import { dayGroupOf, groupByDay } from "./dayGroups";

// `process` cua Node (vitest chay trong Node); tsconfig cua app khong khai @types/node.
declare const process: { env: Record<string, string | undefined> };

const ORIGINAL_TZ = process.env.TZ;
process.env.TZ = "Asia/Ho_Chi_Minh";
afterAll(() => {
  if (ORIGINAL_TZ === undefined) {
    delete process.env.TZ;
  } else {
    process.env.TZ = ORIGINAL_TZ;
  }
});

const NOW = new Date("2026-09-23T10:00:00+07:00");

function row(id: string, updatedAt: string): ConversationOut {
  return {
    id,
    title: id,
    default_model: null,
    system_prompt_override: null,
    active_leaf_id: null,
    pinned: false,
    created_at: updatedAt,
    updated_at: updatedAt,
  };
}

describe("dayGroupOf — gio may +07", () => {
  it("mui gio +07 dang co tac dung (khong thi moi ca duoi vo nghia)", () => {
    expect(NOW.getHours()).toBe(10);
    expect(new Date("2026-09-22T17:30:00Z").getHours()).toBe(0);
  });

  it("23/9 ⇒ Hom nay · 22/9 ⇒ Hom qua · 21/9 ⇒ “21/9/2026”", () => {
    expect(dayGroupOf("2026-09-23T03:00:00+07:00", NOW).label).toBe("Hôm nay");
    expect(dayGroupOf("2026-09-22T23:59:59+07:00", NOW).label).toBe("Hôm qua");
    expect(dayGroupOf("2026-09-21T12:00:00+07:00", NOW).label).toBe("21/9/2026");
  });

  it("`2026-09-22T17:30:00Z` ⇒ Hom nay (00:30 ngay 23/9 o +07)", () => {
    expect(dayGroupOf("2026-09-22T17:30:00Z", NOW).label).toBe("Hôm nay");
    // Mot phut truoc nua dem +07 van la hom qua.
    expect(dayGroupOf("2026-09-22T16:59:00Z", NOW).label).toBe("Hôm qua");
  });

  it("ngay LICH chu khong phai 24 gio: 00:10 hom nay so voi 23:50 hom qua", () => {
    const justAfterMidnight = new Date("2026-09-23T00:10:00+07:00");
    expect(dayGroupOf("2026-09-22T23:50:00+07:00", justAfterMidnight).label).toBe("Hôm qua");
  });

  it("d/m/yyyy khong so 0 dung dau, qua ca doi thang/doi nam", () => {
    expect(dayGroupOf("2026-08-31T12:00:00+07:00", NOW).label).toBe("31/8/2026");
    expect(dayGroupOf("2025-12-05T12:00:00+07:00", NOW).label).toBe("5/12/2025");
  });

  it("moc TUONG LAI (dong ho may lech) ⇒ Hom nay, khong phai mot ngay mai", () => {
    expect(dayGroupOf("2026-09-24T09:00:00+07:00", NOW).label).toBe("Hôm nay");
  });
});

describe("groupByDay", () => {
  it("giu thu tu server (moi nhat truoc), gom mot nhom mot lan", () => {
    const groups = groupByDay(
      [
        row("a", "2026-09-23T09:00:00+07:00"),
        row("b", "2026-09-23T01:00:00+07:00"),
        row("c", "2026-09-22T20:00:00+07:00"),
        row("d", "2026-09-21T20:00:00+07:00"),
        // Hang "tut" giua hai lan nap trang (B-228) — vao DUNG nhom cua no.
        row("e", "2026-09-23T00:30:00+07:00"),
      ],
      NOW,
    );

    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ["Hôm nay", ["a", "b", "e"]],
      ["Hôm qua", ["c"]],
      ["21/9/2026", ["d"]],
    ]);
  });

  it("danh sach rong ⇒ khong nhom nao", () => {
    expect(groupByDay([], NOW)).toEqual([]);
  });
});
