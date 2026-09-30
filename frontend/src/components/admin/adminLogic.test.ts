/**
 * Luat THUAN cua man quan tri (T-3.12) — bang so, khong React.
 *
 * Ba nhom, moi nhom mot cam bay da biet:
 *
 *   - `padMoney` — "tien la chuoi": chi THEM so 0, khong bao gio lam tron.
 *   - `usersView` — `can_execute_skills` la mot khoa cua BAN GHI DE: doi mot
 *     khoa khong duoc xoa khoa khac, va bat/tat ve dung gia tri tier thi go
 *     khoa thay vi ghi mot ban sao se lang le chan nguoi ay sau nay.
 *   - `auditView` — DoD dong 3 / B-191: "voi ai" la chu, khong UUID; nguoi da
 *     xoa chi con 8 ky tu dau.
 */

import { describe, expect, it } from "vitest";

import type { AdminModelOut, AdminUserOut, AuditEntry, TierRow } from "../../lib/api";
import { describeActor, describeChanges, describeTarget, describeValue, limitWindows } from "./auditView";
import { formatDateTime, formatDayKey, formatShortDateTime, padMoney, shortId } from "./format";
import { routeCards } from "./ModelsScreen";
import { tierPatch } from "./TiersSection";
import {
  effectiveSkills,
  isPending,
  overrideLimit,
  overrideWithLimits,
  overrideWithSkills,
} from "./usersView";

const UUID = "4e1dd956-7a41-4c1e-9b1f-0c6a2b9f1d2e";

const FREE: TierRow = {
  name: "free",
  limit_5h_usd: "0.5000",
  limit_7d_usd: "3.0000",
  can_execute_skills: false,
  can_use_web: false,
  web_searches_per_day: 0,
  max_upload_mb: 5,
  max_attachments: 3,
  allowed_model_tags: [],
  is_default: true,
};

function user(p: Partial<AdminUserOut> = {}): AdminUserOut {
  return {
    id: UUID,
    email: "a@scarlet.test",
    display_name: null,
    status: "active",
    role: "user",
    tier_name: "free",
    limit_override_json: null,
    email_verified_at: null,
    approved_at: null,
    approved_by: null,
    last_login_at: null,
    created_at: "2026-09-22T01:02:03Z",
    ...p,
  };
}

function entry(p: Partial<AuditEntry>): AuditEntry {
  return {
    id: 1,
    created_at: "2026-09-22T07:32:00Z",
    actor_id: "11111111-1111-4111-8111-111111111111",
    actor_email: "admin@scarlet.test",
    actor_display_name: null,
    action: "user.approve",
    target_type: "users",
    target_id: UUID,
    target_email: "a@scarlet.test",
    target_display_name: null,
    details: { from: "pending_approval", to: "active" },
    ip: null,
    ...p,
  };
}

describe("padMoney — tien la CHUOI", () => {
  it.each([
    ["0", "0.000000"],
    ["0.1", "0.100000"],
    ["0.000109", "0.000109"],
    ["12.074410", "12.074410"],
    // Dai hon sau chu so: giu nguyen, KHONG cat (cat la lam tron).
    ["0.1234567", "0.1234567"],
  ])("%s ⇒ %s", (input, output) => {
    expect(padMoney(input)).toBe(output);
  });

  it("thang cot dau cham: moi o tien cung so chu so sau dau cham", () => {
    const columns = ["0", "18.60554", "0.3"].map((s) => padMoney(s).split(".")[1].length);
    expect(new Set(columns)).toEqual(new Set([6]));
  });
});

describe("format", () => {
  it("khoa ngay ISO → d/m, KHONG qua `Date` (mui gio am lui ve hom truoc)", () => {
    expect(formatDayKey("2026-09-16")).toBe("16/9");
    expect(formatDayKey("2026-10-01")).toBe("1/10");
  });

  it("ngay gio theo DUNG thu tu ban T-HD7: dd/mm[/yyyy] HH:MM, dau `/`", () => {
    // Gio dia phuong cua may chay test — lay lai bang `Date` de khong phu
    // thuoc mui gio, chi khang dinh THU TU va DAU PHAN CACH.
    const iso = "2026-09-22T07:32:00Z";
    const d = new Date(iso);
    const pad2 = (n: number) => String(n).padStart(2, "0");
    expect(formatShortDateTime(iso)).toBe(
      `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`,
    );
    expect(formatDateTime(iso)).toMatch(/^\d{2}\/\d{2}\/2026 \d{2}:\d{2}$/);
  });

  it("8 ky tu dau cua id", () => {
    expect(shortId(UUID)).toBe("4e1dd956");
  });
});

