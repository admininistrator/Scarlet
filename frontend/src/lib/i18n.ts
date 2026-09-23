import vi from "../locales/vi.json";

// Chi co vi-VN o P0 (B-07: them ngon ngu la viec cua sau nay). Ham t() toi
// thieu — chi tra chuoi theo key, khong interpolation/pluralization.
const locales = { vi } as const;

type Locale = keyof typeof locales;
/**
 * Moi khoa co that trong `vi.json`.
 *
 * Xuat ra (T-3.6) vi cac bang tra cuu kieu `Record<TangMacDinh, ...>` phai
 * khai duoc gia tri cua chung LA mot khoa — khong thi `t(BANG[x])` nhan mot
 * `string` va TypeScript khong con bat duoc mot khoa go sai.
 */
export type TextKey = keyof (typeof locales)["vi"];
type Key = TextKey;

const currentLocale: Locale = "vi";

/**
 * Locale cua `Intl.*` khi dinh dang so va gio (T-3.12, ban T-HD7: *"so nguyen,
 * dinh dang vi-VN"*). Mot hang canh `currentLocale` chu khong rai trong tung
 * component: them ngon ngu (B-07) la doi dung hai dong nay.
 */
export const DISPLAY_LOCALE = "vi-VN";

export function t(key: Key): string {
  return locales[currentLocale][key] ?? key;
}
