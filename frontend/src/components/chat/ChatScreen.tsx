import { Link } from "react-router";

import { useSession } from "../../app/Layout";
import { PATHS } from "../../app/paths";
import { t } from "../../lib/i18n";
import type { TrangThaiKetNoi } from "../../lib/sse";
import { useChat } from "../../features/chat/useChat";
import { ModelPicker } from "../../features/models/ModelPicker";
import { useModels } from "../../features/models/useModels";
import { QuotaBar } from "../../features/quota/ThanhQuota";
import { byokCovers, isSendBlocked, selectedProviderId } from "../../features/quota/quotaView";
import { useQuota } from "../../features/quota/useQuota";
import { Sidebar } from "../sidebar/Sidebar";
import { Composer } from "./Composer";
import { MessageItem } from "./MessageItem";

/**
 * `Date` → `"14:32"`. Dinh dang o DAY chu khong trong `ModelPicker`, vi
 * `t()` cua FE khong co interpolation (`lib/i18n.ts`): moc gio phai la mot
 * phan tu rieng dung canh cau chu, khong phai mot chuoi ghep.
 */
function gioPhut(luc: Date | null): string {
  if (luc === null) {
    return t("model.checkedAtUnknown");
  }
  return luc.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

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
 *
 * T-3.3 dat `Sidebar` canh no. Hai chieu day du lieu, khong hon: man chat noi
 * "toi dang mo hoi thoai nay" (`cay.conversationId`), sidebar noi "hay mo cai
 * kia" (`onSelect`) hoac "cai dang mo vua bi xoa" (`onOpenConversationDeleted`).
 * Sidebar tu giu danh sach cua no va KHONG doc `useChat` — hai man hinh hoi
 * server hai cau hoi khac nhau (`GET /conversations` va
 * `GET /conversations/{id}`), gop chung vao mot state la buoc ca hai phai lam
 * tuoi cung luc.
 */
export function ChatScreen() {
  /*
    T-3.6 — danh muc model song o mot hook rieng va duoc doc O DAY, roi day
    xuong ca hai ben: `useChat` can no de giai ba tang mac dinh, `ModelPicker`
    can no de ve danh sach. Mot nguon, hai nguoi doc — chu khong hai lan
    `GET /models`.
  */
  const danhMuc = useModels();
  const phien = useSession();
  /*
    T-3.11 — thanh quota doc `/auth/me` cua `Layout` (khong mot luot goi nao
    them) va nghe hai nhip tu `useChat`: `quota_warning` cua `202`, va "mot
    luot vua khep / vua bi `429`" de hoi lai `/auth/me`. Khong co bo dem thoi
    gian lam tuoi nao (B-209).
  */
  const quota = useQuota(phien);
  const chat = useChat({
    models: danhMuc.models,
    modelMacDinhTaiKhoan: phien.hoSo?.default_model ?? null,
    onQuotaWarning: quota.noteWarning,
    onQuotaStale: () => void phien.refreshProfile(),
  });
  const { cay } = chat;
  /*
    T-3.4 — tran ky tu den tu `GET /auth/me` (`message_max_chars`, NQ-78),
    khong tu mot hang so o FE (A3/L4). `Layout` da hoi mot lan roi nen o day
    chi la lay lai, khong them mot luot goi nao.

    `?? null` chu khong mot con so mac dinh: "chua biet tran" va "tran bang
    N" la hai chuyen khac nhau, va `Composer` xu ly ca dau rieng.
  */
  const tranKyTu = phien.hoSo?.message_max_chars ?? null;

  /*
    Mot lan chon ghi CA HAI tang, va thu tu la co y:

      1. `PUT /settings`  — tang tai khoan. UC-05 dong 4 (*"duoc nho theo
         user"*) va DoD dong 2 cua T-3.6 deu do dung cot `users.default_model`.
      2. `PATCH /conversations/{id}` — tang hoi thoai, de hoi thoai dang mo
         giu model nay ke ca khi sau do ho doi mac dinh tai khoan sang cai
         khac.

    Tang tai khoan di TRUOC vi no la tang duy nhat ap dung khi chua mo hoi
    thoai nao; neu buoc 2 hong (mat mang giua chung) thi thu da ghi duoc van
    la thu co tac dung rong hon. Hong o buoc 1 thi dung han — khong ghi mot
    nua roi bao thanh cong.
  */
  const chonModel = async (modelId: string): Promise<void> => {
    try {
      await phien.datModelMacDinh(modelId);
      await chat.datModelHoiThoai(modelId);
    } catch (e: unknown) {
      chat.datLoi(e instanceof Error ? e.message : String(e));
    }
  };

  /*
    B-242 — picker song trong thanh cong cu duoi o nhap (ban T-HD4: "trigger
    o composer"; popover `side="top"` mo LEN tu day, duoi 640 px la sheet).
  */
  const modelPicker = (
    <ModelPicker
      models={danhMuc.models}
      macDinh={chat.macDinh}
      nhanDocLuc={gioPhut(danhMuc.docLuc)}
      dangLamMoi={danhMuc.dangLamMoi}
      onLamMoi={() => void danhMuc.lamMoi()}
      onChon={(id) => void chonModel(id)}
    />
  );
  /*
    Provider cua model SE GUI — quyet dinh luot ay tru quota hay di bang khoa
    rieng (Cam bay ①). Cung `modelHieuLuc` ma `gui()` dat vao `model_id`.
    KHOA provider, khong phai nhan — B-257, xem `selectedProviderId`.
  */
  const providerDangChon = selectedProviderId(danhMuc.models, chat.modelHieuLuc);
  const quotaBlocked = isSendBlocked(quota.block, quota.byokProviders, providerDangChon);

  const coThanhTrangThai =
    cay.conversationId !== null || chat.ketNoi !== null || chat.usage !== null;

  /*
    Bo cuc CO DINH (ban T-HD2, `AppShell.tsx`): header cua `Layout`, sidebar va
    o nhap dung yen; CHI cot tin nhan cuon. Ca man hinh cao dung phan con lai
    duoi header (`h-full` + `min-h-0` o moi tang flex), nen khong con thanh
    cuon cua `window` nao keo ca ba thu kia di theo.
  */
  return (
    <div className="flex h-full min-h-0 bg-background text-foreground">
      {/*
        T-3.3 — sidebar dung canh man chat chu khong trong `Layout`: danh sach
        hoi thoai chi co nghia sau `StatusGate`, va `/admin`, `/dang-nhap`
        khong co gi de liet ke. Danh sach ben trong tu cuon (`overflow-y-auto`).
      */}
      <Sidebar
        openConversationId={cay.conversationId}
        onSelect={(id) => void chat.moHoiThoai(id)}
        onNewChat={() => void chat.hoiThoaiMoi()}
        onOpenConversationDeleted={chat.dongHoiThoai}
        footer={
          /*
            T-3.12 — loi vao trang Cai dat o chan sidebar: tren dien thoai day
            la loi DUY NHAT (header 375 px khong con cho, xem `Layout`).
          */
          <Link
            to={PATHS.settings}
            className="motion-press flex h-touch items-center rounded-md px-3 text-base text-foreground hover:bg-surface-hover"
          >
            {t("nav.settings")}
          </Link>
        }
      />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {coThanhTrangThai && (
          <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border px-gutter py-2 text-sm lg:px-gutter-lg">
            {cay.conversationId !== null && (
              <code className="break-all text-xs text-muted">{cay.conversationId}</code>
            )}
            <NhanKetNoi ketNoi={chat.ketNoi} />
            {chat.usage !== null && (
              <span className="text-xs text-muted">
                in={chat.usage.in} out={chat.usage.out}
              </span>
            )}
          </div>
        )}

        {chat.loi !== null && (
          <div className="flex shrink-0 items-center gap-3 border-b border-border px-gutter py-2 text-sm text-danger-text lg:px-gutter-lg">
            <span className="min-w-0 break-words">{chat.loi}</span>
            <button
              type="button"
              onClick={chat.xoaLoi}
              className="motion-press min-h-touch shrink-0 rounded-md border border-border px-3 text-foreground"
            >
              {t("loi.dong")}
            </button>
          </div>
        )}

        {/*
          T-3.5 — cot doc rong toi da `--spacing-measure` (736 px, ban T-HD3).
          Cot nay phai o DAY chu khong trong tung bong bong: bong bong nguoi
          dung neo phai bang `ml-auto`, va "phai" cua no la mep cot chu khong
          phai mep man hinh.
        */}
        <main className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
          {cay.conversationId === null ? (
            <p className="px-gutter py-8 text-muted lg:px-gutter-lg">{t("chat.chuaCoHoiThoai")}</p>
          ) : (
            <div className="mx-auto flex w-full max-w-measure flex-col gap-4 px-gutter py-6 lg:px-gutter-lg">
              {cay.path.map((node) => (
                <MessageItem
                  key={node.id}
                  node={node}
                  cay={cay}
                  ghiChu={chat.ghiChu[node.id] ?? []}
                  dangChay={chat.dangChay === node.id}
                  // T-3.8 / B-232 — nut "Luu" cua bong bong nguoi dung tat
                  // trong luc mot thao tac doi cay con bay. `PATCH
                  // /messages/{id}` khong di qua §11.4 (NQ-93), nen bam hai
                  // lan la hai nhanh va hai hoa don.
                  dangBan={chat.dangBan}
                  // T-3.7 — nut "Doi model & thu lai" gui dung model dang
                  // chon tren picker. Mot nguon, khong hai: neu no bang model
                  // da sinh ra cau tra loi nay thi nut tu tat.
                  modelDangChon={chat.modelHieuLuc}
                  onThuLai={(id, modelId) => void chat.thuLai(id, modelId)}
                  onDanhGia={(id, gia) => void chat.danhGia(id, gia)}
                  onSua={(id, ban) => void chat.suaCauHoi(id, ban)}
                  onChuyenNhanh={(n, huong) => void chat.chuyenNhanh(n, huong)}
                />
              ))}
            </div>
          )}
        </main>

        <Composer
          dangChay={chat.dangChay !== null}
          moDuoc={cay.conversationId !== null && !chat.dangBan}
          tranKyTu={tranKyTu}
          // Tra nguyen `Promise<KetQuaGui>` chu khong `void`: `Composer` giu
          // khoa cua §11.4 va no phai biet ket qua moi biet nen giu hay bo.
          onGui={chat.gui}
          onDung={() => void chat.dung()}
          modelPicker={modelPicker}
          quotaBlocked={quotaBlocked}
          quotaBar={
            <QuotaBar
              readings={quota.readings}
              warnPct={quota.warnPct}
              block={quota.block}
              byokCovered={byokCovers(quota.byokProviders, providerDangChon)}
            />
          }
        />
      </div>
    </div>
  );
}
