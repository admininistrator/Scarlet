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
 * **3. Mot luc chi mot `EventSource` cho moi tab.** `moStreamCho` dong cai cu
 * truoc khi mo cai moi — khong phai de tiet kiem ket noi ma vi hai stream cua
 * cung mot message se cung noi chu vao mot cho. (Hai TAB thi khac: moi tab mot
 * cursor rieng, va §7.4/C7 doi ca hai cung chay.)
 *
 * **5. Delta duoc GOM theo khung hinh, khong day thang vao state** (B-234,
 * quy tac 4 cua ban T-HD3). Xem khoi "GOM DELTA THEO KHUNG HINH" duoi than
 * hook — day la cho duy nhat `noiDelta`/`noiReasoning` duoc goi.
 *
 * **4. Cay giu them o mot `ref`, khong chi trong `useState`.** Ham cap nhat
 * cua React chay luc RENDER chu khong luc goi, nen `setCay(cu => ...)` khong
 * tra lai duoc cay moi cho dong lenh ke tiep — ma `lamTuoi()` phai tra ve cay
 * vua doc de goi thang `baoDamStream()`. Doc tu `ref` cung tranh mot ca stale
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
 * `Composer`; `gui()` nhan no nhu mot tham so va tra ve `KetQuaGui` de chu
 * so huu biet nen giu hay nen bo.
 *
 * ── ...nhung C22 cua `thuLai` thi O DAY (T-3.7 / B-231) ───────────────────
 *
 * NQ-93 dua `POST /messages/{id}/retry` vao danh sach BAT BUOC `Idempotency-Key`,
 * nen nut Thu lai cung phai cam mot khoa. Khoa ay o lai `useChat` chu khong
 * di ra component, va ly do la don vi cua no khac han o nhap:
 *
 *   • Don vi la mot cap **(message, model)** — "thu lai cau tra loi nay bang
 *     model nay". `useChat` la cho duy nhat biet ca hai.
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
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  MA_LOI,
  api,
  type DanhGia,
  type MessageRa,
  type ModelRa,
} from "../../lib/api";
import { khoaMoi } from "../../lib/idempotency";
import { chonMacDinh, type KetQuaMacDinh } from "../models/macDinh";
import { moStream, type TayCamStream, type TrangThaiKetNoi, type UsageRa } from "../../lib/sse";
import {
  batDauSinh,
  canStream,
  cayRong,
  idAnhEmKe,
  napHoiThoai,
  noiDelta,
  noiReasoning,
  type TrangThaiCay,
} from "../../lib/tree";

/** Tham so URL giu hoi thoai dang mo — de F5 quay lai dung cho (M3). */
const THAM_SO_HOI_THOAI = "c";

function docThamSoHoiThoai(): string | null {
  return new URLSearchParams(window.location.search).get(THAM_SO_HOI_THOAI);
}

function ghiThamSoHoiThoai(id: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set(THAM_SO_HOI_THOAI, id);
  window.history.replaceState(null, "", url);
}

/** T-3.3 — hoi thoai vua bi xoa thi `?c=` cua no khong duoc song sot qua F5. */
function xoaThamSoHoiThoai(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete(THAM_SO_HOI_THOAI);
  window.history.replaceState(null, "", url);
}

function loiThanhChu(loi: unknown): string {
  if (loi instanceof ApiError) {
    return `${loi.code}: ${loi.message}`;
  }
  return loi instanceof Error ? loi.message : String(loi);
}

