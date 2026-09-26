import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, Copy, Ellipsis, RotateCcw, ThumbsDown, ThumbsUp, Volume2 } from "lucide";
import { useCallback, useState } from "react";

import type { Feedback } from "../../lib/api";
import { copyText } from "../../lib/clipboard";
import { t } from "../../lib/i18n";
import { ComingSoon } from "../ui/ComingSoon";
import { StaticIcon } from "../ui/Icon";
import { MENU_ITEM_CLASS, MenuDismissContext } from "../ui/menu";
import { IconButton } from "./IconButton";

/**
 * Hang nut duoi mot cau tra loi da xong — T-3.7, ban T-HD3-v2 (T-S.15), UC-02
 * dong 5.
 *
 * KH tham chieu: UC-02, UC-04, §18.2, §8.2, §24.2b·S4, S12 · tasks.md T-3.7,
 * T-3.7a, T-S.15, B-231, B-244 · NQ-118, NQ-121 · CLAUDE.md A8.
 *
 *     Sao chep · Thich · Khong thich · Thu lai · Doc to (cho)
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOT NUT THU LAI (T-S.15, §24.2b·S4)                                   ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Ban T-3.7 co hai nut: "Thu lai" (giu model cu) va "Doi model & thu lai"
 * (model tren picker). NQ-118 gop lam mot: nut duy nhat sinh lai bang model
 * **va** muc dang chon tren picker — `onRetry` khong nhan tham so nao, vi
 * `useChat.retry` la noi duy nhat doc picker (hai noi doc la hai gia tri co
 * the lech nhau). Nguoi quen nut cu khong tu doan ra dieu do, nen tooltip noi
 * no: "Tao lai bang model dang chon" (Cam bay ① cua T-S.15). Tooltip KHONG ghi
 * ten model — ten co the doi ngay truoc khi bam (ban ve 3b).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHONG MOT TRANG THAI NAO CUA SERVER DUOC GIU O DAY                    ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `feedback` di VAO nhu mot prop va no den tu `MessageOut` cua duong di, tuc
 * tu Postgres. Component nay KHONG co `useState` nao cho Thich/Khong thich —
 * "Viec" dong 3 cua T-3.7 viet ro, va ly do la F5: mot ban sao o FE se sang
 * len ngay luc bam roi bien mat sau khi tai lai trang, tuc man hinh noi doi
 * trong dung khoang thoi gian nguoi dung tin no nhat.
 *
 * Hai `useState` o day la trang thai cua **trinh duyet nay, giay nay**: `copied`
 * (chu "Da sao chep" trong 1,6 s) va `menuOpen` (menu "…"). Khong cai nao co
 * ban tren server de lech.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  BAM LAI = GO (ban T-HD3)                                            │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Bam Thich khi dang Thich thi gui `null`, tuc go danh gia. Bam nham Dislike
 * ma khong rut lai duoc la mot nut chi bam duoc mot lan trong doi — chinh la
 * cau T-3.7a dung de chon `value: null` thay vi mot endpoint `DELETE`.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  375 PX — GAP VAO "…" (ban T-HD3-v2 muc 3f)                          │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Co nhanh (`collapse`) thi hang = `‹ n/m ›` 128 + vach 13 + 5 nut: vuot 311 px
 * long bong bong. Duoi `sm` (640 px) Thich, Khong thich va Doc to gap vao menu
 * "…" (Radix `DropdownMenu`): con 128 + 13 + 3 × 44 + 4 × 4 = 289 px. Khong
 * nhanh thi 5 nut (236 px) vua, khong can "…". Ba nut bi an van nam trong
 * DOM (`hidden sm:flex`) — mot phep do o 375 px phai bo qua chung.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  KHONG CO O NHAP LY DO (B-244)                                       │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * §18.2 cho phep mot `reason` kem Dislike va `api.sendFeedback` mo san duong cho
 * no, nhung hom nay mot ly do gui len thi **khong doc lai duoc o dau**:
 * `MessageOut` co y khong mang `feedback_reason`. Ban T-HD3-v2 cung chi ve hai
 * nut.
 */
