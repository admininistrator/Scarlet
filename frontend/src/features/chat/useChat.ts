/**
 * Day noi giua `api.ts`, `sse.ts`, `tree.ts` va man chat — T-1.14.
 *
 * KH tham chieu: §7.2, §7.4, §7.5, §8.2, §18.2, C6, C13, C14, C22.
 *
 * Component KHONG goi `fetch` va KHONG dung `EventSource` truc tiep; moi thu
 * do di qua day. Nho vay bon luat duoi day co dung MOT cho de dung.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  NAM LUAT                                                              ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * **1. Sau MOI thao tac lam doi cay, doc lai duong di tu server.** Gui, thu
 * lai, sua cau hoi, chuyen nhanh — bon thu do deu doi `sibling_count` cua
 * nhung node da co tren man hinh, va C13 noi ro FE khong duoc tu dem. Mot
 * `GET /conversations/{id}` la vai chuc mili-giay va no tra ve dung hai con so
 * do SQL tinh. Phan chu dang chay khong mat vi no nam ngoai `path` (luat 3 cua
 * `tree.ts`).
 *
 * **2. `parent_id` luon gui theo la CLIENT DANG THAY, khong de server tu lay
 * `active_leaf_id`** (C14). Hai tab cung mo mot hoi thoai thi tab thu hai van
 * gan dung vao cho no dang nhin, va server tra `branched: true` de noi ra.
 *
 * **3. Mot luc chi mot `EventSource` cho moi tab.** `openStreamFor` dong cai cu
 * truoc khi mo cai moi — khong phai de tiet kiem ket noi ma vi hai stream cua
 * cung mot message se cung noi chu vao mot cho. (Hai TAB thi khac: moi tab mot
 * cursor rieng, va §7.4/C7 doi ca hai cung chay.)
 *
 * **5. Delta duoc GOM theo khung hinh, khong day thang vao state** (B-234,
 * quy tac 4 cua ban T-HD3). Xem khoi "GOM DELTA THEO KHUNG HINH" duoi than
 * hook — day la cho duy nhat `appendDelta`/`appendReasoning` duoc goi.
 *
 * **4. Cay giu them o mot `ref`, khong chi trong `useState`.** Ham cap nhat
 * cua React chay luc RENDER chu khong luc goi, nen `setCay(cu => ...)` khong
 * tra lai duoc cay moi cho dong lenh ke tiep — ma `reload()` phai tra ve cay
 * vua doc de goi thang `ensureStream()`. Doc tu `ref` cung tranh mot ca stale
 * closure that: `gui()` can `activeLeafId` MOI NHAT (luat 2), khong phai gia
 * tri cua lan render tao ra no.
 *
 * ── C22 KHONG con o day (T-3.4) ──────────────────────────────────────────
 *
 * `khoaGuiRef` da roi file nay. Don vi cua C22 la **mot lan soan thao** —
 * *"sinh khi o nhap chuyen tu rong sang co chu, chi doi sau khi gui thanh
 * cong"* — ma `useChat` khong nhin thay o nhap: no chi thay nhung lan `gui()`
 * duoc goi, va mot `ref` o day song het doi hook nen no cung khong chet khi
 * nguoi dung xoa trang o nhap roi go mot cau khac han. Khoa gio thuoc ve
 * `Composer`; `gui()` nhan no nhu mot tham so va tra ve `SendResult` de chu
 * so huu biet nen giu hay nen bo.
 *
 * ── ...nhung C22 cua `retry` thi O DAY (T-3.7 / B-231) ───────────────────
 *
 * NQ-93 dua `POST /messages/{id}/retry` vao danh sach BAT BUOC `Idempotency-Key`,
 * nen nut Thu lai cung phai cam mot khoa. Khoa ay o lai `useChat` chu khong
 * di ra component, va ly do la don vi cua no khac han o nhap:
 *
 *   • Don vi la mot bo **(message, model, muc)** — "thu lai cau tra loi nay
 *     bang model va muc nay" (T-S.15: model + muc lay tu picker). `useChat` la
 *     cho duy nhat biet ca ba.
 *   • Hang nut song va chet theo duong di: sau mot lan thu lai thanh cong,
 *     `active_leaf_id` doi sang anh em MOI nen bong bong cu bien mat khoi
 *     `path` va component cua no unmount. Mot `ref` trong component se chet
 *     theo, tuc luat 2 cua C22 (giu nguyen khoa qua moi lan HONG) mat dung
 *     luc no can nhat.
 *
 * Ba dong luat giong het `Composer`, chi khac cho sinh: **sinh** o lan bam dau
 * cho mot cap, **giu** qua moi lan hong (mang rot, `500`, `503` — van la mot
 * y dinh), **bo** khi va chi khi `202` ve. Nho vay bam nhanh hai lan la mot
 * hoa don, con bam lai sau khi da xong la mot anh em that (§8.2 cho phep).
 *
 * ── Hoi thoai NHAP (T-S.10, §24.2b·S7, NQ-111) ───────────────────────────
 *
 * Mo `/` hay bam "Hoi thoai moi" ⇒ man NHAP: cay rong, **khong mot loi goi
 * API nao** va khong mot hang nao trong DB. Hook nay khong co `useEffect` nao
 * tao san hoi thoai — `StrictMode` chay effect hai lan (B-260), nen mot effect
 * nhu vay la hai hoi thoai rong moi lan mo app, chi o dev, khong ai thay.
 *
 * Cau DAU gui di la hai buoc, hai khoa (`SendKeys`), hai route:
 *
 *   1. `POST /conversations`              — khoa `conversation`
 *   2. `POST /conversations/{id}/messages` — khoa `message`
 *
 * Buoc 1 xong ma buoc 2 hong ⇒ id vua tao nam o `draftConversationRef`, va
 * lan thu lai BO QUA buoc 1: khong co `POST /conversations` thu hai, nen khong
 * co hoi thoai rong thu hai. Id ay chi song khi man nhap con tren man hinh —
 * mo mot hoi thoai khac la bo no (xem `openConversation`).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  ERROR_CODES,
  api,
  type Feedback,
  type MessageOut,
  type ModelOut,
  type PathArtifact,
  type QuotaWarning,
} from "../../lib/api";
import { PATHS } from "../../app/paths";
import { newKey } from "../../lib/idempotency";
import { isEndpointModel } from "../models/byokModels";
import { pickDefault, type DefaultPick } from "../models/defaults";
import { effectiveEffort } from "../models/reasoning";
import { openStream, type StreamHandle, type ConnectionStatus, type UsageOut } from "../../lib/sse";
import {
  startGeneration,
  canStream,
  emptyTree,
  adjacentSiblingId,
  loadConversation,
  appendDelta,
  appendReasoning,
  type TreeState,
} from "../../lib/tree";

/** Tham so URL giu hoi thoai dang mo — de F5 quay lai dung cho (M3). */
const CONVERSATION_PARAM = "c";

