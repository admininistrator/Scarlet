/**
 * Sinh `Idempotency-Key` cua §11.4 — MOT ham, hai cho goi (T-3.7 / B-231).
 *
 * KH tham chieu: §11.4, C22, ADR-15 · CLAUDE.md A8 · tasks.md T-3.4, B-231.
 *
 * Ham nay o `lib/` chu khong trong `Composer.tsx` tu khi NQ-93 dua
 * `POST /messages/{id}/retry` vao `ROUTE_BAT_BUOC_IDEMPOTENCY`: tu do co HAI
 * cho phai sinh khoa (o nhap va nut Thu lai), va hai ban chep cua cai fallback
 * duoi day la hai cho de sua mot. Cung lop lap luan voi `lib/clipboard.ts` —
 * xem Cam bay ③ cua T-3.7.
 *
 * **Ham nay KHONG quyet dinh khi nao sinh khoa.** Do la luat C22 va no khac
 * nhau o hai cho goi: `Composer` sinh theo **lan soan thao** (rong → co chu),
 * `useChat.thuLai` sinh theo **lan bam** tren mot cap `(message, model)` va
 * giu nguyen qua moi lan hong. Ca hai luat deu chi bo khoa khi da nhan `202`.
 *
 * `crypto.randomUUID` chi ton tai trong **secure context** (https, hoac
 * `localhost`) — tren mot may dev mo bang `http://<ip-lan>` thi no la
 * `undefined`, va mot `TypeError` o day nghia la khong gui duoc gi ca.
 *
 * Duong lui khong can chong va cham toan cau: khoa chi phai doc nhat trong
 * pham vi `idem:{user_id}:{route}:` cua mot nguoi (§11.4), va no song 24 gio.
 */
export function khoaMoi(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}
