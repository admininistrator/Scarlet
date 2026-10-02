import type { ByokEndpoint, ModelOut } from "../../lib/api";

/**
 * Model cua endpoint BYOK nguoi dung tu nhap — T-S.19c (ban T-HD10 4a/4b).
 *
 * KH tham chieu: §10.5 · NQ-134 ②, NQ-137 · tasks.md T-S.19b, T-S.19c.
 *
 * `GET /models` la catalog CHUNG (khong doi danh tinh — xem `useModels`), nen
 * model cua endpoint khong co o do. FE dung chung tu `GET /settings/byok-endpoints`
 * thanh `ModelOut`, de picker, ba tang mac dinh (`pickDefault`) va chip
 * "model · muc" cua tin nhan doc MOT kieu duy nhat.
 *
 * Id `byok:<endpoint_id>/<model>` la hop dong cua backend
 * (`byok_endpoints.model_id_for`, T-S.19b). Khong suy luan, khong vision,
 * khong gia: luot BYOK chi dem token (NQ-134 ③).
 */
const ENDPOINT_PREFIX = "byok:";

export function isEndpointModel(modelId: string | null | undefined): boolean {
  return typeof modelId === "string" && modelId.startsWith(ENDPOINT_PREFIX);
}

/**
 * Endpoint `usable === false` (khoa khong giai ma duoc) bi bo qua: worker se
 * tra `UPSTREAM_ERROR` cho moi luot, nen hien no trong picker la moi nguoi ta
 * chon mot model chac chan hong. Hoi thoai dang tro vao no roi xuong tang duoi
 * (Cam bay ① cua `defaults.ts`).
 */
export function endpointModels(endpoints: readonly ByokEndpoint[]): ModelOut[] {
  return endpoints
    .filter((e) => e.usable)
    .flatMap((e) =>
      e.models.map(
        (model): ModelOut => ({
          id: `${ENDPOINT_PREFIX}${e.id}/${model}`,
          display_name: model,
          // Ten goi nho cua endpoint, khong host (ban T-HD10: "khong co host").
          provider: e.label,
          provider_id: `${ENDPOINT_PREFIX}${e.id}`,
          capabilities: [],
          // FE khong doc hai truong nay; tran that o `Settings` cua backend.
          context_window: 0,
          max_output: 0,
          default: false,
          badge: null,
          available: true,
          unavailable_reason: null,
          reasoning: null,
          pricing: null,
          pricing_mode: "unmetered",
          checked_at: null,
          stale_after_s: 0,
        }),
      ),
    );
}

/** `byok:<id>/<model>` → `<model>` (ten model duoc chua `/`); khong phai ⇒ `null`. */
export function endpointModelName(modelId: string): string | null {
  if (!isEndpointModel(modelId)) {
    return null;
  }
  const rest = modelId.slice(ENDPOINT_PREFIX.length);
  const slash = rest.indexOf("/");
  return slash < 0 || slash === rest.length - 1 ? null : rest.slice(slash + 1);
}
