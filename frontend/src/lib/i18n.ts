import vi from "../locales/vi.json";

// Chi co vi-VN o P0 (B-07: them ngon ngu la viec cua sau nay). Ham t() toi
// thieu — chi tra chuoi theo key, khong interpolation/pluralization.
const locales = { vi } as const;

type Locale = keyof typeof locales;
type Key = keyof (typeof locales)["vi"];

const currentLocale: Locale = "vi";

export function t(key: Key): string {
  return locales[currentLocale][key] ?? key;
}
