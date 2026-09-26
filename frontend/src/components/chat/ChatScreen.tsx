import { LoaderCircle } from "lucide";

import { useSession } from "../../app/Layout";
import { t } from "../../lib/i18n";
import { useTypewriter } from "../../lib/motion";
import { useChat } from "../../features/chat/useChat";
import { ModelPicker } from "../../features/models/ModelPicker";
import { useModels } from "../../features/models/useModels";
import { QuotaNotice } from "../../features/quota/QuotaNotice";
import { byokCovers, isSendBlocked, selectedProviderId } from "../../features/quota/quotaView";
import { useQuota } from "../../features/quota/useQuota";
import { AccountMenu } from "../sidebar/AccountMenu";
import { Sidebar } from "../sidebar/Sidebar";
import { StaticIcon } from "../ui/Icon";
import { Composer } from "./Composer";
import { MessageItem } from "./MessageItem";

/**
 * `Date` → `"14:32"`. Dinh dang o DAY chu khong trong `ModelPicker`, vi
 * `t()` cua FE khong co interpolation (`lib/i18n.ts`): moc gio phai la mot
 * phan tu rieng dung canh cau chu, khong phai mot chuoi ghep.
 */
function formatTime(at: Date | null): string {
  if (at === null) {
    return t("model.checkedAtUnknown");
  }
  return at.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

/**
 * Loi chao cua man nhap — ban T-HD2-v2 muc A/E, go tung ky tu theo T-HD5-v2
 * muc 1b (`useTypewriter`, token `--duration-type`).
 *
 * Be rong giu nguyen trong luc go: ban day du TANG HINH giu cho, ban dang go
 * nam de len tu mep trai, nen chu can giua khong xe dich. Trinh doc man hinh
 * nghe cau day du mot lan (`sr-only`), khong nghe tung ky tu.
 */
function Greeting({ runKey }: { runKey: number }) {
  const full = t("draft.greeting");
  const { typed, typing } = useTypewriter(full, runKey);
  return (
    <h2 className="text-xl font-semibold lg:text-2xl lg:tracking-[-0.01em]">
      <span className="relative inline-block whitespace-nowrap">
        <span aria-hidden className="invisible">
          {full}
        </span>
        <span aria-hidden className="absolute top-0 left-0 whitespace-nowrap">
          <span className="motion-none">{typed}</span>
          {typing && <span className="caret-stream ml-0.5 rounded-sm" />}
        </span>
        <span className="sr-only">{full}</span>
      </span>
    </h2>
  );
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
  const modelCatalog = useModels();
  const session = useSession();
  /*
    T-3.11 — thanh quota doc `/auth/me` cua `Layout` (khong mot luot goi nao
    them) va nghe hai nhip tu `useChat`: `quota_warning` cua `202`, va "mot
    luot vua khep / vua bi `429`" de hoi lai `/auth/me`. Khong co bo dem thoi
    gian lam tuoi nao (B-209).
  */
  const quota = useQuota(session);
  const chat = useChat({
    models: modelCatalog.models,
    accountDefaultModel: session.profile?.default_model ?? null,
    // T-S.14 — muc da nho theo model (§24.2b·S4); `useChat` tinh muc hieu luc.
    reasoningPrefs: session.profile?.reasoning_prefs,
    onQuotaWarning: quota.noteWarning,
    onQuotaStale: () => void session.refreshProfile(),
  });
  const { tree } = chat;
  /*
    T-3.4 — tran ky tu den tu `GET /auth/me` (`message_max_chars`, NQ-78),
    khong tu mot hang so o FE (A3/L4). `Layout` da hoi mot lan roi nen o day
    chi la lay lai, khong them mot luot goi nao.

    `?? null` chu khong mot con so mac dinh: "chua biet tran" va "tran bang
    N" la hai chuyen khac nhau, va `Composer` xu ly ca dau rieng.
  */
  const maxChars = session.profile?.message_max_chars ?? null;

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
  const selectModel = async (modelId: string): Promise<void> => {
    try {
      await session.changeDefaultModel(modelId);
      await chat.changeConversationModel(modelId);
    } catch (e: unknown) {
      chat.showError(e instanceof Error ? e.message : String(e));
    }
  };

  /*
    T-S.14 — chon muc Thinking Effort: nho cho RIENG model dang dung, bang
    `PUT /settings` (du body — `useSessionState.changeReasoningPref`). Khong
    co tang hoi thoai nao cho muc (S4: body › da nho › catalog); lan gui ke
    tiep mang muc nay vi `useChat` doc lai `reasoning_prefs` vua ghi.
  */
  const selectEffort = async (level: string): Promise<void> => {
    const modelId = chat.effectiveModel;
    if (modelId === null) {
      return;
    }
    try {
      await session.changeReasoningPref(modelId, level);
    } catch (e: unknown) {
      chat.showError(e instanceof Error ? e.message : String(e));
    }
  };

  /*
    B-242 — picker song trong thanh cong cu duoi o nhap (ban T-HD4-v2 A: ten
    model chu tron, duoi-phai; popover `side="top"` mo LEN tu day, duoi 640 px
    la sheet).
  */
  const modelPicker = (
    <ModelPicker
      models={modelCatalog.models}
      defaultPick={chat.defaultPick}
      effort={chat.effectiveEffort}
      checkedAtLabel={formatTime(modelCatalog.checkedAt)}
      loading={modelCatalog.loading}
      refreshing={modelCatalog.refreshing}
      onRefresh={() => void modelCatalog.refresh()}
      onPick={(id) => void selectModel(id)}
      onPickEffort={(level) => void selectEffort(level)}
      onOpen={modelCatalog.refreshIfStale}
    />
  );
  /*
    Provider cua model SE GUI — quyet dinh luot ay tru quota hay di bang khoa
    rieng (Cam bay ①). Cung `effectiveModel` ma `gui()` dat vao `model_id`.
    KHOA provider, khong phai nhan — B-257, xem `selectedProviderId`.
  */
  const selectedProvider = selectedProviderId(modelCatalog.models, chat.effectiveModel);
  const quotaBlocked = isSendBlocked(quota.block, quota.byokProviders, selectedProvider);
  const draft = chat.phase === "draft";

  /*
    Bo cuc CO DINH (ban T-HD2, `AppShell.tsx`): header cua `Layout`, sidebar va
    o nhap dung yen; CHI cot tin nhan cuon. Ca man hinh cao dung phan con lai
    duoi header (`h-full` + `min-h-0` o moi tang flex), nen khong con thanh
    cuon cua `window` nao keo ca ba thu kia di theo.

    T-S.10 (ban T-HD2-v2): khong con dai trang thai (ma hoi thoai · trang thai
    ket noi · `in/out`, NQ-115) — chi con MOT thong bao noi o dinh cot khi
    stream dang noi lai.
  */
  return (
    <div className="flex h-full min-h-0 bg-background text-foreground">
      {/*
        T-3.3 — sidebar dung canh man chat chu khong trong `Layout`: danh sach
        hoi thoai chi co nghia sau `StatusGate`, va `/admin`, `/dang-nhap`
        khong co gi de liet ke. Danh sach ben trong tu cuon (`overflow-y-auto`).
      */}
      <Sidebar
        openConversationId={tree.conversationId}
        createdConversationId={chat.createdConversationId}
        // T-S.13: cua so nghe tieu de chay (`STREAM_TTL_S`, NQ-129).
        streamTtlS={session.profile?.stream_ttl_s ?? null}
        onSelect={(id) => void chat.openConversation(id)}
        onNewChat={chat.newConversation}
        onOpenConversationDeleted={chat.closeConversation}
        footer={
          /*
            T-S.12 — khoi tai khoan o chan sidebar, ca trong drawer: loi vao
            Cai dat, Muc su dung va Dang xuat (header v2 khong con email lan
            nut Dang xuat, NQ-115). `StatusGate` chi cho qua phien `active`,
            nen `user` o day co that; `null` (vua dang xuat) thi khong ve.
          */
          session.user !== null && (
            <AccountMenu
              user={session.user}
              avatarColor={session.profile?.avatar_color ?? null}
              onLogout={session.logout}
            />
          )
        }
      />

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {chat.connection === "dang-noi-lai" && (
          <div
            role="status"
            className="absolute top-3 left-1/2 z-10 flex max-w-[calc(100%-2*var(--spacing-gutter))] -translate-x-1/2 items-center gap-2 rounded-full border border-border-strong bg-surface-panel px-3.5 py-2 text-sm whitespace-nowrap shadow-popover"
          >
            <StaticIcon icon={LoaderCircle} size={16} className="motion-spin shrink-0 text-muted" />
            <span className="truncate">{t("chat.ketNoi.dangNoiLai")}</span>
          </div>
        )}

        {chat.error !== null && (
          <div className="flex shrink-0 items-center gap-3 border-b border-border px-gutter py-2 text-sm text-danger-text lg:px-gutter-lg">
            <span className="min-w-0 break-words">{chat.error}</span>
            <button
              type="button"
              onClick={chat.clearError}
              className="motion-press min-h-touch shrink-0 rounded-md border border-border px-3 text-foreground"
            >
              {t("loi.dong")}
            </button>
          </div>
        )}

        {/*
          T-S.10 — MOT khung, hai bo cuc; `Composer` o CUNG mot vi tri trong
          cay o ca hai (o cuoi), nen React giu nguyen phan tu `form` — chu dang
          go, cap khoa C22, va diem xuat phat cua FLIP (`useDock`) deu song qua
          lan doi.

          Man nhap (ban T-HD2-v2 muc A/E): luoi `1fr · auto · 1fr`. Loi chao o
          cuoi hang 1 (cach dinh hop 24), hop nhap o hang 2 — tam hop dung tam
          vung chat — va hang duoi cua o nhap o dau hang 3 (subgrid, xem
          `Composer`).
        */}
        <div
          className={
            draft
              ? "grid min-h-0 flex-1 grid-rows-[1fr_auto_1fr] justify-items-center"
              : "flex min-h-0 flex-1 flex-col"
          }
        >
          {draft && (
            <div className="self-end px-gutter pb-6 text-center lg:px-gutter-lg">
              <Greeting runKey={chat.draftEpoch} />
            </div>
          )}

          {/*
            T-3.5 — cot doc rong toi da `--spacing-measure` (736 px, ban T-HD3).
            Cot nay phai o DAY chu khong trong tung bong bong: bong bong nguoi
            dung neo phai bang `ml-auto`, va "phai" cua no la mep cot chu khong
            phai mep man hinh.
          */}
          {!draft && (
            <main className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
              <div className="mx-auto flex w-full max-w-measure flex-col gap-4 px-gutter pt-6 pb-4 lg:px-gutter-lg">
                {tree.path.map((node) => (
                  <MessageItem
                    key={node.id}
                    node={node}
                    tree={tree}
                    // T-S.15 — ten hien thi cho chip "model · muc" (ban T-HD3-v2 3c).
                    models={modelCatalog.models}
                    notes={chat.notes[node.id] ?? []}
                    running={chat.running === node.id}
                    // T-3.8 / B-232 — nut "Luu" cua bong bong nguoi dung tat
                    // trong luc mot thao tac doi cay con bay. `PATCH
                    // /messages/{id}` khong di qua §11.4 (NQ-93), nen bam hai
                    // lan la hai nhanh va hai hoa don.
                    busy={chat.busy}
                    // T-S.15 — MOT nut Thu lai: `useChat.retry` tu doc model +
                    // muc dang chon tren picker (§24.2b·S4). Bong bong khong
                    // biet gi ve picker, nen khong co nguon thu hai de lech.
                    onRetry={(id) => void chat.retry(id)}
                    onFeedback={(id, value) => void chat.sendFeedback(id, value)}
                    onEdit={(id, draft) => void chat.editQuestion(id, draft)}
                    onSwitchBranch={(n, direction) => void chat.switchBranch(n, direction)}
                  />
                ))}
              </div>
            </main>
          )}

          <Composer
            running={chat.running !== null}
            // Man nhap gui duoc: cau dau TAO hoi thoai (§24.2b·S7).
            enabled={!chat.busy}
            maxChars={maxChars}
            docked={!draft}
            // Tra nguyen `Promise<SendResult>` chu khong `void`: `Composer` giu
            // khoa cua §11.4 va no phai biet ket qua moi biet nen giu hay bo.
            onSend={chat.send}
            onStop={() => void chat.stop()}
            modelPicker={modelPicker}
            quotaBlocked={quotaBlocked}
            quotaNotice={
              <QuotaNotice
                readings={quota.readings}
                warnPct={quota.warnPct}
                block={quota.block}
                byokCovered={byokCovers(quota.byokProviders, selectedProvider)}
              />
            }
          />
        </div>
      </div>
    </div>
  );
}
