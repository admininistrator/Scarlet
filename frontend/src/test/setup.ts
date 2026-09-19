/**
 * Setup dung chung cho moi test FE — B-199.
 *
 * Hai viec, khong hon:
 *
 * 1. Nap matcher cua `@testing-library/jest-dom` (`toBeInTheDocument`,
 *    `toBeDisabled`, ...). Khong co dong nay thi chung ton tai duoi dang
 *    `undefined` va moi khang dinh dung chung deu nem TypeError o cho khong
 *    lien quan gi toi thu dang duoc kiem.
 * 2. Don DOM sau moi test. `@testing-library/react` tu goi `cleanup` khi
 *    `globals: true` (da bat trong `vite.config.ts`), nhung goi tuong minh o
 *    day giu cho dieu do dung ke ca khi ai do tat `globals` — mot DOM khong
 *    duoc don khien test thu hai tim thay HAI phan tu trung ten va do voi mot
 *    thong bao noi ve so luong chu khong ve nguyen nhan.
 */

import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