/**
 * T-S.19a — duong mo mot hoi thoai tu ngoai man chat (dao o `/cai-dat`,
 * `/admin`): man chat mount la doc `?c=` (`readConversationParam`).
 */
export function conversationHref(id: string): string {
  return `${PATHS.home}?${new URLSearchParams({ [CONVERSATION_PARAM]: id }).toString()}`;
}

function readConversationParam(): string | null {
  return new URLSearchParams(window.location.search).get(CONVERSATION_PARAM);
}

function writeConversationParam(id: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set(CONVERSATION_PARAM, id);
  window.history.replaceState(null, "", url);
}

/** T-3.3 — hoi thoai vua bi xoa thi `?c=` cua no khong duoc song sot qua F5. */
function clearConversationParam(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete(CONVERSATION_PARAM);
  window.history.replaceState(null, "", url);
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}

/**
 * Ba ket cuc cua mot lan bam Gui — T-3.4.
 *
 * `gui()` tra ve thay vi chi `setError()`, vi tu T-3.4 **khoa `Idempotency-Key`
 * khong con song o day** (C22: no thuoc ve mot lan soan thao, tuc ve
 * `Composer`). Nguoi giu khoa phai biet duoc lam gi voi no:
 *
 *   `da-gui`   — `202` (ke ca ban phat lai cua §11.4). Bo khoa, xoa o nhap.
 *   `ket-khoa` — `409 IN_PROGRESS`: mot request khac dang giu dung khoa nay.
 *                Chinh la ca B-143 — mot tien trinh `api` chet giua chung se
 *                de khoa o trang thai ay 24 gio. GIU nguyen chu da go va mo
 *                duong thoat (Cam bay ①).
 *   `hong`     — moi ket cuc con lai. GIU ca chu lan khoa: C22 doi lan thu
 *                lai mang **dung mot** khoa, va chu da go khong duoc bien mat.
 */
export type SendResult = "da-gui" | "ket-khoa" | "hong";

/**
 * Hai `Idempotency-Key` cua MOT lan soan thao — T-S.10, §24.2b·S7, C22.
 *
 * Sinh CUNG LUC khi o nhap chuyen tu rong sang co chu (`Composer`), giu qua
 * moi lan thu lai. `conversation` chi duoc dung o man nhap (buoc 1); trong mot
 * hoi thoai da co thi no nam yen. Hai khoa chu khong mot (Cam bay ④): khoa
 * Redis cua §11.4 da chua ten route nen mot khoa cung an toan, nhung khi ay
 * phep do C22 khong con tach duoc endpoint nao giu khoa nao.
 */
export interface SendKeys {
  conversation: string;
  message: string;
}

/**
 * Man hinh chat dang o dau — T-S.10.
 *
 * `draft`: chua co hoi thoai nao (ban T-HD2-v2: o nhap GIUA man, loi chao).
 * `conversation`: mot hoi thoai dang mo, HOAC dang mo (`?c=` luc F5 — neu
 * khong, F5 vao mot hoi thoai co se thay man nhap loe len mot nhip roi o nhap
 * truot xuong day).
 */
export type ChatPhase = "draft" | "conversation";

export interface ChatState {
  tree: TreeState;
  phase: ChatPhase;
  /**
   * Dem so lan VAO man nhap bang tay ("Hoi thoai moi", hoac hoi thoai dang mo
   * bi xoa). Loi chao go lai chu moi khi so nay doi (ban T-HD5-v2, muc 1b).
   */
  draftEpoch: number;
  /**
   * Hoi thoai vua ra doi tu man nhap cua tab nay — dat ngay khi cau dau cua
   * no nhan `202`, cung luot voi id cua cay. Sidebar nghe gia tri nay (T-S.13
   * them tieu de chay chu tren dung hang ay).
   */
  createdConversationId: string | null;
  /**
   * T-3.6 — TANG 1 cua ba tang mac dinh: `conversations.default_model` cua
   * hoi thoai dang mo. `null` = hoi thoai nay khong dat gi, hoac chua mo
   * hoi thoai nao.
   *
   * Doc tu server o moi lan `reload()`, khong giu mot ban rieng: no la mot
   * cot cua hang `conversations` va `PATCH` tra ve ca hang ay.
   */
  conversationModel: string | null;
  /**
   * Ket qua day du cua `pickDefault()` tren ba tang: model dang dung, tang
   * da quyet dinh no, va id hop le cua tung tang.
   *
   * Tinh MOT lan o day chu khong de moi ben tu tinh: `ModelPicker` ve rail
   * va chip tu chinh phep chon ma `gui()` dung de dat `model_id`, nen hai
   * phep chon roi nhau la mot man hinh chi vao model nay va mot request gui
   * di model khac.
   */
  defaultPick: DefaultPick;
  /**
   * Loi tat cua `defaultPick.modelId` — model dang chon tren picker, tuc model
   * cua lan GUI ke tiep **va** cua moi lan `retry` (T-S.15: mot nut Thu lai).
   */
  effectiveModel: string | null;
  /**
   * T-S.14 — muc suy luan cua `effectiveModel` cho lan GUI ke tiep
   * (`features/models/reasoning.ts`), hoac `null` khi model ay khong co khoi
   * `reasoning`. Cung gia tri picker in o hang Thinking Effort — mot phep tinh,
   * hai nguoi doc, cung ly do `defaultPick` o tren.
   */
  effectiveEffort: string | null;
  /** `null` = khong co stream nao dang mo trong tab nay. */
  connection: ConnectionStatus | null;
  /** Id message assistant dang chay, hoac `null`. */
  running: string | null;
  busy: boolean;
  usage: UsageOut | null;
  /** Chip cua `tool_call`/`tool_result`, theo `message_id`. */
  notes: Record<string, string[]>;
  /**
   * T-5.3 — artifact cua mot message: `artifacts[]` cua duong di (song qua F5,
   * qua `STREAM_TTL_S` — B-87) cong the vua toi qua event ma duong di chua co.
   * Tra lai CHINH mang cua duong di khi khong co gi them (on dinh cho `memo`).
   */
  artifactsOf: (node: MessageOut) => readonly PathArtifact[];
  error: string | null;

