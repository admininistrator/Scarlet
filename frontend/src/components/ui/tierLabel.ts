import { t, type TextKey } from "../../lib/i18n";

/**
 * Nhan tier cho nguoi dung — NQ-116: nhan song trong `vi.json`, tier CHUA co
 * nhan thi hien nguyen ten goc (`tiers.name`). Tab Tai khoan (T-S.11) va khoi
 * tai khoan o chan sidebar (T-S.12) doc cung ham nay.
 *
 * Bang tra cuu tuong minh chu khong ghep chuoi `"tier." + name`: tier la DU
 * LIEU (admin them duoc, §10.4), con `t()` chi nhan khoa co that — ghep chuoi
 * la bo qua dung cai kiem cua `TextKey`.
 */
const TIER_LABEL: Readonly<Record<string, TextKey>> = {
  free: "tier.free",
};

export function tierLabel(name: string): string {
  const key = Object.hasOwn(TIER_LABEL, name) ? TIER_LABEL[name] : undefined;
  return key === undefined ? name : t(key);
}