describe("usersView — ban ghi de han muc", () => {
  it("quyen skill hieu luc: ban ghi de thang tier, vang mat thi theo tier", () => {
    expect(effectiveSkills(user(), [FREE])).toBe(false);
    expect(effectiveSkills(user({ limit_override_json: { can_execute_skills: true } }), [FREE])).toBe(true);
    expect(effectiveSkills(user({ tier_name: "khong-co" }), [FREE])).toBe(false);
  });

  it("bat skill KHAC tier ⇒ ghi khoa, GIU cac khoa khac", () => {
    const next = overrideWithSkills({ limit_5h_usd: "1" }, true, false);
    expect(next).toEqual({ limit_5h_usd: "1", can_execute_skills: true });
  });

  it("tat ve DUNG gia tri tier ⇒ go khoa; ban ghi de rong ⇒ null", () => {
    expect(overrideWithSkills({ can_execute_skills: true }, false, false)).toBeNull();
    expect(overrideWithSkills({ can_execute_skills: true, limit_7d_usd: "9" }, false, false)).toEqual({
      limit_7d_usd: "9",
    });
  });

  it("khong biet tier ⇒ luon ghi khoa, khong doan", () => {
    expect(overrideWithSkills(null, false, null)).toEqual({ can_execute_skills: false });
  });

  it("dialog han muc: o trong ⇒ go khoa; go gi luu nguyen CHUOI; giu khoa skill", () => {
    const next = overrideWithLimits(
      { limit_5h_usd: "1", can_execute_skills: true },
      { limit_5h_usd: "  ", limit_7d_usd: "20" },
    );
    expect(next).toEqual({ can_execute_skills: true, limit_7d_usd: "20" });
    expect(overrideWithLimits({ limit_5h_usd: "1" }, { limit_5h_usd: "", limit_7d_usd: "" })).toBeNull();
    expect(overrideLimit({ limit_5h_usd: "1.5" }, "limit_5h_usd")).toBe("1.5");
    expect(overrideLimit(null, "limit_7d_usd")).toBe("");
  });

  it("cho hieu luc: dung TTL cua server, hai ben bien; chua biet TTL ⇒ van cho", () => {
    const saved = 1_000_000;
    expect(isPending(saved, saved + 44_999, 45)).toBe(true);
    expect(isPending(saved, saved + 45_000, 45)).toBe(false);
    expect(isPending(saved, saved + 999_999, null)).toBe(true);
  });
});

describe("auditView — ai / lam gi / voi ai (B-191)", () => {
  it("voi ai = ten + email, KHONG UUID", () => {
    const e = entry({ target_display_name: "Lê Bảo Anh" });
    expect(describeTarget(e)).toEqual({ kind: "user", name: "Lê Bảo Anh", email: "a@scarlet.test" });
    expect(JSON.stringify(describeTarget(e))).not.toContain(UUID);
  });

  it("chua dat ten ⇒ email lam ten, khong lap email lan hai", () => {
    expect(describeTarget(entry({}))).toEqual({ kind: "user", name: "a@scarlet.test", email: null });
  });

  it("nguoi da xoa ⇒ 8 ky tu dau cua id, khong email", () => {
    expect(describeTarget(entry({ target_email: null }))).toEqual({
      kind: "deletedUser",
      shortId: "4e1dd956",
    });
  });

  it("tier ⇒ ten tier; catalog ⇒ khong co dich cu the", () => {
    expect(describeTarget(entry({ target_type: "tiers", target_id: "free", target_email: null }))).toEqual({
      kind: "tier",
      name: "free",
    });
    expect(describeTarget(entry({ target_type: "catalog", target_id: null, target_email: null }))).toEqual({
      kind: "catalog",
    });
  });

  it("actor_email null ⇒ 'khong con biet la ai', khong gia lam nguoi", () => {
    expect(describeActor(entry({ actor_id: null, actor_email: null }))).toEqual({ kind: "unknown" });
  });

  it("duyet ⇒ mot dong trang thai cu → moi, bang NHAN chu khong bang ma", () => {
    expect(describeChanges(entry({}))).toEqual([
      {
        label: { key: "admin.field.status" },
        from: { key: "admin.status.pending_approval" },
        to: { key: "admin.status.active" },
      },
    ]);
  });

  it("sua tai khoan ⇒ moi truong doi mot dong; gia tri cu rong la '—'", () => {
    const e = entry({
      action: "user.update",
      details: {
        changed: {
          tier_name: { from: "free", to: "trusted" },
          limit_override_json: { from: null, to: { limit_5h_usd: "1", can_execute_skills: true } },
        },
      },
    });
    expect(describeChanges(e)).toEqual([
      { label: { key: "admin.field.tier_name" }, from: { text: "free" }, to: { text: "trusted" } },
      {
        label: { key: "admin.field.limit_override_json" },
        from: { empty: true },
        to: { text: "limit_5h_usd=1, can_execute_skills=true" },
      },
    ]);
  });

  it("truong backend moi chua co nhan ⇒ van hien, bang ten tho", () => {
    const e = entry({ action: "tier.update", details: { changed: { truong_moi: { from: 1, to: 2 } } } });
    expect(describeChanges(e)[0].label).toEqual({ raw: "truong_moi" });
  });

  it("tai lai catalog ⇒ su kien khong co 'cu'", () => {
    const e = entry({ action: "catalog.reload", target_type: "catalog", details: { models: 5, version: 3 } });
    expect(describeChanges(e)).toEqual([
      { label: { key: "admin.field.models" }, to: { text: "5" } },
      { label: { key: "admin.field.version" }, to: { text: "3" } },
    ]);
  });

  it("boolean va mang rong", () => {
    expect(describeValue(true)).toEqual({ key: "admin.yes" });
    expect(describeValue([])).toEqual({ empty: true });
  });
});

