import { useState } from "react";

import type { DanhGia, MessageRa } from "../../lib/api";
import { t } from "../../lib/i18n";
import { coAnhEm, noiDung, phanReasoning, type TrangThaiCay } from "../../lib/tree";
import { BranchNav, VachNgan } from "./BranchNav";
import { Markdown } from "./Markdown";
import { NutDuoiCauTraLoi } from "./NutDuoiCauTraLoi";

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
 * nam trong `NutDuoiCauTraLoi` (T-3.7). Chung o mot file rieng chu khong noi
 * tiep vao day vi mot ly do doc duoc: file nay tra loi cau "bong bong nao ve
 * cai gi" (bon trang thai), con file kia tra loi "bam mot nut thi gui gi len
 * server" — va chi cau thu hai can mot bo test rieng.
 *
 * `‹ n/m ›` roi sang `BranchNav.tsx` o T-3.8, va cung luc do no moc them duoi
 * bong bong NGUOI DUNG: sua mot cau hoi sinh anh em cua message user (§8.2),
 * nen bo hang duoi nghia la nhanh vua tao khong co duong nao quay lai tu giao
 * dien. Xem docstring cua chinh file ay.
 */
export function MessageItem({
  node,
  cay,
  ghiChu,
  dangChay,
  dangBan,
  modelDangChon,
  onThuLai,
  onDanhGia,
  onSua,
  onChuyenNhanh,
}: {
  node: MessageRa;
  cay: TrangThaiCay;
  ghiChu: string[];
  dangChay: boolean;
  /**
   * Co mot thao tac doi cay dang bay. Nut "Luu" tat trong luc do — B-232:
   * `PATCH /messages/{id}` nam NGOAI vung phu idempotency cua §11.4 (NQ-93 co
   * y dung o chu "POST" cua A8), nen bam Luu hai lan la hai nhanh va hai hoa
   * don. Day la mot lop chan o FE chu khong phai mot ban va cho khe ay.
   */
  dangBan: boolean;
  /** Model dang chon tren picker — nut "Doi model & thu lai" gui no (T-3.6). */
  modelDangChon: string | null;
  /** `modelId` vang mat = giu nguyen model cu. Xem `useChat.thuLai`. */
  onThuLai: (messageId: string, modelId?: string) => void;
  onDanhGia: (messageId: string, gia: DanhGia | null) => void;
  onSua: (messageId: string, noiDungMoi: string) => void;
  onChuyenNhanh: (node: MessageRa, huong: -1 | 1) => void;
}) {
  const chu = noiDung(cay, node);
  const reasoning = phanReasoning(cay, node);

  if (node.role === "user") {
    return (
      <UserBubble
        node={node}
        chu={chu}
        dangBan={dangBan}
        onSua={onSua}
        onChuyenNhanh={(huong) => onChuyenNhanh(node, huong)}
      />
    );
  }

  const laLoi = node.status === "failed" || node.error_code !== null;
  const chuaKhep = node.status === "queued" || node.status === "streaming" || dangChay;
  const dangCho = !laLoi && chuaKhep && chu === "";
  const dangStream = !laLoi && chuaKhep && chu !== "";
  const xong = !laLoi && !chuaKhep;

  return (
    <article
      aria-label={t("chat.assistantLabel")}
      // T-3.9 / Cam bay ①: hoat anh o VUNG, chay mot lan khi bong bong mount.
      // Hai nhanh chung mot `animation` nen doi sang trang thai loi khong kich lai.
      className={
        laLoi
          ? "motion-enter w-full rounded-bubble border border-danger bg-danger-subtle px-5 py-4"
          : "motion-enter w-full rounded-bubble border border-border bg-surface-assistant px-5 py-4"
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
        // `motion-none`: phan tu nay doi noi dung 300+ lan mot luot sinh (T-1.14).
        <div className="motion-none min-h-6 text-body text-foreground">
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
            className="h-touch self-start rounded-md bg-danger px-4 text-base font-semibold text-danger-foreground hover:bg-danger-hover motion-press"
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
              <>
                <BranchNav
                  node={node}
                  nhan={t("chat.branchLabel")}
                  onChuyenNhanh={(huong) => onChuyenNhanh(node, huong)}
                />
                <VachNgan />
              </>
            )}
            <NutDuoiCauTraLoi
              chu={chu}
              feedback={node.feedback}
              modelDangDung={node.model_id}
              modelDangChon={modelDangChon}
              onDanhGia={(gia) => onDanhGia(node.id, gia)}
              onThuLai={() => onThuLai(node.id)}
              onThuLaiModel={(modelId) => onThuLai(node.id, modelId)}
            />
          </div>
        </>
      )}
    </article>
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
  chu,
  dangBan,
  onSua,
  onChuyenNhanh,
}: {
  node: MessageRa;
  chu: string;
  dangBan: boolean;
  onSua: (messageId: string, noiDungMoi: string) => void;
  onChuyenNhanh: (huong: -1 | 1) => void;
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
              disabled={dangBan}
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
      className="mr-0 ml-auto flex w-full max-w-bubble-user flex-col gap-1 rounded-bubble bg-surface-user px-4 py-3"
    >
      {/* Tin nhan cua nguoi dung la chu tho: no khong di qua mot model nao,
          va render markdown o day nghia la nguoi go ``` bi mat dau ```. */}
      <p className="m-0 text-body whitespace-pre-wrap text-foreground">{chu}</p>
      {/*
        Cung mot ngu phap voi hang duoi bong bong assistant: dieu huong nhanh,
        vach ngan, roi hanh dong. Neo phai vi ca bong bong neo phai (T-HD3 2b).
      */}
      <div className="flex flex-wrap items-center justify-end gap-1">
        {coAnhEm(node) && (
          <>
            <BranchNav
              node={node}
              nhan={t("chat.branchLabelCauHoi")}
              onChuyenNhanh={onChuyenNhanh}
            />
            <VachNgan />
          </>
        )}
        <button
          type="button"
          onClick={() => {
            setBan(chu);
            setDangSua(true);
          }}
          className="h-touch rounded-md px-3 text-base font-medium text-muted hover:bg-surface-hover motion-press"
        >
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