  /**
   * T-3.6 — ghi TANG 1 (`PATCH /conversations/{id}` `{default_model}`).
   *
   * Khong lam gi khi chua mo hoi thoai nao: luc do chi con tang tai khoan,
   * va no thuoc ve `useSessionState` chu khong ve day.
   */
  changeConversationModel: (modelId: string) => Promise<void>;
  /** T-S.10 — ve man nhap. KHONG goi API nao (§24.2b·S7). */
  newConversation: () => void;
  /** T-3.3 — sidebar chon mot hoi thoai da co. */
  openConversation: (conversationId: string) => Promise<void>;
  /** T-3.3 — hoi thoai dang mo vua bi xoa: roi khoi no, ve man nhap. */
  closeConversation: () => void;
  /** Hai khoa do NGUOI GOI cam (C22) — xem `SendResult`, `SendKeys`. */
  send: (content: string, keys: SendKeys, attachmentIds?: readonly string[]) => Promise<SendResult>;
  stop: () => Promise<void>;
  /**
   * §8.2 — sinh lai cau tra loi `messageId` thanh mot anh em cua no, bang
   * model VA muc dang chon tren picker (`effectiveModel`, `effectiveEffort` —
   * T-S.15, §24.2b·S4). Khong con tham so model: doi model la doi tren picker
   * roi bam Thu lai (UC-02 dong 5, UC-04 dong 4).
   *
   * Khoa §11.4 khong o chu ky nay: xem khoi C22 o docstring module.
   */
  retry: (messageId: string) => Promise<void>;
  /**
   * §18.2 — Like/Dislike. `gia === null` la **go** danh gia (bam lai lan hai).
   *
   * Khong nhan `reason`: ban T-HD3 chi co hai nut sang/toi, khong co o nhap ly
   * do — va mot ly do gui len hom nay khong doc lai duoc o dau (B-244).
   * `api.sendFeedback` van mo duong cho no.
   */
  sendFeedback: (messageId: string, value: Feedback | null) => Promise<void>;
  editQuestion: (messageId: string, content: string) => Promise<void>;
  switchBranch: (node: MessageOut, direction: -1 | 1) => Promise<void>;
  /** Dat mot cau loi len bang loi cua man chat (T-3.6 — xem `ChatScreen`). */
  showError: (text: string) => void;
  clearError: () => void;
}

/**
 * Hai thu `useChat` can tu ben ngoai de dung duoc ba tang mac dinh (T-3.6).
 *
 * Danh muc model KHONG con nap trong hook nay: no da chuyen sang
 * `features/models/useModels.ts`, noi co ca luat "mo picker khong goi API"
 * (Cam bay ②). `useChat` chi la mot NGUOI DOC cua danh muc ay — no can
 * danh sach de biet `default: true` cua catalog la model nao, va de bo qua
 * mot `default_model` da bien mat khoi catalog (Cam bay ①).
 */
export interface ChatOptions {
  /** Danh sach cua `GET /models` — xem `useModels()`. */
  models: ModelOut[];
  /** TANG 2: `users.default_model` tu `GET /auth/me`. */
  accountDefaultModel: string | null;
  /**
   * T-S.14 — `reasoning_prefs` cua `GET /auth/me` (`{model_id: level}`).
   * Vang mat = chua nho muc nao, moi model chay o `reasoning.default`.
   */
  reasoningPrefs?: Readonly<Record<string, string>>;
  /**
   * T-3.11 — `quota_warning` cua mot `202` (gui, thu lai, sua). Nguon THU HAI
   * cua con so thanh quota dang hien; nguoi nghe quyet dinh ghep the nao.
   */
  onQuotaWarning?: (warning: QuotaWarning) => void;
  /**
   * T-3.11 — con so quota vua co the doi: mot luot sinh vua khep (`done`/
   * `error`) hoac server vua tra `429 QUOTA_EXCEEDED`. Day la nhip lam tuoi
   * DUY NHAT cua thanh quota — khong co bo dem thoi gian nao (B-209).
   */
  onQuotaStale?: () => void;
  /**
   * T-5.3 — mot artifact MOI vua toi qua stream (UC-10 dong 1: mo panel phai).
   * Goi dung mot lan moi `artifact_id` trong doi hook, sau `GET /artifacts/{id}`
   * (hong ⇒ voi phan event biet). Artifact da co tren duong di — mo lai hoi
   * thoai, F5, `XRANGE` phat lai (§7.3) — KHONG goi.
   */
  onArtifact?: (artifact: PathArtifact) => void;
}

/**
 * Mac dinh cho ban goi `useChat()` khong tham so (bo test cua T-3.4 va moi
 * man hinh khong co picker). Hang so o TAM MODULE chu khong mot object
 * literal trong chu ky ham: mot literal se la mot object MOI moi lan render,
 * tuc moi `useCallback` phu thuoc vao no deu dung lai o moi khung hinh.
 */
const NO_OPTIONS: ChatOptions = { models: [], accountDefaultModel: null };
/** Cung ly do `NO_OPTIONS`: mot `{}` literal la mot object moi moi lan render. */
const NO_PREFS: Readonly<Record<string, string>> = {};
/** Cung ly do: `artifactsOf` tra MOT mang rong cho moi message khong co artifact. */
const NO_ARTIFACTS: readonly PathArtifact[] = [];

