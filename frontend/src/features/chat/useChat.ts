/**
 * Day noi giua `api.ts`, `sse.ts`, `tree.ts` va man chat — T-1.14.
 *
 * KH tham chieu: §7.2, §7.4, §7.5, §8.2, §18.2, C6, C13, C14, C22.
 *
 * Component KHONG goi `fetch` va KHONG dung `EventSource` truc tiep; moi thu
 * do di qua day. Nho vay bon luat duoi day co dung MOT cho de dung.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BON LUAT                                                              ║
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
 * **4. Cay giu them o mot `ref`, khong chi trong `useState`.** Ham cap nhat
 * cua React chay luc RENDER chu khong luc goi, nen `setCay(cu => ...)` khong
 * tra lai duoc cay moi cho dong lenh ke tiep — ma `lamTuoi()` phai tra ve cay
 * vua doc de goi thang `baoDamStream()`. Doc tu `ref` cung tranh mot ca stale
 * closure that: `gui()` can `activeLeafId` MOI NHAT (luat 2), khong phai gia
 * tri cua lan render tao ra no.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  datDanhTinhDev,
  docDanhTinhDev,
  type MessageRa,
  type ModelRa,
} from "../../lib/api";
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

/** `crypto.randomUUID` chi co trong secure context; co duong lui cho http dev. */
function khoaMoi(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

function docThamSoHoiThoai(): string | null {
  return new URLSearchParams(window.location.search).get(THAM_SO_HOI_THOAI);
}

function ghiThamSoHoiThoai(id: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set(THAM_SO_HOI_THOAI, id);
  window.history.replaceState(null, "", url);
}

function loiThanhChu(loi: unknown): string {
  if (loi instanceof ApiError) {
    return `${loi.code}: ${loi.message}`;
  }
  return loi instanceof Error ? loi.message : String(loi);
}

export interface ChatDangDung {
  cay: TrangThaiCay;
  models: ModelRa[];
  modelChon: string | null;
  danhTinh: string | null;
  /** `null` = khong co stream nao dang mo trong tab nay. */
  ketNoi: TrangThaiKetNoi | null;
  /** Id message assistant dang chay, hoac `null`. */
  dangChay: string | null;
  dangBan: boolean;
  usage: UsageRa | null;
  /** Chip cua `tool_call`/`tool_result`/`artifact`, theo `message_id`. */
  ghiChu: Record<string, string[]>;
  loi: string | null;

  datDanhTinh: (userId: string) => void;
  chonModel: (modelId: string | null) => void;
  hoiThoaiMoi: () => Promise<void>;
  gui: (noiDung: string) => Promise<void>;
  dung: () => Promise<void>;
  thuLai: (messageId: string) => Promise<void>;
  suaCauHoi: (messageId: string, noiDung: string) => Promise<void>;
  chuyenNhanh: (node: MessageRa, huong: -1 | 1) => Promise<void>;
  xoaLoi: () => void;
}

export function useChat(): ChatDangDung {
  const [cay, setCay] = useState<TrangThaiCay>(cayRong);
  const [models, setModels] = useState<ModelRa[]>([]);
  const [modelChon, setModelChon] = useState<string | null>(null);
  const [danhTinh, setDanhTinh] = useState<string | null>(null);
  const [ketNoi, setKetNoi] = useState<TrangThaiKetNoi | null>(null);
  const [dangChay, setDangChay] = useState<string | null>(null);
  const [dangBan, setDangBan] = useState(false);
  const [usage, setUsage] = useState<UsageRa | null>(null);
  const [ghiChu, setGhiChu] = useState<Record<string, string[]>>({});
  const [loi, setLoi] = useState<string | null>(null);

  //: Luat 4 — ban doc duoc ngay cua cung mot cay.
  const cayRef = useRef<TrangThaiCay>(cayRong());
  const streamRef = useRef<TayCamStream | null>(null);
  //: C22 — mot thao tac gui cua nguoi dung = MOT khoa, ke ca khi phai thu lai
  //: vi mang rot. Xoa khi da nhan `202`.
  const khoaGuiRef = useRef<string | null>(null);

  const datCay = useCallback((doi: (cu: TrangThaiCay) => TrangThaiCay): TrangThaiCay => {
    const moi = doi(cayRef.current);
    cayRef.current = moi;
    setCay(moi);
    return moi;
  }, []);

  const themGhiChu = useCallback((messageId: string, chu: string) => {
    setGhiChu((cu) => ({ ...cu, [messageId]: [...(cu[messageId] ?? []), chu] }));
  }, []);

  /** Doc lai duong di tu server — luat 1. Tra ve cay moi de goi tiep. */
  const lamTuoi = useCallback(
    async (conversationId: string): Promise<TrangThaiCay | null> => {
      try {
        const chiTiet = await api.docHoiThoai(conversationId);
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
      streamRef.current?.dong();
      setDangChay(messageId);
      setUsage(null);

      streamRef.current = moStream({
        url,
        onTrangThai: setKetNoi,
        onChet: setLoi,
        onCanhBao: setLoi,
        onSuKien: (suKien) => {
          switch (suKien.event) {
            case "start":
              // Xoa phan cu: `start` nghia la "bat dau tu dau" ke ca khi no
              // den tu duong dung lai bang Postgres (§7.4, diem 4 cua sse.ts).
              datCay((c) => batDauSinh(c, suKien.data.message_id));
              break;
            case "delta":
              datCay((c) => noiDelta(c, messageId, suKien.data.t));
              break;
            case "reasoning":
              datCay((c) => noiReasoning(c, messageId, suKien.data.t));
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
              if (suKien.data.usage !== null) {
                setUsage(suKien.data.usage);
              }
              setDangChay(null);
              void lamTuoi(conversationId);
              break;
            case "error":
              setLoi(`${suKien.data.code}: ${suKien.data.message}`);
              setDangChay(null);
              void lamTuoi(conversationId);
              break;
          }
        },
      });
    },
    [datCay, lamTuoi, themGhiChu],
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

  // ── nap lan dau: danh tinh, models, hoi thoai ghi trong URL ──
  useEffect(() => {
    setDanhTinh(docDanhTinhDev());
    api
      .danhSachModel()
      .then(setModels)
      // `/models` khong doi danh tinh, nen that bai o day la ha tang chu khong
      // phai chua dang nhap — noi ro de khong ai di sua nham cho.
      .catch((e: unknown) => setLoi(`khong doc duoc /models — ${loiThanhChu(e)}`));

    const id = docThamSoHoiThoai();
    if (id !== null) {
      void mo(id);
    }
    return () => streamRef.current?.dong();
  }, [mo]);

  const datDanhTinh = useCallback((userId: string) => {
    datDanhTinhDev(userId.trim());
    setDanhTinh(docDanhTinhDev());
    setLoi(null);
  }, []);

  const hoiThoaiMoi = useCallback(async () => {
    setDangBan(true);
    try {
      streamRef.current?.dong();
      setDangChay(null);
      setKetNoi(null);
      const hoiThoai = await api.taoHoiThoai(
        modelChon === null ? {} : { default_model: modelChon },
      );
      await mo(hoiThoai.id);
    } catch (e) {
      setLoi(loiThanhChu(e));
    } finally {
      setDangBan(false);
    }
  }, [mo, modelChon]);

  const gui = useCallback(
    async (noiDungMoi: string) => {
      const conversationId = cayRef.current.conversationId;
      if (conversationId === null) {
        setLoi("chua co hoi thoai nao dang mo");
        return;
      }
      khoaGuiRef.current ??= khoaMoi();
      setDangBan(true);
      try {
        const ra = await api.guiTinNhan(
          conversationId,
          {
            content: noiDungMoi,
            // C14 — la CLIENT dang thay, khong de server tu lay.
            parent_id: cayRef.current.activeLeafId,
            model_id: modelChon,
          },
          khoaGuiRef.current,
        );
        khoaGuiRef.current = null;
        if (ra.branched) {
          setLoi("da mo mot nhanh moi (parent_id khac la hien tai) — C14");
        }
        moStreamCho(ra.stream_url, ra.assistant_message_id, conversationId);
        await lamTuoi(conversationId);
      } catch (e) {
        setLoi(loiThanhChu(e));
      } finally {
        setDangBan(false);
      }
    },
    [lamTuoi, modelChon, moStreamCho],
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

  const thuLai = useCallback(
    async (messageId: string) => {
      const conversationId = cayRef.current.conversationId;
      if (conversationId === null) {
        return;
      }
      setDangBan(true);
      try {
        const ra = await api.thuLai(messageId, modelChon === null ? {} : { model_id: modelChon });
        moStreamCho(ra.stream_url, ra.assistant_message_id, conversationId);
        await lamTuoi(conversationId);
      } catch (e) {
        setLoi(loiThanhChu(e));
      } finally {
        setDangBan(false);
      }
    },
    [lamTuoi, modelChon, moStreamCho],
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
        streamRef.current?.dong();
        setDangChay(null);
        setKetNoi(null);
        baoDamStream(datCay((cu) => napHoiThoai(cu, chiTiet)));
      } catch (e) {
        setLoi(loiThanhChu(e));
      } finally {
        setDangBan(false);
      }
    },
    [baoDamStream, datCay],
  );

  return {
    cay,
    models,
    modelChon,
    danhTinh,
    ketNoi,
    dangChay,
    dangBan,
    usage,
    ghiChu,
    loi,
    datDanhTinh,
    chonModel: setModelChon,
    hoiThoaiMoi,
    gui,
    dung,
    thuLai,
    suaCauHoi,
    chuyenNhanh,
    xoaLoi: () => setLoi(null),
  };
}
