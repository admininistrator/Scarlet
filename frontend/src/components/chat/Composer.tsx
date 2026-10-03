import { ArrowUp, Globe, Mic, Paperclip, Square, Zap } from "lucide";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

import type { SendKeys, SendResult } from "../../features/chat/useChat";
import { DISPLAY_LOCALE, t } from "../../lib/i18n";
// `newKey` roi khoi file nay o T-3.7 (B-231): nut Thu lai nay cung phai sinh
// khoa, va mot ban chep thu hai cua duong lui "khong co secure context" la
// mot ban chep se chi duoc sua mot nua. Xem `lib/idempotency.ts`.
import { newKey } from "../../lib/idempotency";
import { useDock } from "../../lib/motion";
import { ComingSoon } from "../ui/ComingSoon";
import { AttachButtonNoVision } from "./Attachments";
import { Icon, StaticIcon } from "../ui/Icon";

/**
 * O nhap — gui, Dung, `Idempotency-Key` theo lan soan thao (T-3.4), ban v2
 * (T-S.10).
 *
 * KH tham chieu: §11.4 (C22), §18.1, §24.2b·S7, S9, S12, UC-02 dong 2, UC-07 ·
 * tasks.md T-3.4, T-S.10, B-143, B-205/NQ-78, NQ-111, NQ-114, NQ-115 · ban
 * T-HD2-v2 ("Scarlet Khung chinh v2", muc A, B, G) + T-HD5-v2 (muc 1, 2, 7).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOT LAN SOAN THAO = HAI KHOA (C22, §24.2b·S7)                         ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * §11.4 ta cai bay bang mot cau: *"FE sinh `Idempotency-Key` moi cho moi lan
 * bam"* — va khi ay toan bo co che cua T-2.8 vo dung, vi hai lan bam mang hai
 * khoa thi chung la hai request khac nhau voi Redis. Sua cua C22: khoa gan
 * voi **lan soan thao**.
 *
 * Tu T-S.10 mot lan soan thao mang HAI khoa (`SendKeys`): o man nhap cau dau
 * di qua hai route (`POST /conversations` roi `POST .../messages`), moi route
 * mot khoa. Ba dong luat ap cho CA CAP, va ca ba deu song o file nay chu
 * khong o `useChat`:
 *
 *   1. **Sinh** khi o nhap chuyen tu RONG sang CO CHU. Khong sinh luc mount
 *      (mot o nhap chua ai cham khong phai mot lan soan thao), khong sinh luc
 *      bam (do dung la cai bay).
 *   2. **Giu nguyen** qua moi lan thu lai: mang rot, `500`, `503` — cung mot
 *      cap khoa, vi nguoi dung van dang gui **cung mot cau**.
 *   3. **Bo** khi va chi khi `202` ve (`SendResult === "da-gui"`). Cau tiep
 *      theo nguoi dung go se sinh cap moi theo luat 1.
 *
 * Vi the chu da go cung **khong** duoc xoa truoc khi biet ket qua: mot o nhap
 * trong sau mot `500` thi khong con gi de bam gui lan hai, va luat 2 mat y
 * nghia.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  DUONG THOAT KHOI `409 IN_PROGRESS` (B-143, Cam bay ① cua T-3.4)     │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Ban ghi `in_progress` cua §11.4 song du `IDEMPOTENCY_TTL_S` = **24 gio**.
 * Khe con lai dung mot ca: tien trinh `api` bi giet GIUA `SET NX` va luc
 * response di ra. Khi ay luat 2 o tren tro thanh cai nhot ho: cung mot khoa,
 * cung mot `409`, suot 24 gio, khong nut nao ra. Nen `409 IN_PROGRESS` la ket
 * cuc duy nhat co mot nut: *"gui lai bang khoa moi"* — nguoi dung tu quyet
 * dinh bo mot cap khoa da ket, va cai gia (neu request cu van chay that thi
 * co hai luot) in thang tren bang canh bao.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  TRAN KY TU DEN TU SERVER, VA CHI HIEN KHI VUOT (A3/L4, NQ-115)      │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * `maxChars` la `message_max_chars` cua `GET /auth/me`; khong mot con so nao
 * viet tay o day. Ban v2 bo bo dem thuong truc: tran van chan Gui, nhung dong
 * bao chi hien khi **vuot** (`> maxChars`), va khong co nguong "sap cham tran"
 * nao — do se la mot con so moi phai vao config. `null` = **chua biet**: khong
 * bao, khong chan, tran that van dung o `422` cua server.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  PHIM: Enter GUI · Shift+Enter XUONG DONG (chot o T-3.4)             │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Dong nhac "Enter de gui…" da bo (NQ-115); quy uoc thi giu. `isComposing`
 * la dong bat buoc: bo go tieng Viet dung Enter de CHOT mot tu dang dung, va
 * thieu phep kiem nay thi nguoi go dau gui nham nua cau.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  "DANG CHAY" DEN TU `done`/`error` CUA §7.4 (Cam bay ③ cua T-3.4)    │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * `running` di vao nhu mot prop; file nay khong co bo dem thoi gian nao. Gui
 * va Dung la MOT nut — icon bien hinh `arrow-up` ⇄ `square` bang lo xo
 * `sendStop` (T-HD5-v2 muc 7) — nen no phai la cung mot phan tu qua lan doi.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  BO CUC v2 (T-HD2-v2) — KHUNG, KHONG CO DAI NEN                      │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Tu tren xuong: dong han muc (`quotaNotice`, chi khi ≤ nguong hoac het) ·
 * HOP nhap (vien `border-strong`, focus hien dan qua `motion-focus-ring`) ·
 * hang duoi (dong vuot tran ben trai, cho Model Picker ben phai — nut mo
 * picker dung lai o T-S.14). Man nhap (`docked === false`): `form` la mot o
 * cua luoi `1fr · auto · 1fr` cua `ChatScreen`, chiem hang 2–3 bang subgrid,
 * nen HOP nam o hang giua (tam hop = tam vung chat) va hang duoi nam o dau
 * hang 3 — dung ban ve muc A. Trong hoi thoai: khung o day, `4 + 44 + 8`.
 *
 * `form` la khung FLIP (`useDock`): cung MOT phan tu o hai bo cuc, nen o nhap
 * truot tu giua xuong day ma khong mat chu, khong mat khoa.
 */