export function useChat(options: ChatOptions = NO_OPTIONS): ChatState {
  const { models, accountDefaultModel, reasoningPrefs = NO_PREFS } = options;
  /*
    Hai callback quota di qua `ref`: `ChatScreen` truyen chung la closure moi
    moi lan render, va dua chung vao phu thuoc cua `openStreamFor`/`gui` se dung
    lai ca chuoi `useCallback` o moi khung hinh.
  */
  const quotaHooksRef = useRef({
    onQuotaWarning: options.onQuotaWarning,
    onQuotaStale: options.onQuotaStale,
  });
  // T-5.3 — cung ly do: closure moi moi lan render.
  const artifactHookRef = useRef(options.onArtifact);
  useEffect(() => {
    quotaHooksRef.current = {
      onQuotaWarning: options.onQuotaWarning,
      onQuotaStale: options.onQuotaStale,
    };
    artifactHookRef.current = options.onArtifact;
  });
  /** `202` vua ve — chuyen `quota_warning` (neu co) cho nguoi nghe. */
  const reportQuotaWarning = useCallback((warning: QuotaWarning | null | undefined) => {
    if (warning !== null && warning !== undefined) {
      quotaHooksRef.current.onQuotaWarning?.(warning);
    }
  }, []);
  /** Loi cua mot lan tao luot sinh — `429 QUOTA_EXCEEDED` thi quota da doi. */
  const reportQuotaError = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.code === ERROR_CODES.QUOTA_EXCEEDED) {
      quotaHooksRef.current.onQuotaStale?.();
    }
  }, []);
  const [tree, setTree] = useState<TreeState>(emptyTree);
  const [conversationModel, setConversationModel] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionStatus | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState<UsageOut | null>(null);
  const [notes, setNotes] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  /*
    T-S.10 — `true` trong luc `open()` doi `GET /conversations/{id}`. Gia tri
    DAU doc thang URL: F5 tren `?c=` phai ve khung "trong hoi thoai" ngay tu
    khung hinh dau, khong ve man nhap roi moi truot xuong.
  */
  const [opening, setOpening] = useState(() => readConversationParam() !== null);
  const [draftEpoch, setDraftEpoch] = useState(0);
  const [createdConversationId, setCreatedConversationId] = useState<string | null>(null);
  /**
   * T-S.10 — hoi thoai buoc 1 cua man nhap da tao ma buoc 2 chua `202`.
   * `ref` chu khong `state`: lan thu lai doc no ngay trong cung mot luot, va
   * no khong ve gi len man hinh.
   */
  const draftConversationRef = useRef<string | null>(null);

  /*
    Ba tang, mot phep chon, mot cho (T-3.6). `pickDefault` la ham THUAN nen
    khong can `useMemo`: no duyet mot mang bon phan tu.

    Day cung la cho Cam bay ① duoc dong cho CA hai tang tren: mot
    `default_model` tro vao model da bien mat khoi catalog bi bo qua va roi
    xuong tang duoi, thay vi tro thanh mot `model_id` gay `400 MODEL_UNKNOWN`
    o lan gui ke tiep.
  */
  const defaultPick = pickDefault(models, {
    conversation: conversationModel,
    account: accountDefaultModel,
  });
  const effectiveModel = defaultPick.modelId;
  /*
    T-S.14 — chuoi (hoac `null`), khong phai object: `send` phu thuoc vao no
    ma khong dung lai o moi khung hinh chi vi `reasoning_prefs` la object moi.
  */
  const effort = effectiveEffort(
    models.find((m) => m.id === effectiveModel),
    reasoningPrefs,
  );

  //: Luat 4 — ban doc duoc ngay cua cung mot cay.
  const treeRef = useRef<TreeState>(emptyTree());
  const streamRef = useRef<StreamHandle | null>(null);
  /*
    C22 cho nut Thu lai (B-231): `${messageId}:${modelId}:${muc}` → khoa §11.4.

    `Map` chu khong mot chuoi duy nhat: hai bong bong khac nhau tren cung mot
    man hinh la hai y dinh khac nhau. Model va muc nam TRONG khoa (T-S.15):
    bam Thu lai, hong, doi model tren picker roi bam lai la mot y dinh MOI —
    dung lai khoa cu se lam lan bam sau nhan ban phat lai cua lan truoc (§11.4
    tra lai response da luu), tuc doi model khong co tac dung gi.

    `ref` chu khong `state`: hai lan bam trong cung mot luot render phai doc
    duoc CUNG mot gia tri (cai bay S5, y het `keyRef` cua `Composer`).

    Muc chi bi xoa khi `202` ve, nen mot lan hong se de lai mot muc song het
    doi hook. Do la co y (luat 2 cua C22) va no khong phai mot cho ro: so muc
    bi chan boi so bong bong nguoi dung da bam nham, khong boi thoi gian.
  */
  const retryKeysRef = useRef<Map<string, string>>(new Map());

  const updateTree = useCallback((updater: (prev: TreeState) => TreeState): TreeState => {
    const next = updater(treeRef.current);
    treeRef.current = next;
    setTree(next);
    return next;
  }, []);

  const addNote = useCallback((messageId: string, text: string) => {
    setNotes((prev) => ({ ...prev, [messageId]: [...(prev[messageId] ?? []), text] }));
  }, []);

  /*
    T-5.3 — artifact vua toi qua stream, theo `message_id`, cho toi khi duong di
    co no. `seenArtifactsRef` chong lap theo `artifact_id`: noi lai TAY (C6) di
    tu cursor nhung `XRANGE` cua mot tab moi phat lai MOI event (§7.3) — moi
    lan phat lai la mot `GET` va mot lan mo panel nua neu khong chan o day.
  */
  const [streamArtifacts, setStreamArtifacts] = useState<Record<string, PathArtifact[]>>({});
  const seenArtifactsRef = useRef(new Set<string>());

  const receiveArtifact = useCallback(
    (messageId: string, data: { artifact_id: string; kind: string; title: string; version: number }) => {
      const id = data.artifact_id;
      const onPath = treeRef.current.path.some((m) => m.artifacts?.some((a) => a.id === id) === true);
      if (seenArtifactsRef.current.has(id) || onPath) {
        return;
      }
      seenArtifactsRef.current.add(id);
      // The hien NGAY tu phan event biet; `content` chua co ⇒ the nam duoi chu
      // cho toi khi `GET` ve (khong khop khoi nao — B-363).
      const card: PathArtifact = { id, kind: data.kind, title: data.title, version: data.version, language: null, content: null };
      const put = (artifact: PathArtifact) =>
        setStreamArtifacts((prev) => ({
          ...prev,
          [messageId]: [...(prev[messageId] ?? []).filter((a) => a.id !== id), artifact],
        }));
      put(card);
      void api.getArtifact(id).then(
        (full) => {
          const loaded: PathArtifact = { ...card, language: full.language, content: full.content };
          put(loaded);
          artifactHookRef.current?.(loaded);
        },
        () => artifactHookRef.current?.(card),
      );
    },
    [],
  );

  const artifactsOf = useCallback(
    (node: MessageOut): readonly PathArtifact[] => {
      const onPath = node.artifacts ?? NO_ARTIFACTS;
      const extra = (streamArtifacts[node.id] ?? []).filter((a) => !onPath.some((p) => p.id === a.id));
      return extra.length === 0 ? onPath : [...onPath, ...extra];
    },
    [streamArtifacts],
  );

  // ╔══════════════════════════════════════════════════════════════════════╗
  // ║  GOM DELTA THEO KHUNG HINH — B-234, quy tac 4 cua ban T-HD3          ║
  // ╚══════════════════════════════════════════════════════════════════════╝
  //
  // T-1.14 do duoc **309 delta trong 3,768 giay**, khoang cach lon nhat giua
  // hai manh la 22 ms. Day thang moi manh vao `setTree` nghia la 309 lan React
  // dung lai ca bong bong trong 4 giay — nhanh hon han toc do man hinh ve
  // duoc (60 Hz = mot khung moi 16,7 ms), tuc phan lon cong ay khong bao gio
  // xuat hien truoc mat ai.
  //
  // Bo dem duoi day gom cac manh lai va chi day vao state MOT LAN moi khung
  // hinh: ~60 lan/giay thay vi 309 lan trong 4 giay, ma mat khong thay khac.
  //
  // Ba dieu phai dung, va ca ba deu la cho de hong:
  //
  //   1. **`start` XOA phan dang cho cua chinh message do.** `start` nghia la
  //      "bat dau tu dau" ke ca khi no den tu duong dung lai bang Postgres
  //      (T-1.14 ④). Mot manh con nam trong bo dem tu truoc `start` ma duoc
  //      xa sau do se noi chu cu vao sau chu moi — dung trieu chung C3 nhung
  //      do loi cua client.
  //   2. **`done`/`error`/dong stream XA NGAY, khong doi khung hinh ke.**
  //      Sau `done` la `reload()`, va mot manh xa muon hon no se noi them
  //      chu vao mot message da khep.
  //   3. **Tab bi an thi `requestAnimationFrame` khong chay** — dung nhu mong
  //      muon: chu don lai trong bo dem, khong ai ve gi ca, va mot lan xa duy
  //      nhat bat kip luc nguoi dung quay lai. Duong `done` o diem 2 la thu
  //      bao dam ca truong hop tab an suot ca luot sinh.
  const pendingRef = useRef(new Map<string, { content: string; reasoning: string }>());
  const frameRef = useRef<number | null>(null);

  /** Xa bo dem NGAY lap tuc va huy khung hinh dang cho. */
  const flushDeltas = useCallback(() => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    const pending = pendingRef.current;
    if (pending.size === 0) {
      return;
    }
    // Thay bang Map moi TRUOC khi dung: `updateTree` goi `setTree`, va mot manh
    // den giua chung phai roi vao lo hang sau chu khong vao lo dang xa.
    pendingRef.current = new Map();
    updateTree((c) => {
      let next = c;
      for (const [messageId, piece] of pending) {
        if (piece.content !== "") {
          next = appendDelta(next, messageId, piece.content);
        }
        if (piece.reasoning !== "") {
          next = appendReasoning(next, messageId, piece.reasoning);
        }
      }
      return next;
    });
  }, [updateTree]);

  const queueDelta = useCallback(
    (messageId: string, field: "content" | "reasoning", piece: string) => {
      const prev = pendingRef.current.get(messageId) ?? { content: "", reasoning: "" };
      pendingRef.current.set(messageId, { ...prev, [field]: prev[field] + piece });
      if (frameRef.current === null) {
        frameRef.current = window.requestAnimationFrame(() => {
          frameRef.current = null;
          flushDeltas();
        });
      }
    },
    [flushDeltas],
  );

  /**
   * Dong stream cua tab nay — XA truoc, dong sau.
   *
   * Xa chu khong bo: moi noi goi ham nay deu la mot lan roi khoi stream (doi
   * hoi thoai, doi nhanh, unmount), va phan chu da nhan duoc thi da nhan
   * duoc. Bo no di la lam mat 16 ms cuoi cua cau tra loi vi mot ly do ky
   * thuat khong ai nhin thay. Ca DUY NHAT phai bo la `start`, va no bo tay o
   * `onEvent` chu khong o day.
   */
  const closeStream = useCallback(() => {
    flushDeltas();
    streamRef.current?.close();
    streamRef.current = null;
  }, [flushDeltas]);

  /** Doc lai duong di tu server — luat 1. Tra ve cay moi de goi tiep. */
  const reload = useCallback(
    async (conversationId: string): Promise<TreeState | null> => {
      try {
        const detail = await api.getConversation(conversationId);
        // TANG 1 di cung duong di: `GET /conversations/{id}` tra ca hai, nen
        // khong co mot loi goi rieng nao de hai gia tri lech nhau.
        setConversationModel(detail.default_model);
        return updateTree((prev) => loadConversation(prev, detail));
      } catch (e) {
        setError(errorText(e));
        return null;
      }
    },
    [updateTree],
  );

  const openStreamFor = useCallback(
    (url: string, messageId: string, conversationId: string) => {
      // Luat 3: mot tab, mot stream.
      closeStream();
      setRunning(messageId);
      setUsage(null);

      streamRef.current = openStream({
        url,
        onStatus: (status) => {
          setConnection(status);
          // Noi lai duoc thi bang loi cua lan dut truoc KHONG duoc o lai tren
          // man hinh: DoD "Offline 5 s roi bat lai" ket thuc bang mot man hinh
          // dang chay, ma mot dong "Failed to fetch" nam yen o do doc y het
          // mot cai hong chua duoc sua (B-115).
          if (status === "dang-chay") {
            setError(null);
          }
        },
        onFatal: (text) => {
          // Stream chet giua chung: phan da nhan duoc phai len man hinh, neu
          // khong thi 16 ms cuoi bien mat cung voi ket noi (luat 5, diem 2).
          flushDeltas();
          setError(text);
        },
        onWarning: setError,
        onEvent: (event) => {
          switch (event.event) {
            case "start":
              // Xoa phan cu: `start` nghia la "bat dau tu dau" ke ca khi no
              // den tu duong dung lai bang Postgres (§7.4, diem 4 cua sse.ts).
              // Bo dem phai bi bo TRUOC `startGeneration`, khong phai xa: mot manh
              // cua lan sinh truoc ma xa sau `start` se noi chu cu vao sau
              // chu moi (luat 5, diem 1).
              pendingRef.current.delete(event.data.message_id);
              updateTree((c) => startGeneration(c, event.data.message_id));
              break;
            case "delta":
              queueDelta(messageId, "content", event.data.t);
              break;
            case "reasoning":
              queueDelta(messageId, "reasoning", event.data.t);
              break;
            case "tool_call":
              addNote(messageId, `tool_call ${event.data.name}`);
              break;
            case "tool_result":
              addNote(
                messageId,
                `tool_result ${event.data.name} ${event.data.ok ? "ok" : "loi"}`,
              );
              break;
            case "artifact":
              receiveArtifact(messageId, event.data);
              break;
            case "usage":
              setUsage(event.data);
              break;
            case "done":
              // Xa TRUOC `reload()`: mot manh xa muon hon no se noi them chu
              // vao mot message da khep (luat 5, diem 2).
              flushDeltas();
              if (event.data.usage !== null) {
                setUsage(event.data.usage);
              }
              setRunning(null);
              void reload(conversationId);
              quotaHooksRef.current.onQuotaStale?.();
              break;
            case "error":
              flushDeltas();
              setError(`${event.data.code}: ${event.data.message}`);
              setRunning(null);
              void reload(conversationId);
              // Mot luot hong giua chung van co the da tieu tien (worker ghi
              // `usage_events` cho phan da sinh), nen `error` cung lam tuoi.
              quotaHooksRef.current.onQuotaStale?.();
              break;
          }
        },
      });
    },
    [updateTree, closeStream, flushDeltas, reload, queueDelta, addNote, receiveArtifact],
  );

  /**
   * Mo stream neu la cuoi con `queued`/`streaming`.
   *
   * Day la toan bo phan "F5 giua luc stream" (M3) va "dong tab, mo lai sau 30
   * giay": khong co gi luu o client, cau tra loi nam trong Postgres va Redis.
   */
  const ensureStream = useCallback(
    (nextTree: TreeState) => {
      const node = canStream(nextTree);
      if (node === null || nextTree.conversationId === null) {
        return;
      }
      openStreamFor(`/api/v1/messages/${node.id}/stream`, node.id, nextTree.conversationId);
    },
    [openStreamFor],
  );

  const open = useCallback(
    async (conversationId: string) => {
      setOpening(true);
      try {
        const nextTree = await reload(conversationId);
        if (nextTree !== null) {
          writeConversationParam(conversationId);
          ensureStream(nextTree);
        }
      } finally {
        setOpening(false);
      }
    },
    [ensureStream, reload],
  );

  /**
   * Hoi thoai ghi trong URL. Goi luc mount, va goi lai khi mang ve.
   *
   * KHONG con nap `/models` o day (T-3.6): danh muc model doi chu — no can
   * mot nut lam moi, mot moc gio, va luat "khong goi lai khi mo dropdown" —
   * nen no co hook rieng (`features/models/useModels.ts`). Hai thu tung di
   * chung chi vi ca hai cung phai chay luc mount.
   */
  const loadInitial = useCallback(() => {
    const id = readConversationParam();
    if (id !== null) {
      void open(id);
    }
  }, [open]);

  // ── nap lan dau, va nap LAI neu lan dau roi dung luc mat mang ──
  useEffect(() => {
    loadInitial();

    /**
     * F5 trong luc DevTools con dat Offline thi ca `/models` lan
     * `GET /conversations/{id}` deu nem `Failed to fetch`, va man hinh ket o
     * do voi mot bang loi — khong co duong nao ve tru mot lan F5 nua. Mot lan
     * mat mang khong duoc phep doi mot lan tai trang (B-115).
     *
     * Chi lo phan KHOI DONG: stream dang song thi `sse.ts` tu lo lay phan cua
     * no, dung vao day la mo thua mot ket noi.
     */
    function handleOnline(): void {
      if (treeRef.current.conversationId === null) {
        loadInitial();
      }
    }

    window.addEventListener("online", handleOnline);
    return () => {
      window.removeEventListener("online", handleOnline);
      closeStream();
    };
  }, [closeStream, loadInitial]);

  /**
   * T-S.10 — hoi thoai dang mo roi khoi man hinh, ve man NHAP.
   *
   * KHONG goi API nao, va do la toan bo diem cua §24.2b·S7 (NQ-111): ban T-3.x
   * `POST /conversations` ngay o day, nen moi lan bam "Hoi thoai moi" ma khong
   * go gi la mot hang rong nam lai trong DB. Hoi thoai gio ra doi o cau dau
   * (`send`). Dung chung cho "Hoi thoai moi" va "hoi thoai dang mo vua bi xoa".
   */
  const leaveConversation = useCallback(() => {
    closeStream();
    setRunning(null);
    setConnection(null);
    setUsage(null);
    setError(null);
    setConversationModel(null);
    updateTree(() => emptyTree());
    clearConversationParam();
    setDraftEpoch((n) => n + 1);
  }, [updateTree, closeStream]);

  /**
   * T-3.3 — sidebar chon mot hoi thoai da co.
   *
   * Dong stream cu TRUOC khi mo hoi thoai khac: luat 3 cua file nay cho moi
   * tab mot `EventSource`, va mot stream con song cua hoi thoai truoc se noi
   * chu cua no vao cay vua nap.
   *
   * T-S.10: roi man nhap bang duong nay la BO hoi thoai buoc 1 dang treo (neu
   * co). No da nam trong DB va sidebar se liet ke no; gui vao no tu man nhap
   * sau nay voi `parent_id = null` la mot goc thu hai trong mot hoi thoai co
   * the da co tin nhan.
   */
  const openConversation = useCallback(
    async (conversationId: string) => {
      if (conversationId === treeRef.current.conversationId) {
        return;
      }
      draftConversationRef.current = null;
      closeStream();
      setRunning(null);
      setConnection(null);
      setUsage(null);
      setError(null);
      await open(conversationId);
    },
    [closeStream, open],
  );

  /** T-3.3 — hoi thoai dang mo vua bi xoa: khong con gi de hien. */
  const changeConversationModel = useCallback(
    async (modelId: string): Promise<void> => {
      const conversationId = treeRef.current.conversationId;
      if (conversationId === null) {
        /*
          T-S.19c — man nhap: model cua endpoint tu nhap khong lam mac dinh tai
          khoan duoc (`PUT /settings` chi nhan catalog), nen no giu O DAY toi
          luc `send` tao hoi thoai voi `default_model` cua no. Model catalog thi
          tang tai khoan da giu — xoa cho nay de no khong de len tang ay.
        */
        setConversationModel(isEndpointModel(modelId) ? modelId : null);
        return;
      }
      /*
        `PATCH` tra ve ca duong di (`ConversationDetail`), nen khong goi them
        mot `GET` nao — cung ly le da dung o `switchBranch`. Doc
        `default_model` TU RESPONSE chu khong tu `modelId` vua gui: server
        la noi quyet dinh.
      */
      const detail = await api.updateConversation(conversationId, { default_model: modelId });
      setConversationModel(detail.default_model);
      updateTree((prev) => loadConversation(prev, detail));
    },
    [updateTree],
  );

  /**
   * §7.2 ① — tao message roi mo stream. KHONG sinh mot chu nao o day (A1).
   *
   * `keys` di VAO chu khong duoc sinh o day (C22, T-3.4): mot khoa sinh tai
   * cho la mot khoa moi cho moi lan thu lai, va khi ay middleware §11.4 vo
   * dung — dung cai bay ma C22 ta. Chu so huu khoa la `Composer`, vi don vi
   * cua C22 la "lan soan thao" chu khong "loi goi HTTP".
   *
   * T-S.10 — o man nhap day la HAI buoc; xem khoi "Hoi thoai NHAP" o docstring
   * module.
   */
  const send = useCallback(
    async (newContent: string, keys: SendKeys, attachmentIds: readonly string[] = []): Promise<SendResult> => {
      const fromDraft = treeRef.current.conversationId === null;
      setBusy(true);
      try {
        let conversationId = treeRef.current.conversationId ?? draftConversationRef.current;
        if (conversationId === null) {
          const created = await api.createConversation(
            effectiveModel === null ? {} : { default_model: effectiveModel },
            keys.conversation,
          );
          conversationId = created.id;
          // Truoc buoc 2: buoc 2 hong thi lan thu lai doc lai dung id nay.
          draftConversationRef.current = conversationId;
        }
        const output = await api.sendMessage(
          conversationId,
          {
            content: newContent,
            // C14 — la CLIENT dang thay, khong de server tu lay. Man nhap:
            // cay rong, tuc `null` — cau dau la goc.
            parent_id: treeRef.current.activeLeafId,
            model_id: effectiveModel,
            // T-S.14 — dung muc dang hien tren picker (§24.2b·S4: body thang).
            // Model khong co muc ⇒ vang mat: mot `id` bat ky se la `400`.
            ...(effort === null ? {} : { reasoning_effort: effort }),
            // T-4.7 — vang mat khi khong co tep: body cu giu nguyen tung byte.
            ...(attachmentIds.length === 0 ? {} : { attachment_ids: [...attachmentIds] }),
          },
          keys.message,
        );
        if (output.branched) {
          setError("da mo mot nhanh moi (parent_id khac la hien tai) — C14");
        }
        if (fromDraft) {
          draftConversationRef.current = null;
          /*
            Dat id vao cay TRUOC khi mo stream: `loadConversation` don sach
            `inFlight` khi id hoi thoai doi, nen mot cay con `null` luc `start`
            va vai `delta` dau toi se lam mat dung phan mo dau cua cau tra loi
            ngay khi `GET` duoi day ve.
          */
          const id = conversationId;
          updateTree(() => ({ ...emptyTree(), conversationId: id }));
          // CUNG luot render voi id cua cay: sidebar thay "mo mot id la" va
          // "id nay vua ra doi" mot lan, nap lai danh sach mot lan.
          setCreatedConversationId(id);
          writeConversationParam(id);
        }
        reportQuotaWarning(output.quota_warning);
        openStreamFor(output.stream_url, output.assistant_message_id, conversationId);
        await reload(conversationId);
        return "da-gui";
      } catch (e) {
        setError(errorText(e));
        reportQuotaError(e);
        // `IN_PROGRESS` (khoa dang bi giu) chu khong `GENERATION_IN_PROGRESS`
        // (message dang sinh) — hai ma, xem `ERROR_CODES`.
        return e instanceof ApiError && e.code === ERROR_CODES.KEY_IN_USE ? "ket-khoa" : "hong";
      } finally {
        setBusy(false);
      }
    },
    [reportQuotaWarning, reportQuotaError, reload, effectiveModel, effort, openStreamFor, updateTree],
  );

  /**
   * §7.5 — bao server dung, KHONG dong `EventSource`.
   *
   * Worker van phat `done` (kem `finish_reason='cancelled'`) va van ghi phan
   * da sinh xuong Postgres. Dong stream o day la vut mat ca hai.
   */
  const stop = useCallback(async () => {
    if (running === null) {
      return;
    }
    try {
      await api.cancel(running);
    } catch (e) {
      setError(errorText(e));
    }
  }, [running]);

  /**
   * §8.2 — mot anh em moi cho cung mot cau hoi. Xem khoi C22 o docstring module.
   *
   * T-S.15 (§24.2b·S4, NQ-118) — **MOT nut Thu lai**, gui model **va** muc dang
   * chon tren picker: dung hai gia tri `send` dat vao lan gui, nen thu nguoi
   * dung thay tren picker la thu duoc sinh. Ban T-3.7 co hai nut va nut tron
   * co y KHONG gui model (giu model cu); nay "doi model & thu lai" la "doi tren
   * picker roi bam Thu lai" (UC-02 dong 5), va tooltip cua nut noi dieu ay.
   *
   * Model khong co khoi `reasoning` ⇒ `reasoning_effort` vang mat — mot `id`
   * bat ky la `400 REASONING_UNSUPPORTED` (cung luat `send`). Chua biet model
   * nao (`GET /models` chua ve) ⇒ body rong, backend giu model cu.
   */
  const retry = useCallback(
    async (messageId: string) => {
      const conversationId = treeRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      // Mot bo (message, model, muc) = mot y dinh = mot khoa. Hai lan bam nhanh
      // doc cung gia tri nay vi no la `ref` chu khong `state` (cai bay S5).
      const identity = `${messageId}:${effectiveModel ?? ""}:${effort ?? ""}`;
      const key = retryKeysRef.current.get(identity) ?? newKey();
      retryKeysRef.current.set(identity, key);
      setBusy(true);
      try {
        const output = await api.retry(
          messageId,
          {
            ...(effectiveModel === null ? {} : { model_id: effectiveModel }),
            ...(effort === null ? {} : { reasoning_effort: effort }),
          },
          key,
        );
        // Luat 3 cua C22: bo khoa KHI VA CHI KHI `202` ve. Lan bam sau tren
        // cung cau tra loi la mot y dinh moi, tuc mot anh em that.
        retryKeysRef.current.delete(identity);
        reportQuotaWarning(output.quota_warning);
        openStreamFor(output.stream_url, output.assistant_message_id, conversationId);
        await reload(conversationId);
      } catch (e) {
        // Luat 2: GIU khoa. Mang rot hay `503` thi lan bam sau van la cung
        // mot y dinh, va §11.4 chi lam viec duoc khi hai lan ay cung khoa.
        setError(errorText(e));
        reportQuotaError(e);
      } finally {
        setBusy(false);
      }
    },
    [reportQuotaWarning, reportQuotaError, reload, openStreamFor, effectiveModel, effort],
  );

  /**
   * §18.2 — ghi Like/Dislike roi DOC LAI duong di tu server.
   *
   * Doc lai chu khong tu va `feedback` vao node dang co trong state: "Viec"
   * dong 3 cua T-3.7 doi hai nut ve tu `feedback` cua `MessageOut` chu khong tu
   * mot ban rieng o FE, va cach re nhat de dieu do dung mai la khong bao gio
   * co ban thu hai de lech. Cung luat 1 cua hook nay, ap cho mot truong thay
   * vi cho hinh dang cay.
   *
   * `null` = go danh gia (bam Like lan thu hai). Endpoint idempotent theo
   * message nen bam bao nhieu lan cung ra mot hang.
   */
  const sendFeedback = useCallback(
    async (messageId: string, value: Feedback | null) => {
      const conversationId = treeRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      try {
        await api.sendFeedback(messageId, value);
        await reload(conversationId);
      } catch (e) {
        setError(errorText(e));
      }
    },
    [reload],
  );

  const editQuestion = useCallback(
    async (messageId: string, newContent: string) => {
      const conversationId = treeRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      setBusy(true);
      try {
        const output = await api.editQuestion(messageId, newContent);
        reportQuotaWarning(output.quota_warning);
        openStreamFor(output.stream_url, output.assistant_message_id, conversationId);
        await reload(conversationId);
      } catch (e) {
        setError(errorText(e));
        reportQuotaError(e);
      } finally {
        setBusy(false);
      }
    },
    [reportQuotaWarning, reportQuotaError, reload, openStreamFor],
  );

  /**
   * §8.2 — `‹ 2/3 ›`: doc anh em, roi `PATCH` dat `active_leaf_id`. Khong xoa gi.
   *
   * Hai request chu khong mot, va do la co y: `GET siblings` la nguon duy nhat
   * biet id cua anh em ke ben (C13 cam FE tu dem). `PATCH` tra ve LUON duong
   * di moi nen khong can `GET` lan ba.
   */
  const switchBranch = useCallback(
    async (node: MessageOut, direction: -1 | 1) => {
      const conversationId = treeRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      setBusy(true);
      try {
        const siblings = await api.siblings(node.id);
        const target = adjacentSiblingId(siblings, direction);
        if (target === null) {
          return;
        }
        // NQ-35: gui dung id anh em. Khi nga (a) cua B-109 co mat, server tu di
        // tiep xuong la sau nhat cua nhanh nay va dong nay khong phai sua.
        const detail = await api.updateConversation(conversationId, { active_leaf_id: target });
        closeStream();
        setRunning(null);
        setConnection(null);
        ensureStream(updateTree((prev) => loadConversation(prev, detail)));
      } catch (e) {
        setError(errorText(e));
      } finally {
        setBusy(false);
      }
    },
    [ensureStream, updateTree, closeStream],
  );

  return {
    tree,
    phase: tree.conversationId !== null || opening ? "conversation" : "draft",
    draftEpoch,
    createdConversationId,
    conversationModel,
    defaultPick,
    effectiveModel,
    effectiveEffort: effort,
    connection,
    running,
    busy,
    usage,
    notes,
    artifactsOf,
    error,
    changeConversationModel,
    newConversation: leaveConversation,
    openConversation,
    closeConversation: leaveConversation,
    send,
    stop,
    retry,
    sendFeedback,
    editQuestion,
    switchBranch,
    showError: setError,
    clearError: () => setError(null),
  };
}