/**
 * Ba ket cuc cua mot lan bam Gui — T-3.4.
 *
 * `gui()` tra ve thay vi chi `setLoi()`, vi tu T-3.4 **khoa `Idempotency-Key`
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
export type KetQuaGui = "da-gui" | "ket-khoa" | "hong";

export interface ChatDangDung {
  cay: TrangThaiCay;
  /**
   * T-3.6 — TANG 1 cua ba tang mac dinh: `conversations.default_model` cua
   * hoi thoai dang mo. `null` = hoi thoai nay khong dat gi, hoac chua mo
   * hoi thoai nao.
   *
   * Doc tu server o moi lan `lamTuoi()`, khong giu mot ban rieng: no la mot
   * cot cua hang `conversations` va `PATCH` tra ve ca hang ay.
   */
  modelHoiThoai: string | null;
  /**
   * Ket qua day du cua `chonMacDinh()` tren ba tang: model dang dung, tang
   * da quyet dinh no, va id hop le cua tung tang.
   *
   * Tinh MOT lan o day chu khong de moi ben tu tinh: `ModelPicker` ve rail
   * va chip tu chinh phep chon ma `gui()` dung de dat `model_id`, nen hai
   * phep chon roi nhau la mot man hinh chi vao model nay va mot request gui
   * di model khac.
   */
  macDinh: KetQuaMacDinh;
  /**
   * Loi tat cua `macDinh.modelId` — model cho lan GUI ke tiep.
   *
   * Tu T-3.7 no **khong** con di kem moi lan `thuLai`: hai nut Thu lai canh
   * nhau chi khac nhau o cho ay, nen nut tron giu model cu con nut "Doi model
   * & thu lai" truyen `modelId` tuong minh. Gia tri nay van la thu nut thu hai
   * gui di — no la model dang chon tren picker.
   */
  modelHieuLuc: string | null;
  /** `null` = khong co stream nao dang mo trong tab nay. */
  ketNoi: TrangThaiKetNoi | null;
  /** Id message assistant dang chay, hoac `null`. */
  dangChay: string | null;
  dangBan: boolean;
  usage: UsageRa | null;
  /** Chip cua `tool_call`/`tool_result`/`artifact`, theo `message_id`. */
  ghiChu: Record<string, string[]>;
  loi: string | null;

  /**
   * T-3.6 — ghi TANG 1 (`PATCH /conversations/{id}` `{default_model}`).
   *
   * Khong lam gi khi chua mo hoi thoai nao: luc do chi con tang tai khoan,
   * va no thuoc ve `usePhien` chu khong ve day.
   */
  datModelHoiThoai: (modelId: string) => Promise<void>;
  hoiThoaiMoi: () => Promise<void>;
  /** T-3.3 — sidebar chon mot hoi thoai da co. */
  moHoiThoai: (conversationId: string) => Promise<void>;
  /** T-3.3 — hoi thoai dang mo vua bi xoa: roi khoi no, khong mo cai nao. */
  dongHoiThoai: () => void;
  /** `khoa` do NGUOI GOI cam (C22) — xem `KetQuaGui`. */
  gui: (noiDung: string, khoa: string) => Promise<KetQuaGui>;
  dung: () => Promise<void>;
  /**
   * §8.2 — sinh lai cau tra loi `messageId` thanh mot anh em cua no.
   *
   * `modelId` vang mat (nut "Thu lai" tron) ⇒ **khong** gui `model_id`, va
   * backend dung lai dung model cua chinh cau tra loi ay (`_chon_model`).
   * Truyen mot id (nut "Doi model & thu lai") la cho duy nhat doi model.
   *
   * Khoa §11.4 khong o chu ky nay: xem khoi C22 o docstring module.
   */
  thuLai: (messageId: string, modelId?: string) => Promise<void>;
  /**
   * §18.2 — Like/Dislike. `gia === null` la **go** danh gia (bam lai lan hai).
   *
   * Khong nhan `lyDo`: ban T-HD3 chi co hai nut sang/toi, khong co o nhap ly
   * do — va mot ly do gui len hom nay khong doc lai duoc o dau (B-244).
   * `api.danhGia` van mo duong cho no.
   */
  danhGia: (messageId: string, gia: DanhGia | null) => Promise<void>;
  suaCauHoi: (messageId: string, noiDung: string) => Promise<void>;
  chuyenNhanh: (node: MessageRa, huong: -1 | 1) => Promise<void>;
  /** Dat mot cau loi len bang loi cua man chat (T-3.6 — xem `ChatScreen`). */
  datLoi: (chu: string) => void;
  xoaLoi: () => void;
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
export interface TuyChonChat {
  /** Danh sach cua `GET /models` — xem `useModels()`. */
  models: ModelRa[];
  /** TANG 2: `users.default_model` tu `GET /auth/me`. */
  modelMacDinhTaiKhoan: string | null;
}

/**
 * Mac dinh cho ban goi `useChat()` khong tham so (bo test cua T-3.4 va moi
 * man hinh khong co picker). Hang so o TAM MODULE chu khong mot object
 * literal trong chu ky ham: mot literal se la mot object MOI moi lan render,
 * tuc moi `useCallback` phu thuoc vao no deu dung lai o moi khung hinh.
 */
