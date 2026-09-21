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

/**
 * Mot bong bong tren duong di hien tai — §8.2, §7.4, C13.
 *
 * Giao dien o day CO Y tho: T-HD1…T-HD5 (Phase 3) moi la luc thiet ke, va lam
 * dep bay gio la lam hai lan. Thu duy nhat khong duoc tho la **so nhanh**:
 * `‹ n/m ›` doc thang tu `sibling_index`/`sibling_count` cua server qua
 * `chiSoHienThi()`, khong co mot phep dem nao o day (C13).
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
  const [dangSua, setDangSua] = useState(false);
  const [ban, setBan] = useState("");

  const chu = noiDung(cay, node);
  const reasoning = phanReasoning(cay, node);
  const laUser = node.role === "user";

  return (
    <article className="border-b border-border px-6 py-4">
      <header className="flex flex-wrap items-center gap-3 text-xs text-muted">
        <span className="uppercase">{node.role}</span>
        <span>{node.status}</span>
        {node.model_id !== null && <span>{node.model_id}</span>}
        {node.finish_reason !== null && <span>finish={node.finish_reason}</span>}
        {node.error_code !== null && <span className="text-danger-emphasis">{node.error_code}</span>}

        {coAnhEm(node) && (
          <span className="flex items-center gap-1">
            <button
              type="button"
              aria-label={t("chat.nhanhTruoc")}
              disabled={!coTheLui(node)}
              onClick={() => onChuyenNhanh(node, -1)}
              className="rounded-sm border border-border px-1 disabled:opacity-40"
            >
              ‹
            </button>
            {/* chiSoHienThi() la cho duy nhat doi 0-based sang so nguoi doc (B-60) */}
            <span>
              {chiSoHienThi(node)}/{node.sibling_count}
            </span>
            <button
              type="button"
              aria-label={t("chat.nhanhSau")}
              disabled={!coTheToi(node)}
              onClick={() => onChuyenNhanh(node, 1)}
              className="rounded-sm border border-border px-1 disabled:opacity-40"
            >
              ›
            </button>
          </span>
        )}
      </header>

      {reasoning !== "" && (
        <details className="mt-2 text-sm text-muted">
          <summary>{t("chat.reasoning")}</summary>
          <pre className="whitespace-pre-wrap">{reasoning}</pre>
        </details>
      )}

      {ghiChu.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2 text-xs text-muted">
          {ghiChu.map((chip, i) => (
            <li key={i} className="rounded-sm border border-border px-1">
              {chip}
            </li>
          ))}
        </ul>
      )}

      {dangSua ? (
        <form
          className="mt-2 flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (ban.trim() !== "") {
              onSua(node.id, ban);
              setDangSua(false);
            }
          }}
        >
          <textarea
            value={ban}
            onChange={(e) => setBan(e.target.value)}
            rows={3}
            className="w-full rounded-sm border border-border bg-background p-2 text-foreground"
          />
          <div className="flex gap-2 text-sm">
            <button
              type="submit"
              className="rounded-sm border border-border px-2 py-1 hover:bg-accent hover:text-accent-foreground"
            >
              {t("chat.luu")}
            </button>
            <button
              type="button"
              onClick={() => setDangSua(false)}
              className="rounded-sm border border-border px-2 py-1"
            >
              {t("chat.thoi")}
            </button>
          </div>
        </form>
      ) : (
        <p className="mt-2 whitespace-pre-wrap text-foreground">
          {/* §7.4: im lang = DANG CHO, khong phai da xong. Con tro cho o day
              noi ra dieu do thay vi de mot bong bong rong. */}
          {chu === "" && dangChay ? <span className="text-muted">{t("chat.dangCho")}</span> : chu}
        </p>
      )}

      <footer className="mt-2 flex gap-2 text-xs">
        {laUser && !dangSua && (
          <button
            type="button"
            onClick={() => {
              setBan(chu);
              setDangSua(true);
            }}
            className="rounded-sm border border-border px-2 py-1 text-foreground"
          >
            {t("chat.sua")}
          </button>
        )}
        {!laUser && (
          <button
            type="button"
            onClick={() => onThuLai(node.id)}
            className="rounded-sm border border-border px-2 py-1 text-foreground"
          >
            {t("chat.thuLai")}
          </button>
        )}
      </footer>
    </article>
  );
}
