import { useCallback, useId, useState, type ReactNode } from "react";

import { useResource } from "../../features/admin/useResource";
import { endpointModelName } from "../../features/models/byokModels";
import { api, type AdminModelOut, type CostRow, type KeySource, type MeteredSplit } from "../../lib/api";
import { t, type TextKey } from "../../lib/i18n";
import { TableScroll } from "../ui/TableScroll";
import { CountCell, ErrorNotice, LoadingNote, MoneyCell, ScreenTitle, TD, TH, TH_NUMBER } from "./adminUi";
import { formatCount, formatDayKey, padMoney } from "./format";

/**
 * Man 1c "Chi phi" — §16.3, §9.5, C16, ban T-HD7 · T-2.19 → T-3.12.
 *
 * KH tham chieu: §16.3, §9.5, §10.5, C16 · tasks.md T-2.16, T-2.19, B-175,
 * B-178.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHONG CO O NAO CONG HAI COT TIEN LAI                                  ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * C16 + ban T-HD7: *"Hai o tren cung la truong server tinh. Server khong gui
 * thi o bien mat; giao dien khong bao gio tu cong. Bang khong co hang Tong."*
 * `totals` cua `GET /admin/usage` la tong do server cong trong TUNG cot (xem
 * `_tong` cua backend). Mot `Number(a) + Number(b)` tren tien khong co trong
 * file nay; `parseFloat` duy nhat la de tinh CHIEU CAO cot bieu do.
 *
 * Hai cot SO NGUYEN duoc cong o day — "Luot goi" va "Token vao/ra" — va do la
 * co y: docstring `MeteredSplit` cua backend noi *"muon cong thi tang hien thi tu
 * cong, va khi ay nguoi viet ra phep cong biet minh dang cong cai gi"*. Dem so
 * lan goi / so token khong lam tron tien cua ai.
 *
 * ── Nguon tien (B-178) ─────────────────────────────────────────────────────
 *
 * Ban T-HD7 chi ve o doi 7/30 ngay. Bo loc "nguon tien" cua T-2.19 VAN O LAI
 * (mac dinh `system`), cung bang "theo nguon tien" KHONG bi loc: bo di thi con
 * so lon nhat tren man hinh hoac cong nham tien BYOK cua nguoi khac, hoac lang
 * le cat no ra ma khong de lai dau vet — dung hai kieu noi doi B-178 da dong.
 * Hai manh ay dung LAI khuon cua ban ve (o doi dang radio, bang cuon).
 *
 * ── Khoan "Dat ten hoi thoai" (T-S.17, ban T-HD7-v2 muc 1d) ─────────────────
 *
 * Ban v2 tach luot dat ten KHOI hai cot: the/cot/bieu do Metered–Unmetered doc
 * `by_purpose.chat` (backend van tra `metered`/`unmetered` = tong moi viec, nen
 * doc phan `chat` la DOC mot truong khac, khong tru gi). Con so "Dat ten" la
 * `title_cost_usd` — server cong hai cot cua `by_purpose.title` (Cam bay ①
 * T-S.17). Luot dat ten luon tra bang khoa he thong (§24.2b·S6), nen o nguon
 * "Khoa rieng" the ghi "Khong co trong nguon nay" va o cua hang BYOK la "—":
 * o trong co nghia, khong phai so 0.
 *
 * ── Nguon "Khoa rieng" chi dem token (T-S.19c, ban T-HD10 4c/4d, NQ-134 ③) ──
 *
 * Luot BYOK ghi `cost_usd = 0` tu T-S.19b, nen o bo loc ay hai the tien thanh
 * Token vao / Token ra, bang Theo model va Theo nguoi dung bo moi cot tien.
 * Duoi ten model co dong DUONG DI: model catalog ⇒ "Hang · Goi thang" (ten +
 * hang tu `GET /admin/models`), endpoint tu nhap ⇒ "Endpoint tuy chinh · host"
 * (`label` cua server, NQ-137 ②). Bang Theo nguon (khong loc) them Token
 * vao / ra cho ca hai hang, o tien cua hang BYOK la "—".
 */

/** Tong token cua mot hang — cong SO NGUYEN, xem khoi dau file. */
function tokensOf(row: MeteredSplit) {
  return {
    tokensIn: row.metered.prompt_tokens + row.unmetered.prompt_tokens,
    tokensOut: row.metered.completion_tokens + row.unmetered.completion_tokens,
  };
}

