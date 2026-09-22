import { useState } from "react";

import type { MessageRa } from "../../lib/api";
import { t } from "../../lib/i18n";
import {
  chiSoHienThi,
  coAnhEm,
  coTheLui,
  coTheToi,
  noiDung,
  phanReasoning,
  type TrangThaiCay,
} from "../../lib/tree";
import { Markdown } from "./Markdown";

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
 * Component nay KHONG giu mot ban chu nao canh `dangBay`. `noiDung(cay, node)`
 * la cho duy nhat tra loi "message nay dang hien chu gi", va no da biet luat:
 * giua luot sinh `path[i].content` la chuoi RONG (worker chi ghi xuong
 * Postgres luc ket thuc, §7.2 ③) nen phai doc `dangBay`; sau `done` thi hai
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
 * Nam nut duoi cau tra loi (Copy · Thich · Khong thich · Thu lai · Doi model)
 * la T-3.7 — o day chi co Thu lai va Sua nhu T-1.14 da co, mac ao cua T-HD3.
 */
export function MessageItem({
  node,
  cay,
  ghiChu,
  dangChay,
  onThuLai,
  onSua,
  onChuyenNhanh,
}: {
  node: MessageRa;
  cay: TrangThaiCay;
  ghiChu: string[];
  dangChay: boolean;
  onThuLai: (messageId: string) => void;
  onSua: (messageId: string, noiDungMoi: string) => void;
  onChuyenNhanh: (node: MessageRa, huong: -1 | 1) => void;
}) {
  const chu = noiDung(cay, node);
  const reasoning = phanReasoning(cay, node);

  if (node.role === "user") {
    return <UserBubble node={node} chu={chu} onSua={onSua} />;
  }

  const laLoi = node.status === "failed" || node.error_code !== null;
  const chuaKhep = node.status === "queued" || node.status === "streaming" || dangChay;
  const dangCho = !laLoi && chuaKhep && chu === "";
  const dangStream = !laLoi && chuaKhep && chu !== "";
  const xong = !laLoi && !chuaKhep;

  return (
    <article
      aria-label={t("chat.assistantLabel")}
      className={
        laLoi
          ? "w-full rounded-bubble border border-danger bg-danger-subtle px-5 py-4"
          : "w-full rounded-bubble border border-border bg-surface-assistant px-5 py-4"
      }
    >
      <h3 className="mb-2 flex items-center gap-2 text-2xs font-semibold tracking-wider uppercase text-muted">
        <span
          aria-hidden="true"
          className={laLoi ? "size-2 rounded-full bg-danger" : "size-2 rounded-full bg-accent"}
        />
        {t("chat.assistantLabel")}
      </h3>

      {dangCho && (
        <p aria-live="polite" className="flex min-h-6 items-center gap-2 text-body text-muted">
          {t("chat.waiting")}
          <span aria-hidden="true" className="size-1.5 rounded-full bg-muted motion-pulse" />
        </p>
      )}

      {dangStream && (
        <div className="min-h-6 text-body text-foreground">
          <span className="sr-only">{t("chat.streaming")}</span>
          <Markdown text={chu} streaming />
        </div>
      )}

      {/* Ban T-HD3: bong bong loi GIU lai phan chu da chay duoc, khong xoa. */}
      {laLoi && chu !== "" && (
        <div className="mb-3 text-body text-foreground">
          <Markdown text={chu} streaming={false} />
        </div>
      )}

      {laLoi && (
        <div className="flex flex-col gap-3">
          <p className="text-body font-medium text-danger-text">{t("chat.errorTitle")}</p>
          {node.error_code !== null && (
            <p className="font-mono text-sm text-foreground">{node.error_code}</p>
          )}
          <button
            type="button"
            onClick={() => onThuLai(node.id)}
            className="h-touch self-start rounded-md bg-danger px-4 text-base font-semibold text-danger-foreground hover:bg-danger-hover motion-control"
          >
            {t("chat.errorRetry")}
          </button>
        </div>
      )}

      {xong && (
        <div className="text-body text-foreground">
          <Markdown text={chu} streaming={false} />
        </div>
      )}

      {xong && reasoning !== "" && (
        <details className="mt-3 rounded-md border border-border bg-background">
          <summary className="flex h-touch cursor-pointer list-none items-center gap-2 px-3 text-base font-medium">
            <span aria-hidden="true">▸</span>
            {t("chat.reasoning")}
          </summary>
          <div className="border-t border-border px-3 py-3 text-base whitespace-pre-wrap text-muted">
            {reasoning}
          </div>
        </details>
      )}

      {xong && (
        <>
          <ul className="mt-3 flex flex-wrap gap-2">
            {node.model_id !== null && <Chip label={node.model_id} mono />}
            {node.finish_reason !== null && node.finish_reason !== "stop" && (
              <Chip label={node.finish_reason} mono />
            )}
            {ghiChu.map((chip, i) => (
              <Chip key={i} label={chip} />
            ))}
          </ul>

          <div className="mt-2 flex flex-wrap items-center gap-1">
            {coAnhEm(node) && (
              <BranchNav node={node} onChuyenNhanh={(huong) => onChuyenNhanh(node, huong)} />
            )}
            <button
              type="button"
              onClick={() => onThuLai(node.id)}
              className="h-touch rounded-md px-3 text-base font-medium text-foreground hover:bg-surface-hover motion-control"
            >
              {t("chat.errorRetry")}
            </button>
          </div>
        </>
      )}
    </article>
  );
}

