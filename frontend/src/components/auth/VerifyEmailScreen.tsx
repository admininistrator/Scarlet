import { CircleCheck, Clock, Link2Off, LoaderCircle, Mail } from "lucide";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { useSession } from "../../app/Layout";
import { PATHS } from "../../app/paths";
import { Moment } from "../../features/quota/Moment";
import { ApiError, ERROR_CODES, api } from "../../lib/api";
import { t } from "../../lib/i18n";
import { AuthField, FormAlert, SubmitButton } from "./AuthForm";
import { AuthLayout } from "./AuthLayout";
import { AuthMessage, MessageStatus, MessageText, SecondaryLink } from "./AuthMessage";
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
 * ── `calledRef` LA VI `StrictMode`, KHONG PHAI VI CAN THAN QUA ────────────
 *
 * `main.tsx` boc app trong `<StrictMode>`, tuc React chay effect -> cleanup ->
 * effect lai tren CUNG mot instance o ban dev. Khong co co nay thi lan mount
 * dau tieu luon token: loi goi thu nhat tra `verified`, loi goi thu hai tra
 * `already_verified`, va man hinh dung ket qua thu hai — nguoi vua dang ky bi
 * day toi `/dang-nhap` thay vi `/cho-duyet`, dung o ban dev va chi o ban dev.
 * Co khoa theo GIA TRI token chu khong mot `boolean`, de mot token khac (neu
 * URL doi) van chay lai duoc.
 *
 * ── T-S.16: ban T-HD8 (5a–5f) ─────────────────────────────────────────────
 *
 * Ban ve bo o email (*"May chu biet email tu link"*), nhung `POST
 * /auth/resend-verification` doi `email` va `verify-email` tra `expired` khong
 * kem email nao — nen o email O LAI (NQ-131 a, Backlog "gui lai theo token");
 * co phien (`pending_email` bi `StatusGate` dua toi) thi dien san email cua
 * phien. Moi thu khac theo ban ve: nut con bam duoc sau khi da gui, cham han
 * muc thi nut tat va gio thu lai lay tu `retry_after` cua `429`.
 */

/**
 * Bao lau thi tu chuyen trang sau khi bao "da xac thuc".
 *
 * Mot hang co ten chu khong mot so trong `setTimeout`: no la thoi gian cho
 * nguoi dung DOC mot dong chu, nen ngay ai do thay no qua nhanh thi cho sua
 * la mot cho. Du lau de doc mot cau, du ngan de khong ai tuong man hinh treo.
 */
const REDIRECT_AFTER_MS = 1200;

type Outcome = "calling" | "verified" | "already_verified" | "expired" | "invalid";

export function VerifyEmailScreen() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const navigate = useNavigate();

  const [outcome, setOutcome] = useState<Outcome>(token === null ? "expired" : "calling");
  const [error, setError] = useState<string | null>(null);
  const calledRef = useRef<string | null>(null);

  useEffect(() => {
    if (token === null || calledRef.current === token) {
      return;
    }
    calledRef.current = token;

    void (async () => {
      try {
        const output = await api.verifyEmail(token);
        setOutcome(output.status);
      } catch (e) {
        setOutcome("invalid");
        setError(
          e instanceof ApiError && e.code === ERROR_CODES.TOKEN_INVALID
            ? t("verify.tokenHong")
            : authErrorText(e),
        );
      }
    })();
    // KHONG co cleanup, va day khong phai mot cho quen — xem khoi "calledRef"
    // o docstring dau file. Mot co `mounted` bi cleanup dat ve `false` (loi
    // quen thuoc cua moi effect goi mang) se hong CHINH XAC o day: lan chay
    // thu hai cua `StrictMode` bi `calledRef` chan lai TRUOC khi kip dung mot
    // co moi, nen ket qua cua loi goi duy nhat roi vao mot co da tat va man
    // hinh dung mai o "Dang xac thuc email...". Do duoc tren Chrome 2026-09-20.
  }, [token]);

  useEffect(() => {
    if (outcome !== "verified" && outcome !== "already_verified") {
      return;
    }
    const target = outcome === "verified" ? PATHS.pendingApproval : PATHS.login;
    // `replace`: mot lan chuyen huong tu dong khong duoc de lai dau chan
    // trong lich su — bam Back se quay ve day va tieu them mot lan goi.
    const timer = setTimeout(() => void navigate(target, { replace: true }), REDIRECT_AFTER_MS);
    return () => clearTimeout(timer);
  }, [outcome, navigate]);

  if (outcome === "calling") {
    return (
      <AuthLayout>
        <AuthMessage icon={LoaderCircle} spinning title={t("auth.dangXacThuc")} />
      </AuthLayout>
    );
  }

  if (outcome === "verified" || outcome === "already_verified") {
    const first = outcome === "verified";
    return (
      <AuthLayout>
        <AuthMessage
          icon={CircleCheck}
          tone="success"
          title={t("auth.daXacThuc")}
          body={<MessageText>{first ? t("auth.dangChuyenChoDuyet") : t("verify.daXongTruocDo")}</MessageText>}
        >
          {/* Lien ket du phong neu khong tu chuyen (5b). */}
          <SecondaryLink to={first ? PATHS.pendingApproval : PATHS.login}>
            {first ? t("auth.moManChoDuyet") : t("auth.dangNhap")}
          </SecondaryLink>
        </AuthMessage>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <AuthMessage
        icon={token === null ? Mail : Link2Off}
        title={token === null ? t("verify.chuaXacThuc.tieuDe") : t("auth.linkHetHan")}
        body={<MessageText>{t("auth.linkHetHanMoTa")}</MessageText>}
      >
        {error !== null && <FormAlert tone="danger">{error}</FormAlert>}
        <ResendBlock />
      </AuthMessage>
    </AuthLayout>
  );
}