const RANGES = [7, 30] as const;
type Range = (typeof RANGES)[number];
const RANGE_LABEL: Record<Range, TextKey> = { 7: "admin.cost.range7", 30: "admin.cost.range30" };
const DAY_MS = 86_400_000;

type Source = KeySource | null;
// Thu tu cua ban v2; mac dinh van la `system` (B-178).
const SOURCES: Source[] = [null, "system", "byok"];
function sourceLabel(source: Source): TextKey {
  return source === "system"
    ? "admin.cost.source.system"
    : source === "byok"
      ? "admin.cost.source.byok"
      : "admin.cost.source.all";
}

function Segmented<T>({
  label,
  options,
  value,
  onChange,
  optionLabel,
  even = false,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  optionLabel: (v: T) => string;
  /** Ban v2 muc 1h: duoi `sm` la luoi o DEU nhau, nhan dai xuong dong TRONG o. */
  even?: boolean;
}) {
  const frame = even
    ? "grid grid-cols-3 rounded-md border border-border-strong p-0.5 sm:flex"
    : "flex self-start rounded-md border border-border-strong p-0.5";
  const cell = even ? "px-1.5 leading-4 sm:px-3.5 sm:leading-normal" : "px-3 sm:px-4";
  return (
    <div role="radiogroup" aria-label={label} className={frame}>
      {options.map((o) => (
        <button
          key={String(o)}
          type="button"
          role="radio"
          aria-checked={value === o}
          onClick={() => onChange(o)}
          className={
            value === o
              ? `motion-press min-h-touch rounded-sm bg-foreground text-sm font-semibold text-background ${cell}`
              : `motion-press min-h-touch rounded-sm text-sm text-foreground hover:bg-surface-hover ${cell}`
          }
        >
          {optionLabel(o)}
        </button>
      ))}
    </div>
  );
}

export function CostScreen() {
  const [range, setRange] = useState<Range>(7);
  const [source, setSource] = useState<Source>("system");

  const load = useCallback(
    () => api.adminCosts(source, new Date(Date.now() - range * DAY_MS).toISOString()),
    [range, source],
  );
  const report = useResource(load);
  // Ten + hang cua model catalog cho dong duong di (chi nguon Khoa rieng). Hong ⇒ ten = id.
  const adminModels = useResource(api.adminModels);
  const byok = source === "byok";
  const catalogModel = (id: string): AdminModelOut | undefined =>
    adminModels.data?.models.find((m) => m.id === id);
  const totals = report.data === null ? null : tokensOf(report.data.totals);

  return (
    <>
      <ScreenTitle>{t("admin.cost.title")}</ScreenTitle>
      <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-3">
        <Segmented
          label={t("admin.cost.rangeLabel")}
          options={RANGES}
          value={range}
          onChange={setRange}
          optionLabel={(r) => t(RANGE_LABEL[r])}
        />
        <div className="flex w-full flex-col gap-1.5 sm:w-auto sm:flex-row sm:items-center sm:gap-2.5">
          <span aria-hidden="true" className="text-sm text-muted">
            {t("admin.cost.sourceLabel")}
          </span>
          <Segmented
            label={t("admin.cost.sourceLabel")}
            options={SOURCES}
            value={source}
            onChange={setSource}
            optionLabel={(s) => t(sourceLabel(s))}
            even
          />
        </div>
      </div>

      {report.error && (
        <ErrorNotice title={t("admin.loadError")} error={report.error} onRetry={() => void report.reload()} />
      )}
      {report.data === null ? (
        report.loading && <LoadingNote />
      ) : (
        <>
          <dl className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-3 sm:gap-3">
            {byok && totals !== null ? (
              <>
                <TotalCard label={t("admin.cost.tokensInTotal")} value={formatCount(totals.tokensIn)} />
                <TotalCard label={t("admin.cost.tokensOutTotal")} value={formatCount(totals.tokensOut)} />
              </>
            ) : (
              <>
                <TotalCard
                  label={t("admin.cost.serverTotalMetered")}
                  value={padMoney(report.data.totals.by_purpose.chat.metered.cost_usd)}
                />
                <TotalCard
                  label={t("admin.cost.serverTotalUnmetered")}
                  value={padMoney(report.data.totals.by_purpose.chat.unmetered.cost_usd)}
                />
              </>
            )}
            <TotalCard
              label={t("admin.cost.titleTotal")}
              labelWide={t("admin.cost.titleTotalWide")}
              value={source === "byok" ? null : padMoney(report.data.totals.title_cost_usd)}
              note={t("admin.cost.titleNote")}
            />
          </dl>

          <CostChart days={report.data.by_day} />

          <h3 className="text-xl font-semibold text-foreground">{t("admin.cost.byKeySource")}</h3>
          <AxisTable
            caption={t("admin.cost.byKeySource")}
            firstColumn={t("admin.col.keySource")}
            rows={report.data.by_key_source}
            rowLabel={(r) =>
              r.key === "system" || r.key === "byok" ? t(sourceLabel(r.key)) : r.key
            }
            rowDetail={(r) =>
              r.key === "system"
                ? t("admin.cost.sourceDetail.system")
                : r.key === "byok"
                  ? t("admin.cost.sourceDetail.byok")
                  : null
            }
            // T-S.19c: luot BYOK chi dem token — o tien cua hang ay la "—".
            moneyMissing={(r) => r.key === "byok"}
            columns="all"
          />

          <h3 className="text-xl font-semibold text-foreground">{t("admin.cost.byUser")}</h3>
          <AxisTable
            caption={t("admin.cost.byUser")}
            firstColumn={t("admin.col.user")}
            rows={report.data.by_user}
            rowLabel={(r) => r.label ?? r.key}
            columns={byok ? "tokens" : "money"}
          />

          <h3 className="text-xl font-semibold text-foreground">{t("admin.cost.byModel")}</h3>
          <AxisTable
            caption={t("admin.cost.byModel")}
            firstColumn={t("admin.col.model")}
            rows={report.data.by_model}
            rowLabel={(r) => {
              if (!byok) {
                return r.key;
              }
              const own = endpointModelName(r.key);
              return own === null ? (catalogModel(r.key)?.display_name ?? r.key) : <span className="font-mono">{own}</span>;
            }}
            rowDetail={byok ? (r) => <RouteLine row={r} model={catalogModel(r.key)} /> : undefined}
            columns={byok ? "tokens" : "money-tokens"}
          />
        </>
      )}
    </>
  );
}

