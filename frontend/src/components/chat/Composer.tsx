import { useRef, useState, type ReactNode } from "react";

import type { SendResult } from "../../features/chat/useChat";
import { t } from "../../lib/i18n";
// `newKey` roi khoi file nay o T-3.7 (B-231): nut Thu lai nay cung phai sinh
// khoa, va mot ban chep thu hai cua duong lui "khong co secure context" la
// mot ban chep se chi duoc sua mot nua. Xem `lib/idempotency.ts`.
import { newKey } from "../../lib/idempotency";

/**
 * O nhap — gui, Dung, dem ky tu, `Idempotency-Key` theo lan soan thao (T-3.4).
 *
 * KH tham chieu: §11.4 (C22), §18.1, UC-02 dong 2 · tasks.md T-3.4, B-143,
 * B-205/NQ-78 · ban T-HD2 ("Scarlet Khung chinh").
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOT LAN SOAN THAO = MOT KHOA (C22)                                    ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * §11.4 ta cai bay bang mot cau: *"FE sinh `Idempotency-Key` moi cho moi lan
 * bam"* — va khi ay toan bo co che cua T-2.8 vo dung, vi hai lan bam mang hai
 * khoa thi chung la hai request khac nhau voi Redis. Sua cua C22: khoa gan
 * voi **lan soan thao**.
 *
 * Ba dong luat, va ca ba deu song o file nay chu khong o `useChat`:
 *
 *   1. **Sinh** khi o nhap chuyen tu RONG sang CO CHU. Khong sinh luc mount
 *      (mot o nhap chua ai cham khong phai mot lan soan thao), khong sinh luc
 *      bam (do dung la cai bay).
 *   2. **Giu nguyen** qua moi lan thu lai: mang rot, `500`, `503` — cung mot
 *      khoa, vi nguoi dung van dang gui **cung mot cau**.
 *   3. **Bo** khi va chi khi `202` ve (`KetQuaGui === "da-gui"`). Cau tiep
 *      theo nguoi dung go se sinh khoa moi theo luat 1.
 *
 * Vi the `ban` (chu da go) cung **khong** duoc xoa truoc khi biet ket qua:
 * mot o nhap trong sau mot `500` thi khong con gi de bam gui lan hai, va
 * luat 2 mat y nghia.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  DUONG THOAT KHOI `409 IN_PROGRESS` (B-143, Cam bay ① cua T-3.4)     │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Ban ghi `in_progress` cua §11.4 song du `IDEMPOTENCY_TTL_S` = **24 gio**.
 * Moi duong thoat binh thuong da duoc T-2.8 dong (response `<400` ghi de
 * thanh `done`, response loi **xoa** khoa, ngoai le khong ai bat cung xoa),
 * nen khe con lai dung mot ca: tien trinh `api` bi giet (SIGKILL/OOM) GIUA
 * `SET NX` va luc response di ra. Khi ay luat 2 o tren — dung thu giu cho
 * nguoi dung an toan — tro thanh cai nhot ho: cung mot khoa, cung mot `409`,
 * suot 24 gio, khong nut nao ra.
 *
 * Nen `409 IN_PROGRESS` la ket cuc duy nhat co mot nut: *"gui lai bang khoa
 * moi"*. No **khong** pha C22 — C22 cam sinh khoa moi mot cach tu dong o moi
 * lan bam, khong cam nguoi dung tu quyet dinh bo mot khoa da ket. Va vi day
 * la mot hanh dong co y, cai gia phai tra cung ro rang: neu request cu that
 * su van dang chay (chu khong phai da chet), bam nut nay sinh ra mot luot
 * thu hai. Cau chu tren nut phai noi dieu do.
 *
 * Phan backend cua B-143 (mot TTL rieng cho `in_progress`) van con bo ngo —
 * no thuoc T-2.8, khong thuoc day. Nut nay la lop phong thu FE, khong phai
 * ban va cua khe ay.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  TRAN KY TU DEN TU SERVER (A3/L4, B-205/NQ-78)                       │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * `maxChars` la `message_max_chars` cua `GET /auth/me`. Khong co mot con so
 * nao viet tay trong file nay: doi `MESSAGE_MAX_CHARS` trong `.env` phai lam
 * doi bo dem tren man hinh ma khong ai cham vao `.tsx`.
 *
 * `null` = **chua biet** (chua hoi xong, hoac lan hoi hong), khong phai
 * "khong co tran": bo dem an di, nut Gui khong bi chan, va tran that van dung
 * o `422` cua server — T-3.0 da dong duong vong bang `curl` roi, nen FE o day
 * la tien ich cho nguoi go chu khong phai mot lop bao ve.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  PHIM: Enter GUI · Shift+Enter XUONG DONG (chot o T-3.4)             │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * MOT quy uoc, khong hai: `Ctrl/Cmd+Enter` cua ban T-1.14 khong con nghia
 * rieng. Day la thoi quen cua moi chatbot va no khop voi ban T-HD2, noi o
 * nhap la mot `textarea rows={1}`.
 *
 * `isComposing` la dong bat buoc chu khong phai mot phep lich su: bo go
 * tieng Viet (Telex/VNI, IME cua he dieu hanh) dung Enter de CHOT mot tu dang
 * dung, va su kien ay den truoc `compositionend`. Thieu phep kiem nay thi
 * nguoi go dau tieng Viet se gui nham cau dang viet do — mot lan mot.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  "DANG CHAY" DEN TU `done`/`error` CUA §7.4 (Cam bay ③)              │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * `running` di vao nhu mot prop; file nay khong co mot bo dem thoi gian nao
 * va khong duoc co. Nut Gui ⇄ Dung doi chu theo dung no.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  THANH CONG CU DUOI O NHAP (B-242)                                   │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Mot khung: o nhap o tren, hang [picker model … Gui/Dung] o duoi — nguoi
 * dung chon bo cuc nay khi chot B-242 (ban T-HD2 chi ve o nhap + nut gui, ban
 * T-HD4 chi ghi "trigger o composer"). Picker di vao qua `modelPicker` chu
 * khong import thang: file nay tra loi "go va gui mot cau", con danh muc model
 * va ba tang mac dinh la viec cua `ChatScreen`. Vien va vong tieu diem thuoc
 * ve KHUNG (`focus-within`), vi o nhap khong con vien rieng.
 */

