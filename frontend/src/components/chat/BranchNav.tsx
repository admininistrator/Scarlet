import type { MessageOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { displayIndex, canGoBack, canGoForward } from "../../lib/tree";
import { IconButton } from "./IconButton";

/**
 * `‹ n/m ›` — hai nut 44 x 44 va mot con so. Ban T-HD3 hinh 2c, T-3.8.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOT COMPONENT, HAI LOAI BONG BONG                                     ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Ban T-HD3 ve khoi nay o hinh 2c ("dieu huong nhanh — ba trang thai": dau
 * day, giua day, cuoi day) va dat no duoi bong bong assistant. T-3.8 dung
 * DUNG khoi ay duoi ca bong bong nguoi dung, vi §8.2 sinh anh em o ca hai
 * cho va chung khac nhau ve NGUON chu khong ve hinh:
 *
 * | Thao tac       | Sinh anh em cua      | Bong bong mang `‹ n/m ›` |
 * |----------------|----------------------|--------------------------|
 * | Retry          | message **assistant**| assistant                |
 * | Sua cau hoi    | message **user**     | nguoi dung               |
 *
 * Bo hang duoi nghia la mot nhanh vua tao ra khong co duong nao quay lai tu
 * giao dien — UC-04 dong 1 ("khong xoa nhanh cu") van dung trong DB nhung
 * nguoi dung khong con thay nhanh cu o dau. Vi the no la mot file rieng chu
 * khong hai ban chep: 44 px la con so cua danh sach kiem T-HD3, va hai ban
 * chep la hai cho de no tut xuong 40 ma khong ai thay (cung ly le da tach
 * `IconButton` o T-3.7).
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  C13 — KHONG MOT PHEP DEM NAO O DAY                                  │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * `sibling_index`/`sibling_count` do SQL tinh (`get_path`, §8.3) va di theo
 * tung node. Bon cau hoi ma component nay phai tra loi — hien so may, con
 * lui duoc khong, con toi duoc khong, co nhanh khong — deu goi ham cua
 * `tree.ts`, va `displayIndex()` la CHO DUY NHAT cong 1 (B-60, NQ-33). Viet
 * `node.sibling_index + 1` o day la mo duong cho mot cho quen, va mot cho
 * quen thi man hinh hien `‹ 1/2 ›` cho ca hai nhanh ma khong test nao do.
 *
 * `nhan` la `aria-label` cua `role="group"`: mot man hinh co the co nhieu
 * `‹ n/m ›` cung luc (cau hoi da sua VA cau tra loi da retry), nen hai nhom
 * mang cung mot nhan la hai nhom khong phan biet duoc bang giong doc.
 */
export function BranchNav({
  node,
  label,
  onSwitchBranch,
}: {
  node: MessageOut;
  label: string;
  /** `-1` lui mot anh em, `+1` toi mot anh em. Xem `useChat.switchBranch`. */
  onSwitchBranch: (direction: -1 | 1) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex items-center">
      <IconButton
        label={t("chat.branchPrev")}
        glyph="‹"
        disabled={!canGoBack(node)}
        onClick={() => onSwitchBranch(-1)}
      />
      {/*
        Ban T-HD3: `tabular` nen be rong khong nhay khi qua 10 nhanh, va
        `min-w-10` (40 px) la con so cua chinh ban ve.
      */}
      <span className="tabular min-w-10 text-center text-sm text-muted">
        {displayIndex(node)} / {node.sibling_count}
      </span>
      <IconButton
        label={t("chat.branchNext")}
        glyph="›"
        disabled={!canGoForward(node)}
        onClick={() => onSwitchBranch(1)}
      />
    </div>
  );
}

/** Vach ngan hai nhom cua ban T-HD3: dieu huong nhanh | hanh dong. */
export function Divider() {
  return <span aria-hidden="true" className="mx-1 h-6 w-px bg-border" />;
}
