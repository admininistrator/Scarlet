/**
 * Setup dung chung cho moi test FE — B-199.
 *
 * Hai viec, khong hon:
 *
 * 1. Nap matcher cua `@testing-library/jest-dom` (`toBeInTheDocument`,
 *    `toBeDisabled`, ...). Khong co dong nay thi chung ton tai duoi dang
 *    `undefined` va moi khang dinh dung chung deu nem TypeError o cho khong
 *    lien quan gi toi thu dang duoc kiem.
 * 2. Vá hai thứ jsdom khong co ma primitive cua Radix doi (T-3.6, ADR-16).
 * 3. Don DOM sau moi test. `@testing-library/react` tu goi `cleanup` khi
 *    `globals: true` (da bat trong `vite.config.ts`), nhung goi tuong minh o
 *    day giu cho dieu do dung ke ca khi ai do tat `globals` — mot DOM khong
 *    duoc don khien test thu hai tim thay HAI phan tu trung ten va do voi mot
 *    thong bao noi ve so luong chu khong ve nguyen nhan.
 */

import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

/*
  `ResizeObserver` va `hasPointerCapture` khong ton tai trong jsdom, ma
  `@radix-ui/react-popper` (nen cua Popover lan Tooltip) goi ca hai luc mo.
  Thieu chung thi loi nem ra tu ben trong `useLayoutEffect` cua thu vien —
  mot vet stack khong nhac gi toi component dang duoc kiem.

  Ban va o day chu khong trong tung file test: ADR-16 chon primitive Radix
  cho ca dialog/dropdown/tooltip, nen moi man hinh sau nay cham vao chung
  deu can dung hai dong duoi day.
*/
/*
  Phep kiem la `typeof ... !== "function"`, KHONG phai `"x" in globalThis`:
  jsdom KHAI bao vai API kieu nay tren prototype ma khong hien thuc chung,
  nen `"matchMedia" in globalThis` tra `true` trong khi gia tri la
  `undefined` — do dung bang `pnpm test` ngay trong T-3.6. Mot phep kiem
  bang `in` se im lang bo qua ban va, roi loi no ra o giua mot
  `useLayoutEffect` cua Radix.
*/
if (typeof globalThis.ResizeObserver !== "function") {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
}
/*
  `matchMedia` cung khong co trong jsdom, va tu T-3.6 no la thu QUYET DINH
  hinh dang cua Model Picker (dropdown hay sheet). Mac dinh `matches: false`
  = be rong desktop, tuc man hinh ma phan lon test dang mo ta.

  Test nao can be rong nho thi `vi.stubGlobal("matchMedia", ...)` de ghi de,
  va `vi.unstubAllGlobals()` o duoi tra lai dung ban nay sau moi ca — ban
  nay dat bang PHEP GAN chu khong bang `stubGlobal`, nen no khong bi go mat.
*/
if (typeof globalThis.matchMedia !== "function") {
  globalThis.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
if (typeof Element.prototype.hasPointerCapture !== "function") {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

/*
  T-S.19a — han cho mac dinh cua `waitFor`/`findBy*` (1 s) qua sat cho cac luong
  dung CA app: dao dieu huong mount them thanh mo + sidebar doc (do A/B:
  `ReasoningFlow` 1.1 s → 1.65 s, `RetryFlow` 0.75 s → 1.15 s), va ngay sau
  luot `pytest` cua `make test` may con tai nang ⇒ hai ca do luan phien. Han
  dai hon chi lam ca HONG that bai cham hon; ca dat van xong ngay khi dieu kien
  dung. Cung so voi tien le `{ timeout: 3000 }` cua `authScreens.test.tsx`.
*/
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