export function Composer({
  running,
  enabled,
  maxChars,
  onSend,
  onStop,
  modelPicker,
  quotaBar,
  quotaBlocked = false,
}: {
  running: boolean;
  enabled: boolean;
  /** `message_max_chars` cua `GET /auth/me`; `null` = chua biet. */
  maxChars: number | null;
  onSend: (content: string, key: string) => Promise<SendResult>;
  onStop: () => void;
  /** Nut mo Model Picker, dat o dau thanh cong cu duoi o nhap (B-242). */
  modelPicker?: ReactNode;
  /** T-3.11 — thanh quota, dat ngay tren o nhap. */
  quotaBar?: ReactNode;
  /**
   * T-3.11 — het quota system key va model dang chon KHONG di bang BYOK
   * (`quotaView.isSendBlocked`). Chi khoa nut GUI: chu van go duoc, va nut
   * Dung cua mot luot dang chay khong bao gio bi khoa vi quota.
   */
  quotaBlocked?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [keyLocked, setKeyLocked] = useState(false);
  //: Luat 1–3 cua C22. `ref` chu khong `useState`: hai lan bam trong cung mot
  //: luot render phai doc duoc CUNG mot gia tri, ma state thi chi doi o lan
  //: render sau — dung cai bay S5 dang do.
  const keyRef = useRef<string | null>(null);

  const charCount = [...draft].length;
  const overLimit = maxChars !== null && charCount > maxChars;
  const canSend = enabled && draft.trim() !== "" && !overLimit && !quotaBlocked;

  function changeDraft(next: string): void {
    setDraft(next);
    // Luat 1 — rong ⇒ co chu la luc mot lan soan thao bat dau.
    if (next !== "" && keyRef.current === null) {
      keyRef.current = newKey();
    }
    // Xoa sach o nhap la bo han lan soan thao ay: cau sau la mot cau khac.
    if (next === "") {
      keyRef.current = null;
      setKeyLocked(false);
    }
  }

  async function send(): Promise<void> {
    if (!canSend) {
      return;
    }
    // `??=` chu khong gan thang: `changeDraft` gan nhu luon da sinh khoa roi, va
    // ghi de o day chinh la cai bay C22 ta. Dong nay chi do ca dan chu vao o
    // nhap bang mot duong khong sinh ra `change` nao.
    keyRef.current ??= newKey();
    const result = await onSend(draft, keyRef.current);
    if (result === "da-gui") {
      // Luat 3 — va chi o day.
      keyRef.current = null;
      setKeyLocked(false);
      setDraft("");
      return;
    }
    // Luat 2: `ban` va `keyRef` deu o nguyen. Nguoi dung bam Gui lan nua la
    // dung khoa ay.
    setKeyLocked(result === "ket-khoa");
  }

  /** Duong thoat cua B-143 — nguoi dung tu quyet dinh bo mot khoa da ket. */
  function sendWithNewKey(): void {
    keyRef.current = newKey();
    setKeyLocked(false);
    void send();
  }

  return (
    <div className="shrink-0 border-t border-border bg-background px-gutter py-3 lg:px-gutter-lg">
      <form
        className="mx-auto flex max-w-measure flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        {quotaBar}
        <div className="motion-control flex flex-col rounded-lg border border-border-strong bg-surface-panel focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ring">
          <label className="min-w-0">
            <span className="sr-only">{t("chat.oNhap")}</span>
            <textarea
              value={draft}
              onChange={(e) => changeDraft(e.target.value)}
              onKeyDown={(e) => {
                // Bo go tieng Viet dung Enter de chot tu — xem docstring.
                if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) {
                  return;
                }
                e.preventDefault();
                void send();
              }}
              rows={3}
              disabled={!enabled}
              aria-invalid={overLimit}
              placeholder={t("chat.oNhap")}
              className="block min-h-touch w-full resize-none rounded-t-lg bg-transparent px-3 pt-3 pb-1 text-body text-foreground placeholder:text-muted focus-visible:outline-none disabled:opacity-50"
            />
          </label>

          <div className="flex items-center gap-2 px-2 pb-2">
            <div className="min-w-0 flex-1">{modelPicker}</div>

            {running ? (
              <button
                type="button"
                onClick={onStop}
                className="motion-press grid size-touch shrink-0 place-items-center rounded-lg border border-border-strong text-danger-text hover:bg-surface-hover"
              >
                <StopIcon />
                <span className="sr-only">{t("chat.dung")}</span>
              </button>
            ) : (
              <button
                type="submit"
                disabled={!canSend}
                title={quotaBlocked ? t("quota.sendBlocked") : undefined}
                className="motion-press grid size-touch shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground hover:bg-accent-hover disabled:opacity-50"
              >
                <SendIcon />
                <span className="sr-only">{t("chat.gui")}</span>
              </button>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span>{t("chat.phimGui")}</span>
          {maxChars !== null && (
            <span
              /*
                `role="status"` chu khong mot `<span>` cam: nguoi dung trinh
                doc man hinh cung phai biet minh sap cham tran, va `polite`
                nghia la no doi ho go xong mot nhip roi moi noi.
              */
              role="status"
              className={
                overLimit ? "tabular ml-auto text-danger-text" : "tabular ml-auto text-muted"
              }
            >
              {charCount} / {maxChars}
            </span>
          )}
        </div>

        {keyLocked && (
          <div
            role="alert"
            className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-warning-subtle px-3 py-2 text-sm text-warning-text"
          >
            <span>{t("chat.khoaKet")}</span>
            <button
              type="button"
              onClick={sendWithNewKey}
              className="motion-press h-touch rounded-md border border-border-strong px-3 text-base font-medium text-foreground hover:bg-surface-hover"
            >
              {t("chat.guiKhoaMoi")}
            </button>
          </div>
        )}
      </form>
    </div>
  );
}

const iconProps = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

const SendIcon = () => (
  <svg {...iconProps}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

const StopIcon = () => (
  <svg {...iconProps}>
    <rect x="7" y="7" width="10" height="10" rx="1.5" />
  </svg>
);
