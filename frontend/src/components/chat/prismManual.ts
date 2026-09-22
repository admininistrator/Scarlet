/**
 * Phai duoc nap TRUOC `prismjs`.
 *
 * `prism-core.js` doc `window.Prism.manual` NGAY luc no chay, va neu khong
 * thay thi no dang ky mot listener `DOMContentLoaded` de tu di quet ca trang
 * roi ghi de `innerHTML` cua moi phan tu `code[class*="language-"]`.
 *
 * Scarlet khong bao gio muon dieu do: khoi code duoc dung bang phan tu React
 * tu `Prism.tokenize()` (xem `highlight.ts`), va mot thu vien tu sua DOM sau
 * lung React la mot nguon bug khong co day.
 *
 * Import cua ESM chay theo dung thu tu viet, nen mot dong `import
 * "./prismManual"` dat tren dong `import Prism from "prismjs"` la du.
 */
declare global {
  interface Window {
    Prism?: { manual?: boolean };
  }
}

if (typeof window !== "undefined") {
  window.Prism = { ...window.Prism, manual: true };
}

export {};
