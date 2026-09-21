import { t } from "../../lib/i18n";
import type { TrangThaiKetNoi } from "../../lib/sse";
import { useChat } from "../../features/chat/useChat";
import { Composer } from "./Composer";
import { MessageItem } from "./MessageItem";

const NHAN_KET_NOI = {
  "dang-mo": "chat.ketNoi.dangMo",
  "dang-chay": "chat.ketNoi.dangChay",
  "dang-noi-lai": "chat.ketNoi.dangNoiLai",
  dong: "chat.ketNoi.dong",
} as const;

function NhanKetNoi({ ketNoi }: { ketNoi: TrangThaiKetNoi | null }) {
  if (ketNoi === null) {
    return null;
  }
  return <span className="text-xs text-muted">{t(NHAN_KET_NOI[ketNoi])}</span>;
}

/**
 * Man chat THO cua T-1.14 — o nhap, danh sach message, nut Dung, `‹ n/m ›`.
 *
 * Man hinh that la Phase 3 (T-3.x) va do Claude Design ve; o day chi co du thu
 * de chung minh bon dong DoD chay duoc tren trinh duyet that, trong do co M3.
 *
 * T-3.1c go o nhap `user_id` tam cua Phase 1 khoi dau man hinh nay: tu day
 * nguoi vao duoc day deu da di qua `StatusGate`, tuc da co mot phien that.
 * Xem B-186 — hai o danh tinh tren cung mot trang, ma o hien ro hon lai la o
 * khong con tac dung.
 *
 * Danh sach render `cay.path` chu khong phai "moi message" (A2): duong di do
 * server dung bang recursive CTE, va cac nhanh khac nam yen trong Postgres cho
 * toi khi nguoi dung bam `‹ n/m ›`.
 */
export function ChatScreen() {
  const chat = useChat();
  const { cay } = chat;

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-6 py-3 text-sm">
        <button
          type="button"
          onClick={() => void chat.hoiThoaiMoi()}
          disabled={chat.dangBan}
          className="rounded-md border border-border px-3 py-1.5 hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
        >
          {t("chat.hoiThoaiMoi")}
        </button>

        <label className="flex items-center gap-2">
          <span className="text-muted">{t("chat.model")}</span>
          <select
            value={chat.modelChon ?? ""}
            onChange={(e) => chat.chonModel(e.target.value === "" ? null : e.target.value)}
            className="rounded-sm border border-border bg-background px-2 py-1 text-foreground"
          >
            <option value="">{t("chat.modelMacDinh")}</option>
            {chat.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name}
              </option>
            ))}
          </select>
        </label>

        {cay.conversationId !== null && (
          <code className="text-xs text-muted">{cay.conversationId}</code>
        )}
        <NhanKetNoi ketNoi={chat.ketNoi} />
        {chat.usage !== null && (
          <span className="text-xs text-muted">
            in={chat.usage.in} out={chat.usage.out}
          </span>
        )}
      </div>

      {chat.loi !== null && (
        <div className="flex items-center gap-3 border-b border-border px-6 py-2 text-sm text-danger-text">
          <span>{chat.loi}</span>
          <button
            type="button"
            onClick={chat.xoaLoi}
            className="rounded-sm border border-border px-2 text-foreground"
          >
            {t("loi.dong")}
          </button>
        </div>
      )}

      <main className="flex-1">
        {cay.conversationId === null ? (
          <p className="px-6 py-8 text-muted">{t("chat.chuaCoHoiThoai")}</p>
        ) : (
          cay.path.map((node) => (
            <MessageItem
              key={node.id}
              node={node}
              cay={cay}
              ghiChu={chat.ghiChu[node.id] ?? []}
              dangChay={chat.dangChay === node.id}
              onThuLai={(id) => void chat.thuLai(id)}
              onSua={(id, ban) => void chat.suaCauHoi(id, ban)}
              onChuyenNhanh={(n, huong) => void chat.chuyenNhanh(n, huong)}
            />
          ))
        )}
      </main>

      <Composer
        dangChay={chat.dangChay !== null}
        moDuoc={cay.conversationId !== null && !chat.dangBan}
        onGui={(ban) => void chat.gui(ban)}
        onDung={() => void chat.dung()}
      />
    </div>
  );
}
