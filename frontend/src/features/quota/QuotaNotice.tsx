import { Clock, Gauge } from "lucide";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { PATHS } from "../../app/paths";
import { StaticIcon } from "../../components/ui/Icon";
import { t } from "../../lib/i18n";
import { Moment } from "./Moment";
import {
  WINDOW_LABEL,
  warningReading,
  windowNames,
  type QuotaBlock,
  type QuotaReading,
} from "./quotaView";

/**
 * Dong han muc MOT HANG tren o nhap — T-S.10, NQ-114, ban T-HD2-v2 muc G4/G5.
 *
 * KH tham chieu: UC-07 dong 1–2, §24.2b·S9 · tasks.md T-3.11, T-S.10.
 *
 * Hai thanh quota cua T-3.11 roi man chat (sang Cai dat › Muc su dung o
 * T-S.11). O day chi con mot hang cao 44 px, va chi khi co chuyen de noi:
 *
 *   - con ≤ `quota_warn_remaining_pct` ⇒ "Han muc 5 gio con 14%" (UC-07 dong
 *     1, KHONG chan);
 *   - het ⇒ "Da het han muc … · Hoan lai luc …" voi moc CHINH XAC toi giay
 *     (UC-07 dong 2) — nut Gui bi khoa o `Composer`;
 *   - het nhung model dang chon di bang khoa rieng ⇒ noi ro van gui duoc
 *     (Cam bay ③ cua T-S.10 = Cam bay ① cua T-3.11).
 *
 * Moi luat "het / sap het / BYOK" doc tu `quotaView.ts` — CUNG `QuotaBlock` va
 * `byokCovers` ma nut Gui doc, nen dong chu va nut khong the noi hai chuyen.
 * Moi hang co link sang Muc su dung, va do la vung cham nen hang cao 44 px.
 */
export function QuotaNotice({
  readings,
  warnPct,
  block,
  byokCovered,
  now = Date.now(),
}: {
  readings: QuotaReading[];
  /** `quota_warn_remaining_pct` cua `/auth/me`; `null` ⇒ khong ve gi. */
  warnPct: number | null;
  block: QuotaBlock | null;
  /** Model dang chon di bang khoa BYOK — het quota van gui duoc. */
  byokCovered: boolean;
  /** Tiem duoc de test on dinh; mac dinh la luc render. */
  now?: number;
}) {
  // `quota: null` = chua do duoc (Redis chop) — khong noi gi.
  if (readings.length === 0 || warnPct === null) {
    return null;
  }

  if (block !== null) {
    const tone = byokCovered ? "text-muted" : "text-danger-text";
    return (
      <Row icon={<StaticIcon icon={Clock} size={16} className={`shrink-0 ${tone}`} />} tone={tone}>
        {t("quota.notice.exhausted")} {windowNames(block.windows)} ·{" "}
        {byokCovered ? (
          t("quota.notice.byok")
        ) : block.resetAt === null ? (
          t("quota.notice.resetUnknown")
        ) : (
          <>
            {t("quota.notice.resetAt")} <Moment ms={block.resetAt} now={now} className="font-semibold" />
          </>
        )}
      </Row>
    );
  }

  const warning = warningReading(readings, warnPct);
  if (warning === null) {
    return null;
  }
  return (
    <Row
      icon={<StaticIcon icon={Gauge} size={16} className="shrink-0 text-warning" />}
      tone="text-warning-text"
    >
      {t("quota.notice.window")} {t(WINDOW_LABEL[warning.window.limit_type])} {t("quota.remaining")}{" "}
      <strong className="tabular font-semibold">{warning.window.remaining_pct}%</strong>
    </Row>
  );
}

function Row({ icon, tone, children }: { icon: ReactNode; tone: string; children: ReactNode }) {
  return (
    <div role="status" className="flex min-h-touch items-center gap-2 pl-1 text-sm">
      {icon}
      <span className={`min-w-0 truncate ${tone}`}>{children}</span>
      <Link
        to={PATHS.settingsUsage}
        className="ml-auto inline-flex min-h-touch shrink-0 items-center px-2 font-medium whitespace-nowrap"
      >
        {t("quota.viewUsage")}
      </Link>
    </div>
  );
}
