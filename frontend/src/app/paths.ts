/**
 * Mot ban duy nhat cua cac duong CO TEN — T-3.1a (chin), T-S.11 them bon tab
 * cua Cai dat.
 *
 * KH tham chieu: §16.3, §23 · tasks.md T-3.1a, T-3.1b, T-3.12 · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO MOT FILE RIENG CHO CHIN CHUOI                                  ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Cung ly le voi `api.ts` ("File nay la cho DUY NHAT trong FE biet duong dan
 * `/api/v1/...` trong nhu the nao"): mot duong dan viet sai trong JSX chay
 * thanh 404 luc nguoi dung bam nut, khong phai luc build. Bang route va moi
 * `<Link to>` doc CUNG mot hang o day, nen hai ben khong the lech nhau.
 *
 * `as const` chu khong `string`: `PATHS.register` go nham thanh `PATHS.dangKi`
 * la loi `tsc`, dung ho hang voi `keyof vi.json` cua `t()`.
 *
 * ── Chin, khong phai muoi mot ─────────────────────────────────────────────
 *
 * T-3.1a dem 11 duong phai dinh tuyen. Hai duong cuoi — 404 va 500 — KHONG
 * co mat o day va do la co y: chung khong phai dia chi ma ai go vao thanh
 * dia chi. 404 la nhanh `path: "*"` cua bang route (bat moi thu khong khop),
 * 500 la `errorElement` (chi ton tai khi co mot ngoai le). Dat cho chung mot
 * hang `PATHS` se moi nguoi viet `<Link to={PATHS.notFound}>`, tuc dieu
 * huong nguoi dung toi mot trang bao loi ma khong co loi nao xay ra.
 *
 * ── Ten khoa bang tieng Anh, gia tri giu tieng Viet khong dau ─────────────
 *
 * B-142 ngả ② (chot 2026-09-20): dinh danh MOI deu tieng Anh — dung tien le
 * T-2.7. Nhung *gia tri* la URL nguoi dung nhin thay tren thanh dia chi;
 * chung da ton tai tu T-2.19 (`/dang-nhap`) va duoc task T-3.1a liet ke
 * nguyen van, nen doi chung la doi hop dong voi nguoi dung chu khong phai
 * doi mot ten bien.
 */
export const PATHS = {
  home: "/",
  admin: "/admin",
  /**
   * T-S.11 — ≥ 1024 px chuyen thang sang `settingsAccount`; hep hon la danh
   * sach tab (ban T-HD9 F). Nam tab ben duoi moi tab mot duong dan (§24.2b·S10).
   */
  settings: "/cai-dat",
  settingsAccount: "/cai-dat/tai-khoan",
  settingsAppearance: "/cai-dat/giao-dien",
  settingsModel: "/cai-dat/model",
  /**
   * T-S.19c — tab BYOK (ban T-HD10) thay tab Khoa API o vi tri thu tu. Duong
   * cu `settingsApiKeys` chi con chuyen huong ve day (lien ket da gui di van chay).
   */
  settingsByok: "/cai-dat/byok",
  settingsApiKeys: "/cai-dat/khoa-api",
  /**
   * Tab Muc su dung — dich cua dong han muc tren o nhap (T-S.10, NQ-114) va
   * cua menu tai khoan (T-S.12).
   */
  settingsUsage: "/cai-dat/muc-su-dung",
  login: "/dang-nhap",
  register: "/dang-ky",
  forgotPassword: "/quen-mat-khau",
  resetPassword: "/dat-lai-mat-khau",
  verifyEmail: "/verify-email",
  pendingApproval: "/cho-duyet",
  /**
   * T-8.2 — trang chia se cong khai, NGOAI cua dang nhap. Server dung link nay
   * (`PUBLIC_BASE_URL` + `/s/{token}`, T-8.1) — doi o day la gay link da gui.
   */
  share: "/s/:token",
} as const;

export type Path = (typeof PATHS)[keyof typeof PATHS];
