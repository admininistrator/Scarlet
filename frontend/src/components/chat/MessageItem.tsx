import { ChevronDown, ChevronRight, Pencil, RotateCcw } from "lucide";
import { useState } from "react";

import { effortLabel } from "../../features/models/reasoning";
import type { Feedback, MessageOut, ModelOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { hasSiblings, content, reasoningOf, type TreeState } from "../../lib/tree";
import { Icon, StaticIcon } from "../ui/Icon";
import { BranchNav, Divider } from "./BranchNav";
import { Hint } from "./Hint";
import { Markdown } from "./Markdown";
import { AnswerActions } from "./AnswerActions";
import { UserAttachments } from "./BubbleExtras";

/**
 * Mot bong bong tren duong di hien tai — ban T-HD3, §8.2, §7.4, C13.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BON TRANG THAI, VA CHUNG DEN TU DAU                                   ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * | Tren man hinh | Doc tu                                              |
 * |---------------|-----------------------------------------------------|
 * | dang cho      | `status` con `queued`/`streaming` MA chua co chu nao |
 * | dang stream   | `status` con `queued`/`streaming` VA da co chu       |
 * | xong          | `status` = `completed`/`cancelled`                   |
 * | loi           | `status` = `failed`, hoac `error_code` khac `null`   |
 *
 * "Chua co chu nao" phai duoc noi ra chu khong de bong bong rong: §7.4 ghi
 * *"FE khong duoc suy ra 'da xong' bang cach thay stream im lang. Im lang =
 * dang cho, hien trang thai cho"*. Bon trang thai nay la cho FE noi dieu do.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  MOT NGUON SU THAT CHO CHUOI CHU (Cam bay ① va ② cua T-3.5)          │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Component nay KHONG giu mot ban chu nao canh `inFlight`. `noiDung(cay, node)`
 * la cho duy nhat tra loi "message nay dang hien chu gi", va no da biet luat:
 * giua luot sinh `path[i].content` la chuoi RONG (worker chi ghi xuong
 * Postgres luc ket thuc, §7.2 ③) nen phai doc `inFlight`; sau `done` thi hai
 * ban giong nhau. Giu them mot ban o day la cho chu nhan doi sau mot lan F5,
 * vi duong dung lai tu Postgres cung phat `start` (T-1.14 ④).
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  HIEU NANG — quy tac 2 cua ban T-HD3                                 │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * Chip, dieu huong nhanh va hang nut chi duoc dung khi da xong. Nho vay 309
 * delta cua mot cau dai khong cham toi chung mot lan nao. Phan chu nam trong
 * `<Markdown>` da `memo`, va khong mot phan tu nao tren duong chu mang
 * `transition`/`animation`.
 *
 * Hang nut duoi cau tra loi (Sao chep · Thich · Khong thich · Thu lai · Doc
 * to) nam trong `AnswerActions` (T-3.7, T-S.15). Chung o mot file rieng chu
 * khong noi tiep vao day vi mot ly do doc duoc: file nay tra loi cau "bong
 * bong nao ve cai gi" (bon trang thai), con file kia tra loi "bam mot nut thi
 * gui gi len server" — va chi cau thu hai can mot bo test rieng.
 *
 * `‹ n/m ›` roi sang `BranchNav.tsx` o T-3.8, va cung luc do no moc them duoi
 * bong bong NGUOI DUNG: sua mot cau hoi sinh anh em cua message user (§8.2),
 * nen bo hang duoi nghia la nhanh vua tao khong co duong nao quay lai tu giao
 * dien. Xem docstring cua chinh file ay.
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  T-S.15 — BAN T-HD3-v2                                               │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * - **Chip "model · muc"** (ban ve 3c): model va muc DA DUNG de sinh chinh cau
 *   tra loi nay — `model_id`, `reasoning_effort` cua `MessageOut`, tuc cua
 *   Postgres — KHONG phai lua chon hien tai tren picker. Nho vay bam `‹` ve
 *   nhanh cu van thay chip cua model cu (UC-04 dong 4). Ten la `display_name`
 *   cua catalog (khong bao gio ten duong trung gian, NQ-119); hai manh ten va
 *   muc la hai `<span>`, dau "·" `aria-hidden`, khong ghep chuoi.
 * - **Khoi "Suy luan" chi dung khi co noi dung** (ban ve 3d): `reasoning?.trim()`
 *   — muc Off, model khong ho tro hay chuoi rong cho cung mot ket qua.
 * - **Mot nut Thu lai**, ca o hang nut lan o bong bong loi: model + muc dang
 *   chon tren picker (xem `AnswerActions`).
 */
export function MessageItem({
  node,
  tree,
  models,
  notes,
  running,
  busy,
  onRetry,
  onFeedback,
  onEdit,
  onSwitchBranch,
}: {
  node: MessageOut;
  tree: TreeState;
  /**
   * Danh muc `GET /models` — chi de doi `model_id` cua message thanh ten hien
   * thi cho chip. Model da bien mat khoi catalog thi chip hien `model_id` tho.
   */
  models: readonly ModelOut[];
  notes: string[];
  running: boolean;
  /**
   * Co mot thao tac doi cay dang bay. Nut "Luu" tat trong luc do — B-232:
   * `PATCH /messages/{id}` nam NGOAI vung phu idempotency cua §11.4 (NQ-93 co
   * y dung o chu "POST" cua A8), nen bam Luu hai lan la hai nhanh va hai hoa
   * don. Day la mot lop chan o FE chu khong phai mot ban va cho khe ay.
   */
  busy: boolean;
  /** Sinh lai bang model + muc tren picker. Xem `useChat.retry`. */
  onRetry: (messageId: string) => void;
  onFeedback: (messageId: string, value: Feedback | null) => void;
  onEdit: (messageId: string, newContent: string) => void;
  onSwitchBranch: (node: MessageOut, direction: -1 | 1) => void;
}) {
  const text = content(tree, node);
  const reasoning = reasoningOf(tree, node);

  if (node.role === "user") {
    return (
      <UserBubble
        node={node}
        text={text}
        busy={busy}
        onEdit={onEdit}
        onSwitchBranch={(direction) => onSwitchBranch(node, direction)}
      />
    );
  }

  const isError = node.status === "failed" || node.error_code !== null;
  const isOpen = node.status === "queued" || node.status === "streaming" || running;
  const waiting = !isError && isOpen && text === "";
  const streaming = !isError && isOpen && text !== "";
  const done = !isError && !isOpen;

  return (
    <article
      aria-label={t("chat.assistantLabel")}
      // T-3.9 / Cam bay ①: hoat anh o VUNG, chay mot lan khi tin mount.
      // T-S.19a (ban Tin nhan v3): KHONG bong bong — khong nen, vien, bo, dem
      // trong; loi nhan ra qua cham do, tieu de chu do va nut Thu lai nen do.
      className="motion-enter w-full max-w-measure"
    >
      <h3 className="mb-2 flex items-center gap-2 text-2xs font-semibold tracking-[0.08em] uppercase text-muted">
        <span
          aria-hidden="true"
          className={isError ? "size-2 rounded-full bg-danger" : "size-2 rounded-full bg-accent"}
        />
        {t("chat.assistantLabel")}
      </h3>

      {waiting && (
        <p aria-live="polite" className="flex min-h-6 items-center gap-2 text-body text-muted">
          {t("chat.waiting")}
          <span aria-hidden="true" className="size-1.5 rounded-full bg-muted motion-pulse" />
        </p>
      )}

      {streaming && (
        // `motion-none`: phan tu nay doi noi dung 300+ lan mot luot sinh (T-1.14).
        <div className="motion-none min-h-6 text-body text-foreground">
          <span className="sr-only">{t("chat.streaming")}</span>
          <Markdown text={text} streaming />
        </div>
      )}

      {/* Ban T-HD3: bong bong loi GIU lai phan chu da chay duoc, khong xoa. */}
      {isError && text !== "" && (
        <div className="mb-3 text-body text-foreground">
          <Markdown text={text} streaming={false} />
        </div>
      )}

      {isError && (
        <div className="flex flex-col gap-3">
          <p className="text-body font-semibold text-danger-text">{t("chat.errorTitle")}</p>
          {node.error_code !== null && (
            <p className="font-mono text-sm text-foreground">{node.error_code}</p>
          )}
          {/* Ban ve 3a/4: cung hanh vi, cung tooltip voi Thu lai o hang nut. */}
          <Hint label={t("chat.retryHint")}>
            <button
              type="button"
              onClick={() => onRetry(node.id)}
              className="motion-press inline-flex h-touch items-center gap-2 self-start rounded-md bg-danger pr-4 pl-3.5 text-base font-semibold text-danger-foreground hover:bg-danger-hover"
            >
              <StaticIcon icon={RotateCcw} size={16} />
              {t("chat.retry")}
            </button>
          </Hint>
        </div>
      )}

      {done && (
        <div className="motion-none mt-1 min-h-6 text-body text-foreground">
          <Markdown text={text} streaming={false} />
        </div>
      )}

      {done && reasoning.trim() !== "" && <ReasoningBlock text={reasoning} />}

      {done && (
        <>
          <ul className="mt-3 flex flex-wrap gap-2">
            {node.model_id !== null && (
              <ModelChip
                name={models.find((m) => m.id === node.model_id)?.display_name ?? node.model_id}
                effort={node.reasoning_effort}
              />
            )}
            {node.finish_reason !== null && node.finish_reason !== "stop" && (
              <Chip label={node.finish_reason} mono />
            )}
            {notes.map((chip, i) => (
              <Chip key={i} label={chip} />
            ))}
          </ul>

          <div className="mt-2 flex items-center gap-1">
            {hasSiblings(node) && (
              <>
                <BranchNav
                  node={node}
                  label={t("chat.branchLabel")}
                  onSwitchBranch={(direction) => onSwitchBranch(node, direction)}
                />
                <Divider />
              </>
            )}
            <AnswerActions
              text={text}
              feedback={node.feedback}
              collapse={hasSiblings(node)}
              onFeedback={(value) => onFeedback(node.id, value)}
              onRetry={() => onRetry(node.id)}
            />
          </div>
        </>
      )}
    </article>
  );
}

/**
 * Khoi "Suy luan" gap/mo — ban T-HD3-v2 3d. `button[aria-expanded]` cao 44
 * thay cho `<details>` cua v1; mui ten `chevron-right` ↔ `chevron-down` bien
 * hinh qua `morphicons` (S10). Ban ve khong ghi vai tro lo xo nao cho mui ten
 * nay — dung `submenuChevron` (gentle), vai tro cua mui ten "mo them" gan nhat.
 *
 * `whitespace-pre-wrap` giu tu v1: suy luan la chu tho nhieu dong, khong qua
 * markdown.
 */
function ReasoningBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 rounded-md border border-border bg-background">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={
          open
            ? "motion-control flex h-touch w-full items-center gap-2 rounded-t-md border-b border-border px-3 text-base font-medium text-foreground hover:bg-surface-hover"
            : "motion-control flex h-touch w-full items-center gap-2 rounded-md px-3 text-base font-medium text-foreground hover:bg-surface-hover"
        }
      >
        <Icon
          icon={open ? ChevronDown : ChevronRight}
          spring="submenuChevron"
          size={16}
          className="motion-icon text-muted"
        />
        {t("chat.reasoning")}
      </button>
      {open && <div className="motion-panel px-3 py-3 text-base whitespace-pre-wrap text-muted">{text}</div>}
    </div>
  );
}