describe("tierPatch — chi gui truong THAT SU doi", () => {
  const form = {
    money: { limit_5h_usd: "0.5000", limit_7d_usd: "3.0000" },
    ints: { web_searches_per_day: "0", max_upload_mb: "5", max_attachments: "3" },
    bools: { can_execute_skills: false, can_use_web: false },
    tags: "",
  };

  it("khong doi gi ⇒ body rong", () => {
    expect(tierPatch(FREE, form)).toEqual({});
  });

  it("doi hai o ⇒ dung hai truong; tien giu CHUOI, so luong la so", () => {
    expect(
      tierPatch(FREE, {
        ...form,
        money: { ...form.money, limit_5h_usd: "2" },
        ints: { ...form.ints, max_attachments: "4" },
        tags: " fast, cheap ,",
      }),
    ).toEqual({ limit_5h_usd: "2", max_attachments: 4, allowed_model_tags: ["fast", "cheap"] });
  });
});

describe("routeCards — health thuoc ve DUONG DI (`GET /admin/models`, T-S.17)", () => {
  function model(p: Partial<AdminModelOut>): AdminModelOut {
    return {
      id: "m",
      display_name: "M",
      provider: "Hang",
      route: { id: "khoa", label: "Nhan", user_visible: true, availability: "always" },
      health: { available: true, reason: null },
      enabled: true,
      ...p,
    };
  }
  const nineRouter = {
    id: "ninerouter",
    label: "9Router (local)",
    user_visible: false,
    availability: "host-dependent",
  } as const;

  it("gom theo KHOA duong; hong khi CO model bi xam, kem ly do; 'Dung cho' chi model dang bat", () => {
    const cards = routeCards([
      model({ id: "a", display_name: "DeepSeek Flash", route: { ...model({}).route, id: "deepseek", label: "DeepSeek AI" } }),
      model({
        id: "b",
        display_name: "Gemini Flash",
        provider: "Google AI",
        route: nineRouter,
        health: { available: false, reason: "9Router (local) dang khong phan hoi" },
      }),
      model({ id: "c", display_name: "Gemini Tat", route: nineRouter, enabled: false }),
    ]);
    expect(cards).toEqual([
      { id: "deepseek", label: "DeepSeek AI", intermediary: false, ok: true, reason: null, serves: ["DeepSeek Flash"] },
      {
        id: "ninerouter",
        label: "9Router (local)",
        intermediary: true,
        ok: false,
        reason: "9Router (local) dang khong phan hoi",
        serves: ["Gemini Flash"],
      },
    ]);
  });
});

describe("limitWindows — nhat ky gan the cua so (ban v2 muc 1g)", () => {
  it("sua tier: dung cua so co trong `changed`", () => {
    expect(
      limitWindows(
        entry({
          action: "tier.update",
          target_type: "tiers",
          details: { changed: { limit_7d_usd: { from: "10", to: "12" } } },
        }),
      ),
    ).toEqual(["admin.limit.7d"]);
  });

  it("ghi de: chi cua so co gia tri KHAC giua cu va moi; bat skill thi khong gan cua so nao", () => {
    const override = (from: unknown, to: unknown) =>
      entry({ action: "user.update", details: { changed: { limit_override_json: { from, to } } } });
    expect(limitWindows(override({ limit_5h_usd: "1" }, { limit_5h_usd: "1", limit_7d_usd: "20" }))).toEqual([
      "admin.limit.7d",
    ]);
    expect(limitWindows(override(null, { can_execute_skills: true }))).toEqual([]);
    expect(limitWindows(entry({}))).toEqual([]);
  });
});