export function Composer({
  running,
  enabled,
  maxChars,
  onSend,
  onStop,
  docked,
  modelPicker,
  quotaNotice,
  quotaBlocked = false,
  noVision = false,
}: {
  running: boolean;
  enabled: boolean;
  /** `message_max_chars` cua `GET /auth/me`; `null` = chua biet. */
  maxChars: number | null;
  onSend: (content: string, keys: SendKeys) => Promise<SendResult>;
  onStop: () => void;
  /** `false` = man nhap (o nhap giua man); `true` = trong hoi thoai (o day). */
  docked: boolean;
  /** Cho Model Picker o hang duoi, ben phai (NQ-115; T-S.14 dung lai nut). */
  modelPicker?: ReactNode;
  /** Dong han muc mot hang, ngay tren hop nhap (NQ-114) — `QuotaNotice`. */
  quotaNotice?: ReactNode;
  /**
   * T-3.11 — het quota system key va model dang chon KHONG di bang BYOK
   * (`quotaView.isSendBlocked`). Chi khoa nut GUI: chu van go duoc (de soan
   * san), va nut Dung cua mot luot dang chay khong bao gio bi khoa vi quota.
   */
  quotaBlocked?: boolean;
  /**
   * T-4.5 (S9) — model dang chon KHONG `vision` ⇒ nut dinh kem la
   * `AttachButtonNoVision` (tooltip noi ly do). Co `vision` ⇒ nut cho cua T-4.7.
   */
  noVision?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [keyLocked, setKeyLocked] = useState(false);
  //: Luat 1–3 cua C22. `ref` chu khong `useState`: hai lan bam trong cung mot
  //: luot render phai doc duoc CUNG mot gia tri, ma state thi chi doi o lan
  //: render sau — dung cai bay S5 dang do.
  const keysRef = useRef<SendKeys | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dock = useDock<HTMLFormElement>(docked);

  const charCount = [...draft].length;
  const overLimit = maxChars !== null && charCount > maxChars;
  const canSend = enabled && draft.trim() !== "" && !overLimit && !quotaBlocked;

  /*
    Hop nhap gian theo chu toi `--spacing-composer-max` roi cuon ben trong
    (ban ve, bang "Con so"). `rows={1}` khong tu gian; tran nam o class
    `max-h-composer-max`, file nay chi dat chieu cao = noi dung.
  */
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (el === null) {
      return;
    }
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [draft]);

  function freshKeys(): SendKeys {
    return { conversation: newKey(), message: newKey() };
  }

  function changeDraft(next: string): void {
    setDraft(next);
    // Luat 1 — rong ⇒ co chu la luc mot lan soan thao bat dau.
    if (next !== "" && keysRef.current === null) {
      keysRef.current = freshKeys();
    }
    // Xoa sach o nhap la bo han lan soan thao ay: cau sau la mot cau khac.
    if (next === "") {
      keysRef.current = null;
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
    keysRef.current ??= freshKeys();
    const result = await onSend(draft, keysRef.current);
    if (result === "da-gui") {
      // Luat 3 — va chi o day.
      keysRef.current = null;
      setKeyLocked(false);
      setDraft("");
      return;
    }
    // Luat 2: chu va cap khoa deu o nguyen. Nguoi dung bam Gui lan nua la
    // dung cap ay.
    setKeyLocked(result === "ket-khoa");
  }

  /** Duong thoat cua B-143 — nguoi dung tu quyet dinh bo mot cap khoa da ket. */
  function sendWithNewKey(): void {
    keysRef.current = freshKeys();
    setKeyLocked(false);
    void send();
  }

  return (
    <form
      ref={dock.ref}
      onAnimationEnd={dock.onAnimationEnd}
      data-phase={docked ? "docked" : "draft"}
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
      className={`motion-dock w-full px-gutter lg:px-gutter-lg ${
        docked
          ? "shrink-0 pb-[calc(--spacing(2)+env(safe-area-inset-bottom))]"
          : "row-span-2 row-start-2 grid grid-rows-subgrid"
      }`}
    >
      <div className="mx-auto flex w-full max-w-measure flex-col">
        {quotaNotice}
        <div
          className={`motion-focus-ring relative flex flex-col rounded-xl border bg-surface-panel ${
            overLimit
              ? "border-danger ring-1 ring-danger"
              : "border-border-strong focus-within:border-ring focus-within:shadow-focus"
          }`}
        >
          <label className="min-w-0">
            <span className="sr-only">{t("chat.oNhap")}</span>
            <textarea
              ref={textareaRef}
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
              rows={1}
              disabled={!enabled}
              aria-invalid={overLimit}
              placeholder={t("chat.oNhap")}
              // `text-input` 16 px (T-HD5-v2, token T-HD8) chu khong `text-body`
              // 15 px cua T-HD2-v2: nho hon 16 thi iOS phong to trang khi focus
              // (B-295 ②, NQ-133 ①).
              className="block max-h-composer-max w-full resize-none overflow-y-auto rounded-t-xl bg-transparent px-4 pt-3.5 pb-1.5 text-input text-foreground placeholder:text-muted focus-visible:outline-none disabled:opacity-50"
            />
          </label>

          <div className="flex items-center gap-0.5 px-1.5 pb-1.5">
            {/* §7b.2 — bon nut cho cua o nhap; khong mot handler nao (S12). */}
            {noVision ? (
              <AttachButtonNoVision />
            ) : (
              <ComingSoon
                planned="T-4.7"
                label={t("composer.attach")}
                icon={<StaticIcon icon={Paperclip} size={20} />}
              />
            )}
            <ComingSoon
              planned="T-6.7"
              label={t("composer.webSearch")}
              icon={<StaticIcon icon={Globe} size={18} />}
              toggle
            />
            <ComingSoon
              planned="T-7.9"
              label={t("composer.skill")}
              icon={<StaticIcon icon={Zap} size={20} />}
            />
            <span className="flex-1" />
            <ComingSoon
              planned="T-8.4"
              label={t("composer.voice")}
              icon={<StaticIcon icon={Mic} size={20} />}
            />
            {/*
              Gui ⇄ Dung: MOT phan tu, de icon bien hinh thay vi mot nut bi
              thay bang nut khac. Dang chay thi nut la `type="button"` — bam
              Dung khong duoc gui form.
            */}
            <button
              type={running ? "button" : "submit"}
              onClick={running ? onStop : undefined}
              disabled={running ? false : !canSend}
              aria-label={running ? t("chat.dung") : t("chat.gui")}
              title={!running && quotaBlocked ? t("quota.sendBlocked") : undefined}
              className="control-disabled motion-press grid size-touch shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground enabled:hover:bg-accent-hover"
            >
              <Icon icon={running ? Square : ArrowUp} spring="sendStop" size={20} />
            </button>
          </div>
        </div>

        {keyLocked && (
          <div
            role="alert"
            className="mt-2 flex flex-wrap items-center gap-3 rounded-md border border-border bg-warning-subtle px-3 py-2 text-sm text-warning-text"
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
      </div>

      <div className="mx-auto w-full max-w-measure">
        <div className="mt-1 flex min-h-touch items-center gap-2">
          {overLimit && maxChars !== null && (
            <p role="status" className="flex min-w-0 items-center gap-1.5 pl-1 text-sm text-danger-text">
              <span className="truncate">{t("composer.overLimit")}</span>
              <span className="tabular shrink-0 font-semibold">
                {charCount.toLocaleString(DISPLAY_LOCALE)} / {maxChars.toLocaleString(DISPLAY_LOCALE)}
              </span>
            </p>
          )}
          <div className="ml-auto shrink-0">{modelPicker}</div>
        </div>
      </div>
    </form>
  );
}