/**
 * Chip "<model> · <muc>" — ban T-HD3-v2 3c. Khong co muc (model khong co khoi
 * `reasoning`) ⇒ chi ten model. "Off" VAN hien: model co hang muc va nguoi
 * dung da chon tat. Nhan muc qua `effortLabel` (tieng Anh trong `vi.json`,
 * NQ-118). Khong bam duoc, khong con tro tay.
 */
function ModelChip({ name, effort }: { name: string; effort: string | null }) {
  return (
    <li className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background px-2.5 py-1 text-xs leading-4 text-muted">
      <span>{name}</span>
      {effort !== null && (
        <>
          <span aria-hidden="true">·</span>
          <span>{effortLabel(effort)}</span>
        </>
      )}
    </li>
  );
}

/**
 * Bong bong nguoi dung — neo phai, khong vien, khong nhan (T-HD3 hinh 2b).
 *
 * Hai trang thai cua ban ve: mac dinh (chu + nut "Sua") va dang sua tai cho
 * (textarea + "Thoi"/"Luu"). T-3.8 them mot thu ban ve khong dat o day nhung
 * §8.2 doi: `‹ n/m ›` cua chinh message nay. Sua mot cau hoi = them mot cau
 * hoi ANH EM (`PATCH /messages/{id}`), nen con so nhanh cua mot message user
 * doi sau moi lan sua — va day la duong DUY NHAT quay lai cau hoi cu tu giao
 * dien (UC-04 dong 1 va dong 2).
 *
 * `ban` khoi tao bang chuoi rong roi duoc do day luc bam "Sua", khong phai
 * `useState(chu)`: giua luot sinh cua mot lan sua truoc, `chu` co the doi, va
 * mot `useState` chi doc gia tri khoi tao dung mot lan — ban nhap se ke lai
 * cau cu ma khong ai giai thich duoc tai sao.
 */