const TUY_CHON_RONG: TuyChonChat = { models: [], modelMacDinhTaiKhoan: null };

export function useChat(tuyChon: TuyChonChat = TUY_CHON_RONG): ChatDangDung {
  const { models, modelMacDinhTaiKhoan } = tuyChon;
  const [cay, setCay] = useState<TrangThaiCay>(cayRong);
  const [modelHoiThoai, setModelHoiThoai] = useState<string | null>(null);
  const [ketNoi, setKetNoi] = useState<TrangThaiKetNoi | null>(null);
  const [dangChay, setDangChay] = useState<string | null>(null);
  const [dangBan, setDangBan] = useState(false);
  const [usage, setUsage] = useState<UsageRa | null>(null);
  const [ghiChu, setGhiChu] = useState<Record<string, string[]>>({});
  const [loi, setLoi] = useState<string | null>(null);

  /*
    Ba tang, mot phep chon, mot cho (T-3.6). `chonMacDinh` la ham THUAN nen
    khong can `useMemo`: no duyet mot mang bon phan tu.

    Day cung la cho Cam bay ① duoc dong cho CA hai tang tren: mot
    `default_model` tro vao model da bien mat khoi catalog bi bo qua va roi
    xuong tang duoi, thay vi tro thanh mot `model_id` gay `400 MODEL_UNKNOWN`
    o lan gui ke tiep.
  */
  const macDinh = chonMacDinh(models, {
    hoiThoai: modelHoiThoai,
    taiKhoan: modelMacDinhTaiKhoan,
  });
  const modelHieuLuc = macDinh.modelId;

  //: Luat 4 — ban doc duoc ngay cua cung mot cay.
  const cayRef = useRef<TrangThaiCay>(cayRong());
  const streamRef = useRef<TayCamStream | null>(null);
  /*
    C22 cho nut Thu lai (B-231): `${messageId}:${modelId}` → khoa §11.4.

    `Map` chu khong mot chuoi duy nhat: hai bong bong khac nhau tren cung mot
    man hinh la hai y dinh khac nhau, va hai nut cua CUNG mot bong bong ("Thu
    lai" va "Doi model & thu lai") cung vay — dung chung mot khoa se lam nut
    thu hai nhan lai ban phat lai cua nut thu nhat, tuc doi model khong co tac
    dung gi.

    `ref` chu khong `state`: hai lan bam trong cung mot luot render phai doc
    duoc CUNG mot gia tri (cai bay S5, y het `khoaRef` cua `Composer`).

    Muc chi bi xoa khi `202` ve, nen mot lan hong se de lai mot muc song het
    doi hook. Do la co y (luat 2 cua C22) va no khong phai mot cho ro: so muc
    bi chan boi so bong bong nguoi dung da bam nham, khong boi thoi gian.
  */
  const khoaThuLaiRef = useRef<Map<string, string>>(new Map());

  const datCay = useCallback((doi: (cu: TrangThaiCay) => TrangThaiCay): TrangThaiCay => {
    const moi = doi(cayRef.current);
    cayRef.current = moi;
    setCay(moi);
    return moi;
  }, []);

  const themGhiChu = useCallback((messageId: string, chu: string) => {
    setGhiChu((cu) => ({ ...cu, [messageId]: [...(cu[messageId] ?? []), chu] }));
  }, []);

  // ╔══════════════════════════════════════════════════════════════════════╗
  // ║  GOM DELTA THEO KHUNG HINH — B-234, quy tac 4 cua ban T-HD3          ║
  // ╚══════════════════════════════════════════════════════════════════════╝
  //
  // T-1.14 do duoc **309 delta trong 3,768 giay**, khoang cach lon nhat giua
  // hai manh la 22 ms. Day thang moi manh vao `setCay` nghia la 309 lan React
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
  //      Sau `done` la `lamTuoi()`, va mot manh xa muon hon no se noi them
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
    // Thay bang Map moi TRUOC khi dung: `datCay` goi `setCay`, va mot manh
    // den giua chung phai roi vao lo hang sau chu khong vao lo dang xa.
    pendingRef.current = new Map();
    datCay((c) => {
      let moi = c;
      for (const [messageId, manh] of pending) {
        if (manh.content !== "") {
          moi = noiDelta(moi, messageId, manh.content);
        }
        if (manh.reasoning !== "") {
          moi = noiReasoning(moi, messageId, manh.reasoning);
        }
      }
      return moi;
    });
  }, [datCay]);

  const queueDelta = useCallback(
    (messageId: string, field: "content" | "reasoning", manh: string) => {
      const cu = pendingRef.current.get(messageId) ?? { content: "", reasoning: "" };
      pendingRef.current.set(messageId, { ...cu, [field]: cu[field] + manh });
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
   * `onSuKien` chu khong o day.
   */
  const dongStream = useCallback(() => {
    flushDeltas();
    streamRef.current?.dong();
    streamRef.current = null;
  }, [flushDeltas]);

  /** Doc lai duong di tu server — luat 1. Tra ve cay moi de goi tiep. */
  const lamTuoi = useCallback(
    async (conversationId: string): Promise<TrangThaiCay | null> => {
      try {
        const chiTiet = await api.docHoiThoai(conversationId);
        // TANG 1 di cung duong di: `GET /conversations/{id}` tra ca hai, nen
        // khong co mot loi goi rieng nao de hai gia tri lech nhau.
        setModelHoiThoai(chiTiet.default_model);
        return datCay((cu) => napHoiThoai(cu, chiTiet));
      } catch (e) {
        setLoi(loiThanhChu(e));
        return null;
      }
    },
    [datCay],
  );

  const moStreamCho = useCallback(
    (url: string, messageId: string, conversationId: string) => {
      // Luat 3: mot tab, mot stream.
      dongStream();
      setDangChay(messageId);
      setUsage(null);

      streamRef.current = moStream({
        url,
        onTrangThai: (trangThai) => {
          setKetNoi(trangThai);
          // Noi lai duoc thi bang loi cua lan dut truoc KHONG duoc o lai tren
          // man hinh: DoD "Offline 5 s roi bat lai" ket thuc bang mot man hinh
          // dang chay, ma mot dong "Failed to fetch" nam yen o do doc y het
          // mot cai hong chua duoc sua (B-115).
          if (trangThai === "dang-chay") {
            setLoi(null);
          }
        },
        onChet: (chu) => {
          // Stream chet giua chung: phan da nhan duoc phai len man hinh, neu
          // khong thi 16 ms cuoi bien mat cung voi ket noi (luat 5, diem 2).
          flushDeltas();
          setLoi(chu);
        },
        onCanhBao: setLoi,
        onSuKien: (suKien) => {
          switch (suKien.event) {
            case "start":
              // Xoa phan cu: `start` nghia la "bat dau tu dau" ke ca khi no
              // den tu duong dung lai bang Postgres (§7.4, diem 4 cua sse.ts).
              // Bo dem phai bi bo TRUOC `batDauSinh`, khong phai xa: mot manh
              // cua lan sinh truoc ma xa sau `start` se noi chu cu vao sau
              // chu moi (luat 5, diem 1).
              pendingRef.current.delete(suKien.data.message_id);
              datCay((c) => batDauSinh(c, suKien.data.message_id));
              break;
            case "delta":
              queueDelta(messageId, "content", suKien.data.t);
              break;
            case "reasoning":
              queueDelta(messageId, "reasoning", suKien.data.t);
              break;
            case "tool_call":
              themGhiChu(messageId, `tool_call ${suKien.data.name}`);
              break;
            case "tool_result":
              themGhiChu(
                messageId,
                `tool_result ${suKien.data.name} ${suKien.data.ok ? "ok" : "loi"}`,
              );
              break;
            case "artifact":
              themGhiChu(messageId, `artifact ${suKien.data.artifact_id} v${suKien.data.version}`);
              break;
            case "usage":
              setUsage(suKien.data);
              break;
            case "done":
              // Xa TRUOC `lamTuoi()`: mot manh xa muon hon no se noi them chu
              // vao mot message da khep (luat 5, diem 2).
              flushDeltas();
              if (suKien.data.usage !== null) {
                setUsage(suKien.data.usage);
              }
              setDangChay(null);
              void lamTuoi(conversationId);
              break;
            case "error":
              flushDeltas();
              setLoi(`${suKien.data.code}: ${suKien.data.message}`);
              setDangChay(null);
              void lamTuoi(conversationId);
              break;
          }
        },
      });
    },
    [datCay, dongStream, flushDeltas, lamTuoi, queueDelta, themGhiChu],
  );

  /**
   * Mo stream neu la cuoi con `queued`/`streaming`.
   *
   * Day la toan bo phan "F5 giua luc stream" (M3) va "dong tab, mo lai sau 30
   * giay": khong co gi luu o client, cau tra loi nam trong Postgres va Redis.
   */
  const baoDamStream = useCallback(
    (cayMoi: TrangThaiCay) => {
      const node = canStream(cayMoi);
      if (node === null || cayMoi.conversationId === null) {
        return;
      }
      moStreamCho(`/api/v1/messages/${node.id}/stream`, node.id, cayMoi.conversationId);
    },
    [moStreamCho],
  );

  const mo = useCallback(
    async (conversationId: string) => {
      const cayMoi = await lamTuoi(conversationId);
      if (cayMoi !== null) {
        ghiThamSoHoiThoai(conversationId);
        baoDamStream(cayMoi);
      }
    },
    [baoDamStream, lamTuoi],
  );

  /**
   * Hoi thoai ghi trong URL. Goi luc mount, va goi lai khi mang ve.
   *
   * KHONG con nap `/models` o day (T-3.6): danh muc model doi chu — no can
   * mot nut lam moi, mot moc gio, va luat "khong goi lai khi mo dropdown" —
   * nen no co hook rieng (`features/models/useModels.ts`). Hai thu tung di
   * chung chi vi ca hai cung phai chay luc mount.
   */
  const napBanDau = useCallback(() => {
    const id = docThamSoHoiThoai();
    if (id !== null) {
      void mo(id);
    }
  }, [mo]);

  // ── nap lan dau, va nap LAI neu lan dau roi dung luc mat mang ──
  useEffect(() => {
    napBanDau();

    /**
     * F5 trong luc DevTools con dat Offline thi ca `/models` lan
     * `GET /conversations/{id}` deu nem `Failed to fetch`, va man hinh ket o
     * do voi mot bang loi — khong co duong nao ve tru mot lan F5 nua. Mot lan
     * mat mang khong duoc phep doi mot lan tai trang (B-115).
     *
     * Chi lo phan KHOI DONG: stream dang song thi `sse.ts` tu lo lay phan cua
     * no, dung vao day la mo thua mot ket noi.
     */
    function khiCoMang(): void {
      if (cayRef.current.conversationId === null) {
        napBanDau();
      }
    }

    window.addEventListener("online", khiCoMang);
    return () => {
      window.removeEventListener("online", khiCoMang);
      dongStream();
    };
  }, [dongStream, napBanDau]);

  const hoiThoaiMoi = useCallback(async () => {
    setDangBan(true);
    try {
      dongStream();
      setDangChay(null);
      setKetNoi(null);
      const hoiThoai = await api.taoHoiThoai(
        modelHieuLuc === null ? {} : { default_model: modelHieuLuc },
      );
      await mo(hoiThoai.id);
    } catch (e) {
      setLoi(loiThanhChu(e));
    } finally {
      setDangBan(false);
    }
  }, [dongStream, mo, modelHieuLuc]);

  /**
   * T-3.3 — sidebar chon mot hoi thoai da co.
   *
   * Dong stream cu TRUOC khi mo hoi thoai khac: luat 3 cua file nay cho moi
   * tab mot `EventSource`, va mot stream con song cua hoi thoai truoc se noi
   * chu cua no vao cay vua nap.
   */
  const moHoiThoai = useCallback(
    async (conversationId: string) => {
      if (conversationId === cayRef.current.conversationId) {
        return;
      }
      dongStream();
      setDangChay(null);
      setKetNoi(null);
      setUsage(null);
      setLoi(null);
      await mo(conversationId);
    },
    [dongStream, mo],
  );

  /** T-3.3 — hoi thoai dang mo vua bi xoa: khong con gi de hien. */
  const datModelHoiThoai = useCallback(
    async (modelId: string): Promise<void> => {
      const conversationId = cayRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      /*
        `PATCH` tra ve ca duong di (`HoiThoaiChiTiet`), nen khong goi them
        mot `GET` nao — cung ly le da dung o `chuyenNhanh`. Doc
        `default_model` TU RESPONSE chu khong tu `modelId` vua gui: server
        la noi quyet dinh.
      */
      const chiTiet = await api.suaHoiThoai(conversationId, { default_model: modelId });
      setModelHoiThoai(chiTiet.default_model);
      datCay((cu) => napHoiThoai(cu, chiTiet));
    },
    [datCay],
  );

  const dongHoiThoai = useCallback(() => {
    dongStream();
    setDangChay(null);
    setKetNoi(null);
    setUsage(null);
    setLoi(null);
    setModelHoiThoai(null);
    datCay(() => cayRong());
    xoaThamSoHoiThoai();
  }, [datCay, dongStream]);

  /**
   * §7.2 ① — tao message roi mo stream. KHONG sinh mot chu nao o day (A1).
   *
   * `khoa` di VAO chu khong duoc sinh o day (C22, T-3.4): mot khoa sinh tai
   * cho la mot khoa moi cho moi lan thu lai, va khi ay middleware §11.4 vo
   * dung — dung cai bay ma C22 ta. Chu so huu khoa la `Composer`, vi don vi
   * cua C22 la "lan soan thao" chu khong "loi goi HTTP".
   */
  const gui = useCallback(
    async (noiDungMoi: string, khoa: string): Promise<KetQuaGui> => {
      const conversationId = cayRef.current.conversationId;
      if (conversationId === null) {
        setLoi("chua co hoi thoai nao dang mo");
        return "hong";
      }
      setDangBan(true);
      try {
        const ra = await api.guiTinNhan(
          conversationId,
          {
            content: noiDungMoi,
            // C14 — la CLIENT dang thay, khong de server tu lay.
            parent_id: cayRef.current.activeLeafId,
            model_id: modelHieuLuc,
          },
          khoa,
        );
        if (ra.branched) {
          setLoi("da mo mot nhanh moi (parent_id khac la hien tai) — C14");
        }
        moStreamCho(ra.stream_url, ra.assistant_message_id, conversationId);
        await lamTuoi(conversationId);
        return "da-gui";
      } catch (e) {
        setLoi(loiThanhChu(e));
        // `IN_PROGRESS` (khoa dang bi giu) chu khong `GENERATION_IN_PROGRESS`
        // (message dang sinh) — hai ma, xem `MA_LOI`.
        return e instanceof ApiError && e.code === MA_LOI.KHOA_DANG_GIU ? "ket-khoa" : "hong";
      } finally {
        setDangBan(false);
      }
    },
    [lamTuoi, modelHieuLuc, moStreamCho],
  );

  /**
   * §7.5 — bao server dung, KHONG dong `EventSource`.
   *
   * Worker van phat `done` (kem `finish_reason='cancelled'`) va van ghi phan
   * da sinh xuong Postgres. Dong stream o day la vut mat ca hai.
   */
  const dung = useCallback(async () => {
    if (dangChay === null) {
      return;
    }
    try {
      await api.huy(dangChay);
    } catch (e) {
      setLoi(loiThanhChu(e));
    }
  }, [dangChay]);

  /**
   * §8.2 — mot anh em moi cho cung mot cau hoi. Xem khoi C22 o docstring module.
   *
   * **Khong con nhet `modelHieuLuc` vao moi lan thu lai** (ban T-3.6 lam vay).
   * T-3.7 dung HAI nut canh nhau, va chung chi khac nhau o dung diem ay: "Thu
   * lai" giu nguyen model cu, "Doi model & thu lai" moi doi. Gui model dang
   * chon cho ca hai la lam nut thu nhat lang le doi model — dung thu
   * `_chon_model` cua backend viet ro la khong duoc ("bam Retry ma khong chon
   * gi phai sinh lai bang dung model cu").
   */
  const thuLai = useCallback(
    async (messageId: string, modelId?: string) => {
      const conversationId = cayRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      // Mot cap (message, model) = mot y dinh = mot khoa. Hai lan bam nhanh
      // doc cung gia tri nay vi no la `ref` chu khong `state` (cai bay S5).
      const dinhDanh = `${messageId}:${modelId ?? ""}`;
      const khoa = khoaThuLaiRef.current.get(dinhDanh) ?? khoaMoi();
      khoaThuLaiRef.current.set(dinhDanh, khoa);
      setDangBan(true);
      try {
        const ra = await api.thuLai(
          messageId,
          modelId === undefined ? {} : { model_id: modelId },
          khoa,
        );
        // Luat 3 cua C22: bo khoa KHI VA CHI KHI `202` ve. Lan bam sau tren
        // cung cau tra loi la mot y dinh moi, tuc mot anh em that.
        khoaThuLaiRef.current.delete(dinhDanh);
        moStreamCho(ra.stream_url, ra.assistant_message_id, conversationId);
        await lamTuoi(conversationId);
      } catch (e) {
        // Luat 2: GIU khoa. Mang rot hay `503` thi lan bam sau van la cung
        // mot y dinh, va §11.4 chi lam viec duoc khi hai lan ay cung khoa.
        setLoi(loiThanhChu(e));
      } finally {
        setDangBan(false);
      }
    },
    [lamTuoi, moStreamCho],
  );

  /**
   * §18.2 — ghi Like/Dislike roi DOC LAI duong di tu server.
   *
   * Doc lai chu khong tu va `feedback` vao node dang co trong state: "Viec"
   * dong 3 cua T-3.7 doi hai nut ve tu `feedback` cua `MessageRa` chu khong tu
   * mot ban rieng o FE, va cach re nhat de dieu do dung mai la khong bao gio
   * co ban thu hai de lech. Cung luat 1 cua hook nay, ap cho mot truong thay
   * vi cho hinh dang cay.
   *
   * `null` = go danh gia (bam Like lan thu hai). Endpoint idempotent theo
   * message nen bam bao nhieu lan cung ra mot hang.
   */
  const danhGia = useCallback(
    async (messageId: string, gia: DanhGia | null) => {
      const conversationId = cayRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      try {
        await api.danhGia(messageId, gia);
        await lamTuoi(conversationId);
      } catch (e) {
        setLoi(loiThanhChu(e));
      }
    },
    [lamTuoi],
  );

  const suaCauHoi = useCallback(
    async (messageId: string, noiDungMoi: string) => {
      const conversationId = cayRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      setDangBan(true);
      try {
        const ra = await api.suaCauHoi(messageId, noiDungMoi);
        moStreamCho(ra.stream_url, ra.assistant_message_id, conversationId);
        await lamTuoi(conversationId);
      } catch (e) {
        setLoi(loiThanhChu(e));
      } finally {
        setDangBan(false);
      }
    },
    [lamTuoi, moStreamCho],
  );

  /**
   * §8.2 — `‹ 2/3 ›`: doc anh em, roi `PATCH` dat `active_leaf_id`. Khong xoa gi.
   *
   * Hai request chu khong mot, va do la co y: `GET siblings` la nguon duy nhat
   * biet id cua anh em ke ben (C13 cam FE tu dem). `PATCH` tra ve LUON duong
   * di moi nen khong can `GET` lan ba.
   */
  const chuyenNhanh = useCallback(
    async (node: MessageRa, huong: -1 | 1) => {
      const conversationId = cayRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      setDangBan(true);
      try {
        const anhEm = await api.anhEm(node.id);
        const dich = idAnhEmKe(anhEm, huong);
        if (dich === null) {
          return;
        }
        // NQ-35: gui dung id anh em. Khi nga (a) cua B-109 co mat, server tu di
        // tiep xuong la sau nhat cua nhanh nay va dong nay khong phai sua.
        const chiTiet = await api.suaHoiThoai(conversationId, { active_leaf_id: dich });
        dongStream();
        setDangChay(null);
        setKetNoi(null);
        baoDamStream(datCay((cu) => napHoiThoai(cu, chiTiet)));
      } catch (e) {
        setLoi(loiThanhChu(e));
      } finally {
        setDangBan(false);
      }
    },
    [baoDamStream, datCay, dongStream],
  );

  return {
    cay,
    modelHoiThoai,
    macDinh,
    modelHieuLuc,
    ketNoi,
    dangChay,
    dangBan,
    usage,
    ghiChu,
    loi,
    datModelHoiThoai,
    hoiThoaiMoi,
    moHoiThoai,
    dongHoiThoai,
    gui,
    dung,
    thuLai,
    danhGia,
    suaCauHoi,
    chuyenNhanh,
    datLoi: setLoi,
    xoaLoi: () => setLoi(null),
  };
}