export function AnswerActions({
  text,
  feedback,
  collapse,
  onFeedback,
  onRetry,
}: {
  /** Chu se vao clipboard — noi dung cau tra loi, khong kem chip hay nhan. */
  text: string;
  /** `MessageOut.feedback`, tuc tu server. `null` = chua ai bam gi. */
  feedback: Feedback | null;
  /** Hang co `‹ n/m ›` — duoi `sm` gap Thich, Khong thich, Doc to vao "…". */
  collapse: boolean;
  onFeedback: (value: Feedback | null) => void;
  /** Sinh lai bang model + muc tren picker — xem `useChat.retry`. */
  onRetry: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  const handleCopy = useCallback(() => {
    void copyText(text).then((done) => {
      if (!done) {
        return;
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    });
  }, [text]);

  const liked = feedback === "like";
  const disliked = feedback === "dislike";
  const toggleLike = () => onFeedback(liked ? null : "like");
  const toggleDislike = () => onFeedback(disliked ? null : "dislike");

  return (
    <>
      <IconButton label={copied ? t("chat.copied") : t("chat.copy")} icon={Copy} onClick={handleCopy} />
      <div className={collapse ? "hidden items-center gap-1 sm:flex" : "flex items-center gap-1"}>
        <IconButton
          label={liked ? t("chat.liked") : t("chat.like")}
          icon={ThumbsUp}
          pressed={liked}
          onClick={toggleLike}
        />
        <IconButton
          label={disliked ? t("chat.disliked") : t("chat.dislike")}
          icon={ThumbsDown}
          pressed={disliked}
          onClick={toggleDislike}
        />
      </div>
      <IconButton label={t("chat.retry")} hint={t("chat.retryHint")} icon={RotateCcw} onClick={onRetry} />
      <div className={collapse ? "hidden sm:block" : "block"}>
        <ComingSoon planned="T-8.4" label={t("chat.readAloud")} icon={<StaticIcon icon={Volume2} size={18} />} />
      </div>

      {collapse && (
        <DropdownMenu.Root open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenu.Trigger
            aria-label={t("chat.moreActions")}
            className="motion-press grid size-touch place-items-center rounded-md border border-transparent text-muted hover:bg-surface-hover hover:text-foreground data-[state=open]:bg-surface-hover sm:hidden"
          >
            <StaticIcon icon={Ellipsis} size={18} />
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={6}
              className="motion-popover z-50 w-56 rounded-lg border border-border bg-surface-panel p-1.5 shadow-popover"
            >
              {/* Esc khi dang o muc cho (tooltip mo) dong CA menu — B-308 ②. */}
              <MenuDismissContext.Provider value={closeMenu}>
                <DropdownMenu.CheckboxItem checked={liked} onCheckedChange={toggleLike} className={MENU_ITEM_CLASS}>
                  <StaticIcon icon={ThumbsUp} size={18} className={liked ? "text-accent-text" : "text-muted"} />
                  <span className="flex-1">{liked ? t("chat.liked") : t("chat.like")}</span>
                  <DropdownMenu.ItemIndicator>
                    <StaticIcon icon={Check} size={16} className="text-accent-text" />
                  </DropdownMenu.ItemIndicator>
                </DropdownMenu.CheckboxItem>
                <DropdownMenu.CheckboxItem
                  checked={disliked}
                  onCheckedChange={toggleDislike}
                  className={MENU_ITEM_CLASS}
                >
                  <StaticIcon icon={ThumbsDown} size={18} className={disliked ? "text-accent-text" : "text-muted"} />
                  <span className="flex-1">{disliked ? t("chat.disliked") : t("chat.dislike")}</span>
                  <DropdownMenu.ItemIndicator>
                    <StaticIcon icon={Check} size={16} className="text-accent-text" />
                  </DropdownMenu.ItemIndicator>
                </DropdownMenu.CheckboxItem>
                <DropdownMenu.Separator className="my-1 h-px bg-divider" />
                <ComingSoon
                  menuItem
                  planned="T-8.4"
                  label={t("chat.readAloud")}
                  icon={<StaticIcon icon={Volume2} size={18} className="text-muted" />}
                />
              </MenuDismissContext.Provider>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      )}
    </>
  );
}
