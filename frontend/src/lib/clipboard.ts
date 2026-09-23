/**
 * Sao chep vao clipboard — MOT ham, hai nut goi (T-3.7, Cam bay ③).
 *
 * KH tham chieu: UC-02 dong 5 · ban T-HD3 · tasks.md T-3.5, T-3.7.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO KHONG PHAI HAI DONG `navigator.clipboard` O HAI CHO            ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Co hai nut Copy: mot duoi moi khoi code (T-3.5) va mot duoi moi cau tra loi
 * (T-3.7). Chep hai ban la chep luon cai bay duoi day vao ca hai — roi mot
 * ngay nao do chi sua mot ban.
 *
 * Cai bay: `navigator.clipboard` **khong ton tai** ngoai secure context. Stack
 * nay chay `https://localhost` nen duong thuong khong cham toi, nhung mot may
 * dev mo bang `http://<ip-lan>` (dung de thu 375 px tren dien thoai that) thi
 * `navigator.clipboard` la `undefined`, va `navigator.clipboard.writeText(...)`
 * la mot `TypeError` nem tu trong `onClick` — nut khong lam gi, khong bao gi.
 *
 * Nen ham nay:
 *   • tra ve `false` thay vi nem, de nut biet ma ĐUNG hien "Da sao chep";
 *   • co mot duong lui bang `<textarea>` + `document.execCommand("copy")` —
 *     API da deprecated nhung no la thu DUY NHAT chay ngoai secure context;
 *   • khong nem ke ca khi ca hai duong deu hong.
 *
 * Khong `alert`, khong `console.error`: ben goi quyet dinh noi gi voi nguoi
 * dung, vi hai nut hien hai cho khac nhau.
 */
export async function copyText(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard !== undefined) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Quyen bi tu choi, hoac tab khong con focus. Roi xuong duong lui.
    }
  }
  return legacyCopy(text);
}

/**
 * Duong lui cho ngoai secure context. Tra `false` neu ca cai nay cung khong co.
 *
 * `position: fixed` + `opacity: 0` chu khong `display: none`: mot phan tu
 * khong duoc render thi khong chon chu trong no duoc, tuc `execCommand` chep
 * ra chuoi rong. Va `fixed` chu khong `absolute` de trang khong bi keo lech
 * mot khung hinh khi phan tu tam nay xuat hien.
 */
function legacyCopy(text: string): boolean {
  if (typeof document === "undefined" || typeof document.execCommand !== "function") {
    return false;
  }
  const o = document.createElement("textarea");
  o.value = text;
  o.setAttribute("readonly", "");
  o.style.position = "fixed";
  o.style.top = "0";
  o.style.opacity = "0";
  document.body.appendChild(o);
  try {
    o.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(o);
  }
}
