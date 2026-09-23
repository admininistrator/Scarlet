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

import type { AdminUserRa, AuditEntry, ModelRa, TierRow } from "../../lib/api";
import { describeActor, describeChanges, describeTarget, describeValue } from "./auditView";
import { formatDateTime, formatDayKey, formatShortDateTime, padMoney, shortId } from "./format";
import { providerCards } from "./ModelsScreen";
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

function user(p: Partial<AdminUserRa> = {}): AdminUserRa {
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
  ])("%s ⇒ %s", (vao, ra) => {
    expect(padMoney(vao)).toBe(ra);
  });

  it("thang cot dau cham: moi o tien cung so chu so sau dau cham", () => {
    const cot = ["0", "18.60554", "0.3"].map((s) => padMoney(s).split(".")[1].length);
    expect(new Set(cot)).toEqual(new Set([6]));
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
    const hai = (n: number) => String(n).padStart(2, "0");
    expect(formatShortDateTime(iso)).toBe(
      `${hai(d.getDate())}/${hai(d.getMonth() + 1)} ${hai(d.getHours())}:${hai(d.getMinutes())}`,
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
    const moi = overrideWithSkills({ limit_5h_usd: "1" }, true, false);
    expect(moi).toEqual({ limit_5h_usd: "1", can_execute_skills: true });
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
    const moi = overrideWithLimits(
      { limit_5h_usd: "1", can_execute_skills: true },
      { limit_5h_usd: "  ", limit_7d_usd: "20" },
    );
    expect(moi).toEqual({ can_execute_skills: true, limit_7d_usd: "20" });
    expect(overrideWithLimits({ limit_5h_usd: "1" }, { limit_5h_usd: "", limit_7d_usd: "" })).toBeNull();
    expect(overrideLimit({ limit_5h_usd: "1.5" }, "limit_5h_usd")).toBe("1.5");
    expect(overrideLimit(null, "limit_7d_usd")).toBe("");
  });

  it("cho hieu luc: dung TTL cua server, hai ben bien; chua biet TTL ⇒ van cho", () => {
    const luu = 1_000_000;
    expect(isPending(luu, luu + 44_999, 45)).toBe(true);
    expect(isPending(luu, luu + 45_000, 45)).toBe(false);
    expect(isPending(luu, luu + 999_999, null)).toBe(true);
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

describe("providerCards — health tung provider tu `GET /models`", () => {
  function model(p: Partial<ModelRa>): ModelRa {
    return {
      id: "m",
      display_name: "M",
      provider: "Nhan",
      provider_id: "khoa",
      capabilities: [],
      context_window: 1,
      max_output: 1,
      default: false,
      badge: null,
      available: true,
      unavailable_reason: null,
      ...p,
    };
  }

  it("gom theo KHOA provider; hong khi CO model bi xam, kem ly do", () => {
    const the = providerCards([
      model({ id: "a", provider: "DeepSeek AI", provider_id: "deepseek" }),
      model({ id: "b", provider: "9Router (local)", provider_id: "ninerouter", available: false, unavailable_reason: "tat" }),
      model({ id: "c", provider: "9Router (local)", provider_id: "ninerouter", available: false, unavailable_reason: "tat" }),
    ]);
    expect(the).toEqual([
      { label: "DeepSeek AI", ok: true, reason: null },
      { label: "9Router (local)", ok: false, reason: "tat" },
    ]);
  });
});