/** Bong bong nguoi dung — neo phai, khong vien, khong nhan (T-HD3 hinh 2b). */
function UserBubble({
  node,
  chu,
  onSua,
}: {
  node: MessageRa;
  chu: string;
  onSua: (messageId: string, noiDungMoi: string) => void;
}) {
  const [dangSua, setDangSua] = useState(false);
  const [ban, setBan] = useState("");

  if (dangSua) {
    return (
      <article
        aria-label={t("chat.editing")}
        className="mr-0 ml-auto w-full max-w-bubble-user rounded-bubble border border-border-strong bg-surface-user px-4 py-3"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (ban.trim() !== "") {
              onSua(node.id, ban);
              setDangSua(false);
            }
          }}
        >
          <label className="block">
            <span className="sr-only">{t("chat.editing")}</span>
            <textarea
              autoFocus
              value={ban}
              onChange={(e) => setBan(e.target.value)}
              rows={3}
              className="w-full resize-y rounded-md border border-border-strong bg-surface-panel p-3 text-body text-foreground"
            />
          </label>
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDangSua(false)}
              className="h-touch rounded-md px-4 text-base font-medium hover:bg-surface-hover motion-control"
            >
              {t("chat.cancel")}
            </button>
            <button
              type="submit"
              className="h-touch rounded-md bg-accent px-4 text-base font-semibold text-accent-foreground hover:bg-accent-hover motion-control"
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
      className="mr-0 ml-auto flex w-full max-w-bubble-user flex-col gap-1 rounded-bubble bg-surface-user px-4 py-3"
    >
      {/* Tin nhan cua nguoi dung la chu tho: no khong di qua mot model nao,
          va render markdown o day nghia la nguoi go ``` bi mat dau ```. */}
      <p className="m-0 text-body whitespace-pre-wrap text-foreground">{chu}</p>
      <button
        type="button"
        onClick={() => {
          setBan(chu);
          setDangSua(true);
        }}
        className="h-touch self-end rounded-md px-3 text-base font-medium text-muted hover:bg-surface-hover motion-control"
      >
        {t("chat.edit")}
      </button>
    </article>
  );
}

/** `‹ n/m ›` — hai nut 44 x 44 va mot con so. Ban T-HD3 hinh 2c. */
function BranchNav({
  node,
  onChuyenNhanh,
}: {
  node: MessageRa;
  onChuyenNhanh: (huong: -1 | 1) => void;
}) {
  return (
    <div role="group" aria-label={t("chat.branchLabel")} className="flex items-center">
      <IconButton
        label={t("chat.branchPrev")}
        glyph="‹"
        disabled={!coTheLui(node)}
        onClick={() => onChuyenNhanh(-1)}
      />
      {/* chiSoHienThi() la cho duy nhat doi 0-based sang so nguoi doc (B-60) */}
      <span className="tabular min-w-10 text-center text-sm text-muted">
        {chiSoHienThi(node)} / {node.sibling_count}
      </span>
      <IconButton
        label={t("chat.branchNext")}
        glyph="›"
        disabled={!coTheToi(node)}
        onClick={() => onChuyenNhanh(1)}
      />
    </div>
  );
}

function IconButton({
  label,
  glyph,
  onClick,
  disabled,
}: {
  label: string;
  glyph: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="grid size-touch place-items-center rounded-md border border-transparent text-muted hover:bg-surface-hover disabled:text-disabled-foreground motion-control"
    >
      <span aria-hidden="true" className="text-lg">
        {glyph}
      </span>
    </button>
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