function UserBubble({
  node,
  text,
  busy,
  onEdit,
  onSwitchBranch,
}: {
  node: MessageOut;
  text: string;
  busy: boolean;
  onEdit: (messageId: string, newContent: string) => void;
  onSwitchBranch: (direction: -1 | 1) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  if (editing) {
    return (
      <article
        aria-label={t("chat.editing")}
        className="mr-0 ml-auto w-full max-w-bubble-user"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim() !== "") {
              onEdit(node.id, draft);
              setEditing(false);
            }
          }}
        >
          <label className="block">
            <span className="sr-only">{t("chat.editing")}</span>
            <textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={3}
              className="w-full resize-y rounded-md border border-border-strong bg-surface-panel p-3 text-body text-foreground"
            />
          </label>
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="h-touch rounded-md px-4 text-base font-medium hover:bg-surface-hover motion-press"
            >
              {t("chat.cancel")}
            </button>
            {/*
              `disabled` khi dang ban — B-232. Duong sua cau hoi di qua `PATCH`,
              tuc ngoai vung phu idempotency cua §11.4, nen bam hai lan la hai
              nhanh va hai hoa don. Mot nut bi khoa khong phai lop bao ve that
              (client nao cung go duoc), nhung no la lop duy nhat hom nay co.
            */}
            <button
              type="submit"
              disabled={busy}
              className="h-touch rounded-md bg-accent px-4 text-base font-semibold text-accent-foreground hover:bg-accent-hover disabled:bg-surface-hover disabled:text-disabled-foreground motion-press"
            >
              {t("chat.save")}
            </button>
          </div>
        </form>
      </article>
    );
  }

  return (
    <article
      aria-label={t("chat.userLabel")}
      // T-S.19a (ban Tin nhan v3): neo phai, rong theo chu (toi da 560), khong
      // nen, khong vien, khong nhan.
      className="mr-0 ml-auto flex w-fit max-w-bubble-user flex-col gap-1"
    >
      {/*
        T-4.7 — tep TREN chu (ban T-HD3-v2 3e), tu `attachments` cua duong di:
        F5 van hien (UC-06 dong 5). `url` ky moi o moi lan doc duong di (B-343).
      */}
      {node.attachments !== undefined && node.attachments.length > 0 && (
        <div className="flex justify-end">
          <UserAttachments
            items={node.attachments.map((a) => ({
              id: a.id,
              kind: a.kind,
              name: a.name,
              bytes: a.bytes,
              thumbnailUrl: a.url ?? undefined,
            }))}
          />
        </div>
      )}
      {/* Tin nhan cua nguoi dung la chu tho: no khong di qua mot model nao,
          va render markdown o day nghia la nguoi go ``` bi mat dau ```.
          Tin chi co tep (T-4.4a: `content` rong) ⇒ khong ve doan rong. */}
      {text !== "" && <p className="m-0 text-body whitespace-pre-wrap text-foreground">{text}</p>}
      {/*
        Cung mot ngu phap voi hang duoi bong bong assistant: dieu huong nhanh,
        vach ngan, roi hanh dong. Neo phai vi ca bong bong neo phai (T-HD3 2b).
      */}
      <div className="flex flex-wrap items-center justify-end gap-1">
        {hasSiblings(node) && (
          <>
            <BranchNav
              node={node}
              label={t("chat.branchLabelCauHoi")}
              onSwitchBranch={onSwitchBranch}
            />
            <Divider />
          </>
        )}
        {/* Ban T-HD3-v2 3g: nut chu co them icon Lucide `pencil`. */}
        <button
          type="button"
          onClick={() => {
            setDraft(text);
            setEditing(true);
          }}
          className="motion-press inline-flex h-touch items-center gap-1.5 rounded-md px-3 text-base font-medium text-muted hover:bg-surface-hover"
        >
          <StaticIcon icon={Pencil} size={16} />
          {t("chat.edit")}
        </button>
      </div>
    </article>
  );
}

function Chip({ label, mono }: { label: string; mono?: boolean }) {
  return (
    <li
      className={
        mono
          ? "rounded-full border border-border bg-background px-2.5 py-1 font-mono text-2xs text-muted"
          : "rounded-full border border-border bg-background px-2.5 py-1 text-2xs text-muted"
      }
    >
      {label}
    </li>
  );
}
