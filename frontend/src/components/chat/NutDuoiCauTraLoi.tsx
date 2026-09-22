import { useCallback, useState } from "react";

import type { DanhGia } from "../../lib/api";
import { saoChep } from "../../lib/clipboard";
import { t } from "../../lib/i18n";
import { IconButton } from "./IconButton";

/**
 * Nam nut duoi mot cau tra loi da xong — T-3.7, ban T-HD3, UC-02 dong 5.
 *
 * KH tham chieu: UC-02, UC-04, §18.2, §8.2 · tasks.md T-3.7, T-3.7a, B-231,
 * B-244 · CLAUDE.md A8.
 *
 *     Sao chep · Thich · Khong thich · Thu lai · Doi model & thu lai
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHONG MOT TRANG THAI NAO CUA SERVER DUOC GIU O DAY                    ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `feedback` di VAO nhu mot prop va no den tu `MessageRa` cua duong di, tuc
 * tu Postgres. Component nay KHONG co `useState` nao cho Thich/Khong thich —
 * "Viec" dong 3 cua T-3.7 viet ro, va ly do la F5: mot ban sao o FE se sang
 * len ngay luc bam roi bien mat sau khi tai lai trang, tuc man hinh noi doi
 * trong dung khoang thoi gian nguoi dung tin no nhat.
 *
 * Mot `useState` duy nhat o day la `daChep` — trang thai cua **trinh duyet
 * nay, giay nay** (chu "Da sao chep" trong 1,6 s). No khong co ban nao tren
 * server de lech.
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
 * │  HAI NUT THU LAI, VA CHUNG KHAC NHAU DUNG MOT CHO                    │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * "Thu lai" gui `POST .../retry` **khong** kem `model_id`, nen backend dung
 * lai dung model da sinh ra cau tra loi nay (`_chon_model`). "Doi model & thu
 * lai" gui `modelDangChon` — model dang chon tren picker (T-3.6).
 *
 * Nut thu hai **tat** khi hai model la mot: no khong con gi de doi, va mot
 * nut ten la "Doi model" ma gui di dung model cu la mot nut noi doi. Do cung
 * la cho phep so `!==` duy nhat song — khong ai phai nho kiem no o tang goi.
 * Khong co danh sach model nao mo ra o day: cho chon model la picker, va hai
 * danh sach model tren mot man hinh la hai cho de lech (A3 ve tinh than).
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │  KHONG CO O NHAP LY DO (B-244)                                       │
 * └──────────────────────────────────────────────────────────────────────┘
 *
 * §18.2 cho phep mot `reason` kem Dislike va `api.danhGia` mo san duong cho
 * no, nhung hom nay mot ly do gui len thi **khong doc lai duoc o dau**:
 * `MessageRa` co y khong mang `feedback_reason`. Go mot cau roi F5 va thay no
 * bien mat te hon la chua bao gio moi go. Ban T-HD3 cung chi ve hai nut.
 */
export function NutDuoiCauTraLoi({
  chu,
  feedback,
  modelDangDung,
  modelDangChon,
  onDanhGia,
  onThuLai,
  onThuLaiModel,
}: {
  /** Chu se vao clipboard — noi dung cau tra loi, khong kem chip hay nhan. */
  chu: string;
  /** `MessageRa.feedback`, tuc tu server. `null` = chua ai bam gi. */
  feedback: DanhGia | null;
  /** `MessageRa.model_id` — model DA sinh ra cau tra loi nay. */
  modelDangDung: string | null;
  /** Model dang chon tren picker (`modelHieuLuc`). `null` = chua biet. */
  modelDangChon: string | null;
  onDanhGia: (gia: DanhGia | null) => void;
  onThuLai: () => void;
  onThuLaiModel: (modelId: string) => void;
}) {
  const [daChep, setDaChep] = useState(false);

  const khiChep = useCallback(() => {
    void saoChep(chu).then((xong) => {
      if (!xong) {
        return;
      }
      setDaChep(true);
      window.setTimeout(() => setDaChep(false), 1600);
    });
  }, [chu]);

  //: `null` = khong co model nao KHAC de doi sang, tuc nut thu hai phai tat.
  const modelKhac =
    modelDangChon !== null && modelDangChon !== modelDangDung ? modelDangChon : null;

  return (
    <>
      <IconButton
        label={daChep ? t("chat.copied") : t("chat.copy")}
        glyph="⧉"
        onClick={khiChep}
      />
      <IconButton
        label={feedback === "like" ? t("chat.liked") : t("chat.like")}
        glyph="↑"
        pressed={feedback === "like"}
        onClick={() => onDanhGia(feedback === "like" ? null : "like")}
      />
      <IconButton
        label={feedback === "dislike" ? t("chat.disliked") : t("chat.dislike")}
        glyph="↓"
        pressed={feedback === "dislike"}
        onClick={() => onDanhGia(feedback === "dislike" ? null : "dislike")}
      />
      <IconButton label={t("chat.errorRetry")} glyph="↻" onClick={onThuLai} />
      <button
        type="button"
        onClick={() => {
          if (modelKhac !== null) {
            onThuLaiModel(modelKhac);
          }
        }}
        disabled={modelKhac === null}
        title={modelKhac === null ? t("chat.retryOtherModelSame") : t("chat.retryOtherModel")}
        className="h-touch rounded-md px-3 text-base font-medium text-foreground hover:bg-surface-hover disabled:text-disabled-foreground motion-control"
      >
        {t("chat.retryOtherModel")}
      </button>
    </>
  );
}
