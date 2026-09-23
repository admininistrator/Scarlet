/**
 * Ba tang model mac dinh — T-3.6, UC-05 dong 4.
 *
 * KH tham chieu: §9.2, §9.3, UC-05 · tasks.md T-3.6 (Viec can lam dong 3-4,
 * Cam bay ①), B-206/NQ-79.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  HOI THOAI ＞ TAI KHOAN ＞ CATALOG                                      ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Ba nguon, ba chu so huu khac nhau:
 *
 *   1. `conversations.default_model` — nguoi dung dat cho DUNG hoi thoai nay
 *      (`PATCH /conversations/{id}`). Thang tat ca.
 *   2. `users.default_model`         — nguoi dung dat cho CHINH MINH
 *      (`PUT /settings`, §18.4). Thang catalog.
 *   3. `default: true` cua catalog   — nguoi VAN HANH dat cho ca he thong
 *      (§9.2). Duong lui cuoi cung.
 *
 * File nay khong biet React va khong goi mot API nao: no la mot phep chon
 * thuan tuy tren ba chuoi va mot danh sach. Ly do tach ra la Cam bay ① —
 * phep chon nay co bon nhanh loi (id khong con trong catalog, model bi
 * `enabled: false`, catalog khong co `default`, danh sach rong) va cả bon
 * deu phai kiem duoc ma khong phai dung mot component.
 *
 * ── Cam bay ① cua T-3.6: mot tang co the tro vao HU VO ────────────────────
 *
 * T-3.0 validate `default_model` luc GHI, khong luc doc — co y, vi catalog la
 * file sua nong (`POST /admin/catalog/reload`, §19.1). Nghia la
 * `users.default_model` hom nay co the tro vao mot model da bien mat khoi
 * catalog, va `conversations.default_model` cua mot hoi thoai cu cung vay.
 *
 * Vi vay MOI tang deu phai di qua `inCatalog()` truoc khi duoc cong
 * nhan. Mot tang tro vao hu vo bi BO QUA va roi xuong tang duoi, chu khong
 * lam ca phep chon tra ve `null` — mot o trong hay mot id tran tren man hinh
 * la dung thu Cam bay ① cam.
 */

import type { ModelOut } from "../../lib/api";

/** Tang da quyet dinh model dang dung. Dung cho chip va rail cua T-HD4. */
export type DefaultTier = "conversation" | "account" | "catalog";

/** Ba id mac dinh, moi id la mot tang. `null` = tang ay khong dat gi. */
export interface DefaultSources {
  /** `conversations.default_model` cua hoi thoai dang mo. */
  conversation: string | null;
  /** `users.default_model` tu `GET /auth/me`. */
  account: string | null;
}

/**
 * Ket qua phep chon: model nao dang dung, va tang nao dat ra tung id.
 *
 * `tang` KHAC "id nao dang duoc chon": hai thong tin nay tach nhau vi chung
 * co the lech. Ban T-HD4 noi ro — dau tich va nen nhan bao *model nao dang
 * duoc chon*, rail va chip bao *tang nao dat ra no*.
 */
export interface DefaultPick {
  /** Model dang dung. `null` chi khi danh sach rong hoac khong con model nao. */
  modelId: string | null;
  /** Tang da quyet dinh `modelId`. `null` khi `modelId` la `null`. */
  tier: DefaultTier | null;
  /**
   * Id HOP LE cua tung tang — da loc qua catalog. Component so `model.id`
   * voi ba gia tri nay de ve rail/chip, nen mot tang tro vao hu vo phai la
   * `null` o day chu khong phai id goc.
   */
  byTier: Record<DefaultTier, string | null>;
}

function inCatalog(models: ModelOut[], id: string | null): string | null {
  if (id === null) {
    return null;
  }
  return models.some((m) => m.id === id) ? id : null;
}

/**
 * Chon model hieu luc tu ba tang.
 *
 * KHONG loc theo `available`: mot model tam thoi khong goi duoc VAN la model
 * mac dinh cua nguoi ay (Cam bay ③ — 9Router tat la ca THUONG, va no bat lai
 * sau vai phut). Tu dong nhay sang model khac vi nguon tam im nghia la lan
 * sau ho hoi mot model khac ma khong ai bao. Hang do hien xam va bam khong
 * an; doi hay khong la viec cua nguoi dung.
 */
export function pickDefault(models: ModelOut[], sources: DefaultSources): DefaultPick {
  const byTier: Record<DefaultTier, string | null> = {
    conversation: inCatalog(models, sources.conversation),
    account: inCatalog(models, sources.account),
    catalog: models.find((m) => m.default)?.id ?? null,
  };

  const order: DefaultTier[] = ["conversation", "account", "catalog"];
  for (const tier of order) {
    const id = byTier[tier];
    if (id !== null) {
      return { modelId: id, tier, byTier };
    }
  }

  /*
    Ca cuoi: catalog khong co model nao `default: true` (hoac danh sach
    rong). Backend the `Catalog` validate "dung MOT model default" luc nap
    (T-0.7), nen ca nay chi xay ra khi danh sach chua ve hoac rong that.

    Roi ve model DAU TIEN thay vi `null`: thu tu cua `GET /models` la
    `order` cua catalog (§9.2), tuc no la mot lua chon co chu y cua nguoi
    van hanh chu khong phai mot hang ngau nhien. `tang` la `null` vi khong
    tang nao dat ra no — nut mo picker se khong in dong thu hai.
  */
  return { modelId: models[0]?.id ?? null, tier: null, byTier };
}