/**
 * Dong duong di duoi ten model, CHI o man quan tri (ban T-HD10 4c, `ByokRouteLine`).
 * Endpoint tu nhap ⇒ "Endpoint tuy chinh · host" (endpoint da xoa ⇒ khong host);
 * model catalog dung khoa rieng ⇒ "Hang · Goi thang".
 */
function RouteLine({ row, model }: { row: CostRow; model: AdminModelOut | undefined }) {
  if (endpointModelName(row.key) !== null) {
    return (
      <span className="flex flex-wrap gap-x-1.5">
        <span>{t("admin.models.kind.custom")}</span>
        {row.label !== null && (
          <>
            <span aria-hidden>·</span>
            <span className="wrap-anywhere">{row.label}</span>
          </>
        )}
      </span>
    );
  }
  if (model === undefined) {
    return null;
  }
  return (
    <span className="flex flex-wrap gap-x-1.5">
      <span>{model.provider}</span>
      <span aria-hidden>·</span>
      <span>{t("admin.models.kind.direct")}</span>
    </span>
  );
}

/**
 * Mot the tong (ban v2 muc 1d/1h). Duoi `sm` nhan va so nam tren MOT hang
 * (luoi hai cot), dong giai thich trai ca hang ben duoi; tu `sm` xep doc.
 * `value === null` = so khong ap cho bo loc dang chon — hien cau thay vi so 0.
 */
function TotalCard({
  label,
  labelWide,
  value,
  note,
}: {
  label: string;
  labelWide?: string;
  value: string | null;
  note?: string;
}) {
  return (
    <div className="grid min-w-0 grid-cols-[1fr_auto] items-baseline gap-x-2 gap-y-1 rounded-lg border border-border bg-surface-panel px-3.5 py-3 sm:grid-cols-1 sm:p-4">
      <dt className="text-sm text-muted">
        {labelWide === undefined ? (
          label
        ) : (
          <>
            <span className="sm:hidden">{label}</span>
            <span className="hidden sm:inline">{labelWide}</span>
          </>
        )}
      </dt>
      {value === null ? (
        <dd className="text-base text-muted">{t("admin.cost.titleNotInSource")}</dd>
      ) : (
        <dd className="money text-left text-xl font-semibold text-foreground sm:text-2xl">{value}</dd>
      )}
      {note !== undefined && <dd className="col-span-2 text-xs text-muted sm:col-span-1">{note}</dd>}
    </div>
  );
}

