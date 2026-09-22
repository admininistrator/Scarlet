import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { PATHS } from "../../app/paths";
import { ApiError, MA_LOI, api } from "../../lib/api";
import { t } from "../../lib/i18n";
import { authErrorText } from "./authErrors";

/**
 * Man `/verify-email?token=` — UC-01 dong 4 va dong 5. T-3.1b.
 *
 * KH tham chieu: §11.1, §11.5, §18.1, UC-01 · tasks.md T-2.2, T-3.1b.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BON KET CUC, BON MAN HINH — VA KHONG MOT MAN NAO LA MAN LOI           ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 *  `verified`         lan bam DAU  -> bao da xac thuc, tu sang `/cho-duyet`
 *  `already_verified` lan bam HAI  -> di thang toi `/dang-nhap` (UC-01 dong 5)
 *  `expired`          het han      -> nut "gui lai" (UC-01 dong 4)
 *  khong co `?token=`              -> cung khoi "gui lai", khong mot loi nao
 *
 * Chi `TOKEN_INVALID` (`400`) moi la mot loi that, va no la ca duy nhat o day
 * co nghia "lien ket nay khong phai cua he thong nay".
 *
 * ── VI SAO BACKEND PHAI TACH `already_verified` (T-3.1b) ──────────────────
 *
 * Toi T-2.2, ca hai lan bam deu tra `{"status": "verified"}` — idempotent, va
 * khong ai can phan biet. T-3.1b thi can, va can CA HAI CHIEU cung luc: DoD
 * dong 1 doi lan bam dau tu sang `/cho-duyet`, DoD dong 4 doi lan bam thu hai
 * ve `/dang-nhap`. Mot response giong het nhau cho hai ket cuc khac nhau thi
 * FE chi doan duoc — va cai doan re nhat (nho token nao da dung trong
 * `localStorage`) sai ngay khi nguoi dung mo lien ket tren may khac. Xem
 * docstring `VerifyEmailResponse.status` cua backend.
 *
 * ── `daGoi` LA VI `StrictMode`, KHONG PHAI VI CAN THAN QUA ────────────────
 *
 * `main.tsx` boc app trong `<StrictMode>`, tuc React chay effect -> cleanup ->
 * effect lai tren CUNG mot instance o ban dev. Khong co co nay thi lan mount
 * dau tieu luon token: loi goi thu nhat tra `verified`, loi goi thu hai tra
 * `already_verified`, va man hinh dung ket qua thu hai — nguoi vua dang ky bi
 * day toi `/dang-nhap` thay vi `/cho-duyet`, dung o ban dev va chi o ban dev.
 * Co khoa theo GIA TRI token chu khong mot `boolean`, de mot token khac (neu
 * URL doi) van chay lai duoc.
 */

/**
 * Bao lau thi tu chuyen trang sau khi bao "da xac thuc".
 *
 * Mot hang co ten chu khong mot so trong `setTimeout`: no la thoi gian cho
 * nguoi dung DOC mot dong chu, nen ngay ai do thay no qua nhanh thi cho sua
 * la mot cho. Du lau de doc mot cau, du ngan de khong ai tuong man hinh treo.
 */
const CHUYEN_SAU_MS = 1200;

type KetCuc = "dang-goi" | "verified" | "already_verified" | "expired" | "loi";

