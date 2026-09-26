/**
 * Khoi ④ "Gia" cua Model Picker v2 — T-S.14, ban T-HD4-v2 muc B, E, F.
 *
 * KH tham chieu: §24.2b·S3c, S11 (khoi 4) · NQ-120 · tasks.md T-S.14 Cam bay ①.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  GIA LA CHUOI · KHUNG GIO DO BACKEND CHON                              ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `input_per_1m`/`output_per_1m` la chuoi dung chu so cua catalog; doi sang so
 * DUNG MOT LAN, trong `formatUsd`, de hien (T-3.11 ③). File nay khong so, cong
 * hay chon con so nao.
 *
 * "Dang ap dung" la `pricing.current` — khung backend da chon theo mui gio
 * cua catalog (S3c). FE khong doc dong ho de doan cao/thap diem: mot may lech
 * mui gio se hien sai khung ma khong ai thay.
 *
 * ── Bo cuc hai dong (ban B: "Ngoai khung, chip chuyen xuong dong thap diem")
 *
 * Dong chinh luon la gia NIEM YET (khung `peak`, hoac gia duy nhat); dong duoi
 * la "Gio thap diem: …". Chip "Dang ap dung · …" di theo khung backend tra
 * trong `current` — dung tren dong chinh o gio cao diem, xuong dong duoi o gio
 * thap diem. Hai dong khong doi cho cho nhau theo gio.
 */

import type { ReactNode } from "react";

import type { ModelOut, ModelPricing, PriceRates } from "../../lib/api";
import { t } from "../../lib/i18n";
import { formatUsd } from "../quota/quotaView";
import { SectionLabel } from "./chips";

function ActiveChip({ rates }: { rates: PriceRates }) {
  if (rates.window === null) {
    return null;
  }
  return (
    <span className="rounded-full border border-border-strong px-2 py-px text-2xs font-semibold whitespace-nowrap">
      {t(rates.window === "peak" ? "model.priceActivePeak" : "model.priceActiveOffPeak")}
    </span>
  );
}

/** Mot dong gia + (neu la khung dang ap dung) chip — canh nhau o desktop, chip xuong dong o 375 px. */
function PriceLine({
  active,
  narrow,
  rates,
  children,
}: {
  active: boolean;
  narrow: boolean;
  rates: PriceRates;
  children: ReactNode;
}) {
  return (
    <div
      className={
        narrow ? "flex flex-col items-start gap-1.5" : "flex flex-wrap items-center gap-x-2.5 gap-y-1.5"
      }
    >
      {children}
      {active ? <ActiveChip rates={rates} /> : null}
    </div>
  );
}

function PriceLines({ pricing, narrow }: { pricing: ModelPricing; narrow: boolean }) {
  const all = pricing.other === null ? [pricing.current] : [pricing.current, pricing.other];
  const listed = all.find((r) => r.window !== "off_peak") ?? pricing.current;
  const offPeak = all.find((r) => r !== listed && r.window === "off_peak") ?? null;

  return (
    <>
      <PriceLine active={pricing.current === listed} narrow={narrow} rates={listed}>
        <span className="tabular text-base">
          <span className="text-muted">{t("model.priceInput")}</span>{" "}
          <strong className="font-semibold">{formatUsd(listed.input_per_1m)}</strong>{" "}
          <span className="text-muted">·</span> <span className="text-muted">{t("model.priceOutput")}</span>{" "}
          <strong className="font-semibold">{formatUsd(listed.output_per_1m)}</strong>{" "}
          <span className="text-muted">{t("model.pricePerUnit")}</span>
          {pricing.estimated ? <span className="text-muted"> · {t("model.priceEstimate")}</span> : null}
        </span>
      </PriceLine>
      {offPeak !== null ? (
        <PriceLine active={pricing.current === offPeak} narrow={narrow} rates={offPeak}>
          <span className="tabular text-sm text-muted">
            {t("model.priceOffPeakPrefix")} {t("model.priceInput")} {formatUsd(offPeak.input_per_1m)} ·{" "}
            {t("model.priceOutput")} {formatUsd(offPeak.output_per_1m)}
          </span>
        </PriceLine>
      ) : null}
    </>
  );
}

export function PriceBlock({ model, narrow }: { model: ModelOut; narrow: boolean }) {
  return (
    <div
      className={`flex flex-col gap-1.5 border-t border-divider ${narrow ? "px-4 pt-3 pb-4" : "p-3"}`}
    >
      <SectionLabel>{t("model.priceLabel")}</SectionLabel>
      {model.pricing === null ? (
        /*
          Ban F: model khong tinh phi theo token (Ollama, duong trung gian
          `unmetered`). Dong "suy luan tinh nhu token ra" chi co nghia khi co
          token de tinh — o day khong hien.
        */
        <span className="text-base">{t("model.priceUnmetered")}</span>
      ) : (
        <>
          <PriceLines pricing={model.pricing} narrow={narrow} />
          <span className="text-xs text-muted">{t("model.priceReasoningNote")}</span>
        </>
      )}
    </div>
  );
}