/**
 * Cot cua mot bang. `money` = ba cot tien + luot goi; `money-tokens` = ba cot
 * tien + token vao/ra (bang theo model); `tokens` = chi token vao/ra (nguon
 * Khoa rieng, ban T-HD10 4c); `all` = ba cot tien + luot goi + token (bang Theo
 * nguon, T-S.19c).
 */
type Columns = "money" | "money-tokens" | "tokens" | "all";

/**
 * Mot truc cua bao cao: cot dau dinh, metered va unmetered luon la HAI cot
 * rieng, cung thu tu o moi bang va cung thu tu voi chu giai bieu do. Hai cot
 * ay la phan `chat`; cot "Dat ten" dung sau chung, truoc luot goi (ban v2).
 * Luot goi / token dem MOI viec — dat ten cung la mot lan goi model.
 */
function AxisTable({
  caption,
  firstColumn,
  rows,
  rowLabel,
  rowDetail,
  moneyMissing,
  columns,
}: {
  caption: string;
  firstColumn: string;
  rows: CostRow[];
  rowLabel: (row: CostRow) => ReactNode;
  rowDetail?: (row: CostRow) => ReactNode;
  /** Hang ma tien khong ap (nguon BYOK chi dem token) — "—", khong phai 0. */
  moneyMissing?: (row: CostRow) => boolean;
  columns: Columns;
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted">{t("admin.empty")}</p>;
  }
  const money = columns !== "tokens";
  const requests = columns === "money" || columns === "all";
  const tokens = columns !== "money";
  const missing = <td className={`${TD} money text-muted`}>—</td>;
  return (
    <TableScroll label={caption}>
      <thead>
        <tr>
          <th scope="col" className={`${TH} sticky-col w-sticky-col`}>
            {firstColumn}
          </th>
          {money && (
            <>
              <th scope="col" className={TH_NUMBER}>
                {t("admin.col.metered")}
              </th>
              <th scope="col" className={TH_NUMBER}>
                {t("admin.col.unmetered")}
              </th>
              <th scope="col" className={TH_NUMBER}>
                {t("admin.col.titling")}
              </th>
            </>
          )}
          {requests && (
            <th scope="col" className={TH_NUMBER}>
              {t("admin.col.requests")}
            </th>
          )}
          {tokens && (
            <>
              <th scope="col" className={TH_NUMBER}>
                {t("admin.col.tokensIn")}
              </th>
              <th scope="col" className={TH_NUMBER}>
                {t("admin.col.tokensOut")}
              </th>
            </>
          )}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const detail = rowDetail?.(r) ?? null;
          const noMoney = moneyMissing?.(r) ?? false;
          const { tokensIn, tokensOut } = tokensOf(r);
          return (
            <tr key={r.key}>
              <th
                scope="row"
                className={`${TD} sticky-col w-sticky-col max-w-sticky-col text-left font-semibold ${detail === null ? "truncate" : ""}`}
              >
                {detail === null ? (
                  rowLabel(r)
                ) : (
                  <>
                    <span className="block truncate">{rowLabel(r)}</span>
                    <span className="block text-xs font-normal text-muted">{detail}</span>
                  </>
                )}
              </th>
              {money &&
                (noMoney ? (
                  <>
                    {missing}
                    {missing}
                    {missing}
                  </>
                ) : (
                  <>
                    <MoneyCell value={r.by_purpose.chat.metered.cost_usd} />
                    <MoneyCell value={r.by_purpose.chat.unmetered.cost_usd} />
                    <MoneyCell value={r.title_cost_usd} />
                  </>
                ))}
              {requests && <CountCell value={r.metered.events + r.unmetered.events} />}
              {tokens && (
                <>
                  <CountCell value={tokensIn} />
                  <CountCell value={tokensOut} />
                </>
              )}
            </tr>
          );
        })}
      </tbody>
    </TableScroll>
  );
}

