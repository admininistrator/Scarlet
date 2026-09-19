import type { ChiPhiRa, HangChiPhi, NguonKhoa, SoTien } from "../../lib/api";
import { t } from "../../lib/i18n";

/**
 * Man "Chi phi" cua §16.3 — **hai cot tach rieng** `metered` / `unmetered`.
 *
 * KH tham chieu: §16.3, §9.5, §10.5, C16 · tasks.md T-2.16, T-2.19, B-178.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHONG CO O NAO CONG HAI COT LAI                                       ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * C16: *"bang chi phi khong khop hoa don provider vi tron chung model metered
 * va unmetered vao mot con so"*. Backend da tu choi tra ve mot truong `tong`
 * (xem `HaiCot` trong `api/v1/admin.py`), va file nay khong duoc dung lai no
 * o tang hien thi: khong mot `Number(a) + Number(b)` nao trong day. Hai cot
 * di canh nhau tu SQL toi man hinh, va nguoi doc tu biet minh dang nhin cai
 * nao.
 *
 * `cost_usd` di tu chuoi sang so DUNG MOT LAN, trong `tien()`, va chi de dinh
 * dang. Doi som hon la lam tron tien ngay tai bien vao cua FE.
 */

/** `Decimal` cua backend la CHUOI — xem `SoTien`. Doi sang so chi de HIEN. */
function tien(gia: string): string {
  return Number(gia).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 6,
  });
}

function OTien({ o }: { o: SoTien }) {
  return (
    <>
      <td className="py-1.5 pr-4 tabular-nums">{tien(o.cost_usd)}</td>
      <td className="py-1.5 pr-4 tabular-nums text-muted">
        {o.prompt_tokens.toLocaleString()} / {o.completion_tokens.toLocaleString()}
      </td>
      <td className="py-1.5 pr-6 tabular-nums text-muted">{o.events.toLocaleString()}</td>
    </>
  );
}

/** Mot truc cua bang chi phi: mot khoa moi hang, hai cot moi hang. */
function BangTruc({ ten, hang }: { ten: string; hang: HangChiPhi[] }) {
  return (
    <div className="mb-6">
      <h4 className="mb-2 text-sm font-semibold">{ten}</h4>
      {hang.length === 0 ? (
        <p className="text-sm text-muted">{t("admin.chuaCoDuLieu")}</p>
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-muted">
              <th className="py-2 pr-4 font-normal" />
              <th className="py-2 pr-6 font-normal" colSpan={3}>
                {t("admin.metered")}
              </th>
              <th className="py-2 font-normal" colSpan={3}>
                {t("admin.unmetered")}
              </th>
            </tr>
            <tr className="border-b border-border text-left text-muted">
              <th className="py-1 pr-4 text-xs font-normal">{t("admin.khoa")}</th>
              <th className="py-1 pr-4 text-xs font-normal">{t("admin.chiPhiUsd")}</th>
              <th className="py-1 pr-4 text-xs font-normal">{t("admin.token")}</th>
              <th className="py-1 pr-6 text-xs font-normal">{t("admin.luot")}</th>
              <th className="py-1 pr-4 text-xs font-normal">{t("admin.chiPhiUsd")}</th>
              <th className="py-1 pr-4 text-xs font-normal">{t("admin.token")}</th>
              <th className="py-1 text-xs font-normal">{t("admin.luot")}</th>
            </tr>
          </thead>
          <tbody>
            {hang.map((h) => (
              <tr key={h.key} className="border-b border-border">
                <td className="py-1.5 pr-4">{h.label ?? h.key}</td>
                <OTien o={h.metered} />
                <OTien o={h.unmetered} />
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const NGUON: (NguonKhoa | null)[] = ["system", "byok", null];

export function BangChiPhi({
  chiPhi,
  nguon,
  onDoiNguon,
}: {
  chiPhi: ChiPhiRa;
  nguon: NguonKhoa | null;
  onDoiNguon: (nguon: NguonKhoa | null) => void;
}) {
  return (
    <section className="px-6 py-4">
      <h3 className="mb-3 text-base font-semibold">{t("admin.chiPhi")}</h3>

      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">{t("admin.nguonTien")}:</span>
        {NGUON.map((n) => (
          <button
            key={n ?? "tat-ca"}
            type="button"
            aria-pressed={nguon === n}
            onClick={() => onDoiNguon(n)}
            className={`rounded-sm border border-border px-2 py-1 ${
              nguon === n ? "bg-accent text-accent-foreground" : "hover:bg-accent hover:text-accent-foreground"
            }`}
          >
            {n === "system"
              ? t("admin.nguonSystem")
              : n === "byok"
                ? t("admin.nguonByok")
                : t("admin.nguonTatCa")}
          </button>
        ))}
        <span className="text-muted">
          {new Date(chiPhi.since).toLocaleDateString()} → {new Date(chiPhi.until).toLocaleDateString()}
        </span>
      </div>

      {/*
        B-178: mac dinh `system` nghia la con so nay LA hoa don cua nguoi van
        hanh, khong phai hoa don do cong them tien BYOK cua nguoi khac (§10.5).
        Nhan noi ro dang loc gi, vi mot tong khong nhan doc y het mot tong
        khong loc.
      */}
      <div className="mb-6">
        <h4 className="mb-2 text-sm font-semibold">
          {t("admin.tong")}{" "}
          <span className="font-normal text-muted">
            (
            {chiPhi.key_source === null
              ? t("admin.nguonTatCa")
              : chiPhi.key_source === "system"
                ? t("admin.nguonSystem")
                : t("admin.nguonByok")}
            )
          </span>
        </h4>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-muted">
              <th className="py-1 pr-4 text-xs font-normal">{t("admin.cot")}</th>
              <th className="py-1 pr-4 text-xs font-normal">{t("admin.chiPhiUsd")}</th>
              <th className="py-1 pr-4 text-xs font-normal">{t("admin.token")}</th>
              <th className="py-1 text-xs font-normal">{t("admin.luot")}</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-border">
              <td className="py-1.5 pr-4">{t("admin.metered")}</td>
              <OTien o={chiPhi.totals.metered} />
            </tr>
            <tr className="border-b border-border">
              <td className="py-1.5 pr-4">{t("admin.unmetered")}</td>
              <OTien o={chiPhi.totals.unmetered} />
            </tr>
          </tbody>
        </table>
      </div>

      <BangTruc ten={t("admin.theoNgay")} hang={chiPhi.by_day} />
      <BangTruc ten={t("admin.theoUser")} hang={chiPhi.by_user} />
      <BangTruc ten={t("admin.theoModel")} hang={chiPhi.by_model} />

      {/*
        Truc thu tu KHONG bi `key_source` loc, ke ca khi ba bang tren da bi loc
        — xem `admin_usage`. No o day de mot mac dinh loc khong tro thanh mot
        kieu noi doi moi: nhin vao day la biet phan vua bi cat ra to bao nhieu.
      */}
      <BangTruc ten={t("admin.theoNguon")} hang={chiPhi.by_key_source} />
    </section>
  );
}