export function VerifyEmailScreen() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const navigate = useNavigate();

  const [ketCuc, setKetCuc] = useState<KetCuc>(token === null ? "expired" : "dang-goi");
  const [loi, setLoi] = useState<string | null>(null);
  const daGoi = useRef<string | null>(null);

  useEffect(() => {
    if (token === null || daGoi.current === token) {
      return;
    }
    daGoi.current = token;

    void (async () => {
      try {
        const ra = await api.xacThucEmail(token);
        setKetCuc(ra.status);
      } catch (e) {
        setKetCuc("loi");
        setLoi(
          e instanceof ApiError && e.code === MA_LOI.TOKEN_HONG
            ? t("verify.tokenHong")
            : authErrorText(e),
        );
      }
    })();
    // KHONG co cleanup, va day khong phai mot cho quen — xem khoi "daGoi" o
    // docstring dau file. Mot co `conGan` bi cleanup dat ve `false` (loi
    // quen thuoc cua moi effect goi mang) se hong CHINH XAC o day: lan chay
    // thu hai cua `StrictMode` bi `daGoi` chan lai TRUOC khi kip dung mot co
    // moi, nen ket qua cua loi goi duy nhat roi vao mot co da tat va man hinh
    // dung mai o "Dang xac thuc email...". Do duoc tren Chrome 2026-09-20.
  }, [token]);

  useEffect(() => {
    if (ketCuc !== "verified" && ketCuc !== "already_verified") {
      return;
    }
    const dich = ketCuc === "verified" ? PATHS.pendingApproval : PATHS.login;
    // `replace`: mot lan chuyen huong tu dong khong duoc de lai dau chan
    // trong lich su — bam Back se quay ve day va tieu them mot lan goi.
    const hen = setTimeout(() => void navigate(dich, { replace: true }), CHUYEN_SAU_MS);
    return () => clearTimeout(hen);
  }, [ketCuc, navigate]);

  if (ketCuc === "dang-goi") {
    return (
      <main className="mx-auto w-full max-w-sm px-6 py-12 text-center">
        <p className="text-sm text-muted">{t("verify.dangKiemTra")}</p>
      </main>
    );
  }

  if (ketCuc === "verified") {
    return (
      <main className="mx-auto w-full max-w-sm px-6 py-12 text-center">
        <h2 className="text-lg font-semibold">{t("verify.xong.tieuDe")}</h2>
        <p className="mt-2 text-sm text-muted">{t("verify.xong.moTa")}</p>
      </main>
    );
  }

  if (ketCuc === "already_verified") {
    return (
      <main className="mx-auto w-full max-w-sm px-6 py-12 text-center">
        <h2 className="text-lg font-semibold">{t("verify.xong.tieuDe")}</h2>
        <p className="mt-2 text-sm text-muted">{t("verify.daXongTruocDo")}</p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-sm px-6 py-12">
      <h2 className="text-lg font-semibold">
        {token === null ? t("verify.chuaXacThuc.tieuDe") : t("verify.hetHan.tieuDe")}
      </h2>
      {loi !== null && (
        <p role="alert" className="mt-2 text-sm text-danger-text">
          {loi}
        </p>
      )}
      <p className="mt-2 text-sm text-muted">{t("verify.hetHan.moTa")}</p>
      <ResendBlock />
    </main>
  );
}

/**
 * Khoi "gui lai email xac thuc" — Cam bay ③ cua T-3.1b.
 *
 * *"`resend-verification` co han muc 3/gio (§18.1), nen nut "gui lai" phai
 * noi ra dieu do khi bi tu choi. Mot nut bam duoc ma khong co chuyen gi xay
 * ra la cach chac chan nhat de nguoi dung bam them bon lan."*
 *
 * Co o nhap email chu khong tu dien: token trong URL la mot chuoi bam, no
 * khong mang email nao, va man hinh nay con phai chay duoc khi nguoi dung
 * CHUA dang nhap (vua bam mot lien ket het han trong hop thu).
 *
 * Thanh cong tra ve mot cau CO DINH cua §11.5 — "neu email nay ton tai va
 * chua duoc xac thuc" — nen o day khong co nhanh nao noi "da gui" mot cach
 * chac chan hon thuc te.
 */
function ResendBlock() {
  const [email, setEmail] = useState("");
  const [dangGui, setDangGui] = useState(false);
  const [loi, setLoi] = useState<string | null>(null);
  const [daGui, setDaGui] = useState(false);

  async function gui() {
    setLoi(null);
    setDangGui(true);
    try {
      await api.guiLaiXacThuc(email);
      setDaGui(true);
    } catch (e) {
      setLoi(
        e instanceof ApiError && e.code === MA_LOI.QUA_NHIEU_LAN
          ? t("verify.guiLaiQuaNhieu")
          : authErrorText(e),
      );
    } finally {
      setDangGui(false);
    }
  }

  if (daGui) {
    return <p className="mt-6 text-sm text-muted">{t("verify.daGuiLai")}</p>;
  }

  return (
    <form
      className="mt-6 flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void gui();
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">{t("auth.email")}</span>
        <input
          type="email"
          required
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-sm border border-border bg-background px-2 py-1.5 text-foreground"
        />
      </label>

      {loi !== null && (
        <p role="alert" className="text-sm text-danger-text">
          {loi}
        </p>
      )}

      <button
        type="submit"
        disabled={dangGui}
        className="motion-press rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
      >
        {dangGui ? t("auth.dangXuLy") : t("verify.guiLai")}
      </button>
    </form>
  );
}