/**
 * Cot canh nhau: metered (dac, `chart-1`) va unmetered (`chart-2` + vach cheo
 * — doc duoc khi in trang den, ban T-HD7 muc 1i). `parseFloat` CHI de tinh
 * chieu cao — khong hien, khong cong. Nhan "Cao nhat" la CHUOI GOC cua ngay
 * lon nhat, khong phai so tu sinh. Truc khong co vach so.
 *
 * T-S.17 (§24.2b·S6): van DUNG hai chuoi, va la phan `chat` — luot dat ten
 * khong ve len bieu do (he thiet ke chi co hai mau bieu do).
 */
export function CostChart({ days }: { days: CostRow[] }) {
  const patternId = useId();
  const values = days.flatMap((d) => [d.by_purpose.chat.metered.cost_usd, d.by_purpose.chat.unmetered.cost_usd]);
  const maxString = values.reduce((a, b) => (parseFloat(b) > parseFloat(a) ? b : a), values[0] ?? "0");
  const max = parseFloat(maxString) || 1;
  const w = 100 / Math.max(days.length, 1);
  return (
    <figure className="print-exact flex min-w-0 flex-col gap-3 rounded-lg border border-border bg-surface-panel p-4">
      <figcaption className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-lg font-semibold text-foreground">{t("admin.cost.chartTitle")}</span>
        <span className="flex flex-wrap gap-4 text-sm text-foreground">
          <span className="flex items-center gap-1.5">
            <svg width="14" height="14" aria-hidden="true">
              <rect width="14" height="14" className="fill-chart-1" />
            </svg>
            {t("admin.metered")}
          </span>
          <span className="flex items-center gap-1.5">
            <svg width="14" height="14" aria-hidden="true">
              <rect width="14" height="14" className="fill-chart-2" />
              <rect width="14" height="14" fill={`url(#${patternId})`} />
            </svg>
            {t("admin.unmetered")}
          </span>
        </span>
      </figcaption>
      {days.length === 0 ? (
        <p className="text-sm text-muted">{t("admin.empty")}</p>
      ) : (
        <>
          <p className="text-xs text-muted">
            {t("admin.cost.chartMaxPrefix")} <span className="tabular text-foreground">{padMoney(maxString)}</span>
          </p>
          <svg
            viewBox="0 0 100 60"
            preserveAspectRatio="none"
            role="img"
            aria-label={t("admin.cost.chartTitle")}
            className="h-chart w-full"
          >
            <defs>
              <pattern
                id={patternId}
                width="3"
                height="3"
                patternUnits="userSpaceOnUse"
                patternTransform="rotate(45)"
              >
                <rect width="1" height="3" className="fill-chart-pattern" />
              </pattern>
            </defs>
            {[0, 15, 30, 45].map((y) => (
              <line
                key={y}
                x1="0"
                x2="100"
                y1={y}
                y2={y}
                vectorEffect="non-scaling-stroke"
                className="stroke-chart-grid"
              />
            ))}
            <line
              x1="0"
              x2="100"
              y1="60"
              y2="60"
              vectorEffect="non-scaling-stroke"
              className="stroke-border-strong"
            />
            {days.map((d, i) => {
              const hm = (parseFloat(d.by_purpose.chat.metered.cost_usd) / max) * 58;
              const hu = (parseFloat(d.by_purpose.chat.unmetered.cost_usd) / max) * 58;
              const x = i * w + w * 0.18;
              const bw = w * 0.3;
              return (
                <g key={d.key}>
                  <rect x={x} y={60 - hm} width={bw} height={hm} className="fill-chart-1" />
                  <rect x={x + bw + w * 0.04} y={60 - hu} width={bw} height={hu} className="fill-chart-2" />
                  <rect
                    x={x + bw + w * 0.04}
                    y={60 - hu}
                    width={bw}
                    height={hu}
                    fill={`url(#${patternId})`}
                  />
                </g>
              );
            })}
          </svg>
          <ol
            className="grid text-center text-2xs text-muted"
            style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }}
          >
            {days.map((d) => (
              <li key={d.key} className="tabular">
                {formatDayKey(d.key)}
              </li>
            ))}
          </ol>
          <details className="text-sm">
            <summary className="inline-flex min-h-touch cursor-pointer items-center text-accent-text underline underline-offset-2">
              {t("admin.cost.showTable")}
            </summary>
            <AxisTable
              caption={t("admin.cost.chartTitle")}
              firstColumn={t("admin.col.day")}
              rows={days}
              rowLabel={(r) => formatDayKey(r.key)}
              columns="money"
            />
          </details>
        </>
      )}
    </figure>
  );
}