type Resend =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "sent" }
  | { kind: "limited"; retryAt: number | null }
  | { kind: "failed"; text: string };

/** Giay cho cua `429` (`details.retry_after`, §10.6) -> moc gio; khong co thi `null`. */
function retryAtOf(error: ApiError): number | null {
  const details = error.details as { retry_after?: unknown } | null | undefined;
  const seconds = details?.retry_after;
  return typeof seconds === "number" ? Date.now() + seconds * 1000 : null;
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
 * Ban ve 5f: *"Giao dien khong tu dem, khong in so 3"* — con so nam o may chu,
 * o day chi doc `retry_after` ra mot moc gio.
 */
function ResendBlock() {
  const session = useSession();
  // `null` = nguoi dung chua go gi: lay email cua phien NEU co, ke ca khi phien
  // ve SAU lan ve dau (mo thang `/verify-email` luc `/auth/me` con dang hoi).
  const [typed, setTyped] = useState<string | null>(null);
  const email = typed ?? session.user?.email ?? "";
  const [resend, setResend] = useState<Resend>({ kind: "idle" });

  async function submit() {
    setResend({ kind: "busy" });
    try {
      await api.resendVerification(email);
      setResend({ kind: "sent" });
    } catch (e) {
      setResend(
        e instanceof ApiError && e.code === ERROR_CODES.TOO_MANY_ATTEMPTS
          ? { kind: "limited", retryAt: retryAtOf(e) }
          : { kind: "failed", text: authErrorText(e) },
      );
    }
  }

  return (
    <form
      aria-busy={resend.kind === "busy"}
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <AuthField
        id="resend-email"
        label={t("auth.email")}
        type="email"
        autoComplete="email"
        value={email}
        onChange={setTyped}
        readOnly={resend.kind === "busy"}
      />

      {resend.kind === "limited" && (
        <FormAlert tone="warning" icon={Clock}>
          <span className="flex flex-col gap-0.5">
            <span>{t("auth.guiLaiQuaGioiHan")}</span>
            {resend.retryAt !== null && (
              <span className="flex gap-1">
                <span>{t("auth.thuLaiLuc")}</span>
                <Moment ms={resend.retryAt} now={Date.now()} className="font-semibold" />
              </span>
            )}
          </span>
        </FormAlert>
      )}
      {resend.kind === "failed" && <FormAlert tone="danger">{resend.text}</FormAlert>}
      {resend.kind === "sent" && <MessageStatus>{t("auth.daGuiLaiThu")}</MessageStatus>}

      {resend.kind === "limited" ? (
        // Tat vi DIEU KIEN, ly do nam ngay phia tren — nen `.control-disabled`
        // (mo) chu khong nhu nut dang gui.
        <button
          type="button"
          disabled
          className="control-disabled min-h-touch w-full rounded-md bg-accent text-body font-semibold text-accent-foreground"
        >
          {t("auth.guiLaiThu")}
        </button>
      ) : (
        <SubmitButton busy={resend.kind === "busy"} label={t("auth.guiLaiThu")} />
      )}
    </form>
  );
}
