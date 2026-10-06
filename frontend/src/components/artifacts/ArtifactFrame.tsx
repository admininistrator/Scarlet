/**
 * Khung render artifact — T-5.6 (ADR-10, §14.3). Noi dung toi sau bang
 * `postMessage` (T-5.7); `src` chi la trang khung tinh cua origin phu, khong
 * id, khong query.
 *
 * Ba lop chong nhau, moi lop chan mot thu ma hai lop kia khong chan:
 *   1. origin phu (`VITE_ARTIFACTS_BASE_URL`, anh xa tu `ARTIFACTS_BASE_URL`)
 *   2. `sandbox` KHONG co `allow-same-origin` ⇒ script chay voi origin `null`
 *   3. CSP cua origin phu (Nginx, Phu luc D) ⇒ `connect-src 'none'`
 *
 * `allow-same-origin` cung `allow-scripts` la vo hieu hoa toan bo sandbox
 * (§14.3). "Iframe khong gui cookie / `localStorage` nem" la HANG RAO, khong
 * phai loi can sua. `scripts/test_artifact_origin.mjs` doc chuoi duoi day tu
 * chinh file nay — sua mot cho la S12 do ngay.
 */
export const ARTIFACT_SANDBOX = "allow-scripts allow-popups allow-forms";

export function ArtifactFrame({ title }: { title: string }) {
  return (
    <iframe
      src={`${import.meta.env.VITE_ARTIFACTS_BASE_URL}/`}
      sandbox={ARTIFACT_SANDBOX}
      title={title}
      className="h-full w-full border-0"
    />
  );
}
