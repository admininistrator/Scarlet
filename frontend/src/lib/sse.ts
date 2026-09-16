/**
 * Dau doc SSE cua FE — §7 phia client (§23 ghi dung mot dong: `sse.ts` = §7).
 *
 * KH tham chieu: §7.2 ②, §7.4, Phu luc F, C1, C6 · tasks.md T-1.14.
 *
 * File nay KHONG biet React, khong biet cay message, khong biet hoi thoai nao.
 * No nhan mot URL va tra lai mot dong su kien da go kieu. Nho vay cai kho cua
 * §7 — cursor, reconnect, chin loai event — kiem duoc ma khong phai dung mot
 * component nao.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  BON DIEU DE SAI, VA CA BON DEU SAI TRONG IM LANG                      ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * **1. `error` la HAI chuyen khac han nhau, tren cung mot ten.**
 * `es.addEventListener("error", ...)` bat ca (a) `event: error` do server gui
 * theo §7.4 — mot loi CO MA, luot sinh da chet — lan (b) su kien `error` cua
 * chinh `EventSource` khi duong truyen dut. Phu luc F viet ca hai dong do canh
 * nhau ma khong noi chung dung chung mot ten. Phan biet bang `data`: ca (a) la
 * `MessageEvent` co `data` dang chuoi, ca (b) khong co. Lam nguoc lai thi mot
 * lan rot mang se hien ra thanh "model bao loi", va nut Retry moc len giua luc
 * cau tra loi van dang chay.
 *
 * **2. KHONG dong khi dut duong truyen** (dung chu cua task) — de trinh duyet
 * tu reconnect voi `Last-Event-ID`. Nhung `readyState === CLOSED` la chuyen
 * khac: trinh duyet DA BO CUOC (response khong phai 2xx — 401/404/503 — hoac
 * `Content-Type` sai), va no se KHONG thu lai. Coi ca nay la "dang cho" nghia
 * la treo vinh vien mot con tro nhap nhay. §7.4 cam suy ra "xong" tu im lang;
 * no khong cam phan biet "dang cho" voi "da chet".
 *
 * **3. Reconnect TAY (C6) phai tu mang cursor.** Phu luc F viet "dong va mo
 * lai `EventSource` — `Last-Event-ID` lo phan con lai". Dieu do dung cho lan
 * reconnect do CHINH trinh duyet lam tren cung mot object; mot `new
 * EventSource(...)` thi "last event ID string" cua no khoi tao RONG, nen no
 * khong gui header nao ca va server se phat lai tu dau (§7.2 ② mac dinh
 * cursor `0`) — tuc chu bi LAP, dung trieu chung C3. Vi vay o day tu giu
 * `cursor` va noi vao `?cursor=`. `doc_cursor` phia server doc header TRUOC
 * query, nen khi trinh duyet tu reconnect object moi do thi header (moi hon)
 * van thang cai `?cursor=` (da cu) trong URL — dung nhu no da viet.
 *
 * **4. `start` nghia la "bat dau tu dau", khong phai "noi tiep".** Duong dung
 * lai tu Postgres (T-1.7) cung phat `start` truoc. Nguoi dung file nay phai
 * XOA phan chu da co cua message do khi thay `start`, neu khong thi mot lan F5
 * se noi chong ban phat lai len ban cu.
 */

/** So token — payload cua `usage`. Khoa VANG MAT nghia la provider khong bao. */
export interface UsageRa {
  in: number;
  out: number;
  reasoning?: number;
  cached?: number;
}

/** Chin loai event cua §7.4 / Phu luc F. */
export type SuKienStream =
  | { event: "start"; data: { message_id: string; model_id: string } }
  | { event: "delta"; data: { t: string } }
  | { event: "reasoning"; data: { t: string } }
  | {
      event: "tool_call";
      data: { call_id: string; name: string; args: unknown; args_raw?: string };
    }
  | {
      event: "tool_result";
      data: { call_id: string; name: string; ok: boolean; result: unknown };
    }
  | { event: "artifact"; data: { artifact_id: string; version: number } }
  | { event: "usage"; data: UsageRa }
  | { event: "done"; data: { finish_reason: string | null; usage: UsageRa | null } }
  | { event: "error"; data: { code: string; message: string } };

export type LoaiSuKien = SuKienStream["event"];

/**
 * Tam loai dang ky bang vong lap. `error` KHONG o day — no co mot handler
 * rieng vi ten do dung chung voi su kien dut duong truyen (diem 1).
 */
const LOAI_KHONG_PHAI_LOI = [
  "start",
  "delta",
  "reasoning",
  "tool_call",
  "tool_result",
  "artifact",
  "usage",
  "done",
] as const;

/** Du chin loai — dung cho test va cho nguoi doc dem lai. */
export const MOI_LOAI_SU_KIEN: readonly LoaiSuKien[] = [...LOAI_KHONG_PHAI_LOI, "error"];

/**
 * Trang thai duong day, de man hinh noi dung su that.
 *
 * `dang-noi-lai` khac `dong`: cai dau la trinh duyet dang tu thu lai, cai sau
 * la no da bo cuoc. Gop hai cai vao mot la mat dung thu nguoi dung can biet.
 */
export type TrangThaiKetNoi = "dang-mo" | "dang-chay" | "dang-noi-lai" | "dong";

export interface ThamSoStream {
  /** Duong dan tuong doi, lay nguyen tu `stream_url` cua `202`. */
  url: string;
  onSuKien: (suKien: SuKienStream) => void;
  onTrangThai?: (trangThai: TrangThaiKetNoi) => void;
  /** Trinh duyet bo cuoc (`readyState === CLOSED`) — xem diem 2. */
  onChet?: (lyDo: string) => void;
  /** Khung doc khong duoc. Mac dinh in ra console, khong nuot. */
  onCanhBao?: (lyDo: string) => void;
}

export interface TayCamStream {
  /** Dong han. Go ca listener `visibilitychange`. Goi nhieu lan khong sao. */
  dong: () => void;
  /** Redis Stream ID cuoi cung DA NHAN — de kiem trong DevTools. */
  cursor: () => string;
}

/**
 * Mo mot stream SSE toi mot message va giu no song cho toi `done`/`error`.
 *
 * Hop dong: ham nay KHONG bao gio tu ket luan "xong" tu im lang (§7.4). Chi
 * `done` hoac `error` dong duoc no; moi thu khac chi doi trang thai duong day.
 */
export function moStream(thamSo: ThamSoStream): TayCamStream {
  const canhBao = thamSo.onCanhBao ?? ((lyDo: string) => console.error("[sse]", lyDo));

  let es: EventSource | null = null;
  //: Redis Stream ID cua ban ghi CUOI CUNG DA GIAO CHO NGUOI DUNG (§7.3).
  let cursor = "";
  //: `done`/`error` da toi. Sau day khong reconnect nua du tab co hien lai.
  let daKetThuc = false;

  function baoTrangThai(trangThai: TrangThaiKetNoi): void {
    thamSo.onTrangThai?.(trangThai);
  }

  function dongKetNoi(): void {
    if (es !== null) {
      es.close();
      es = null;
    }
  }

  function nhanKhung(loai: LoaiSuKien, ev: MessageEvent<string>): void {
    // Cap nhat cursor TRUOC khi giao su kien ra ngoai: neu handler nem thi
    // cursor van dung, va lan noi lai sau do khong phat lai khung nay.
    if (ev.lastEventId) {
      cursor = ev.lastEventId;
    }

    let data: unknown;
    try {
      data = JSON.parse(ev.data) as unknown;
    } catch {
      // Mot khung doc khong duoc KHONG phai ly do de ngung doc nhung khung
      // con lai — nhung cung khong duoc bien mat khong dau vet.
      canhBao(`khung ${loai} khong phai JSON: ${ev.data.slice(0, 120)}`);
      return;
    }

    thamSo.onSuKien({ event: loai, data } as SuKienStream);

    if (loai === "done" || loai === "error") {
      daKetThuc = true;
      dongKetNoi();
      baoTrangThai("dong");
    }
  }

  /** Mot ten, hai chuyen — xem diem 1 trong docstring module. */
  function xuLySuKienError(ev: Event): void {
    const khung = ev as MessageEvent<unknown>;
    if (typeof khung.data === "string") {
      nhanKhung("error", khung as MessageEvent<string>);
      return;
    }

    if (es === null || es.readyState === EventSource.CLOSED) {
      // Trinh duyet da bo cuoc va se KHONG thu lai (diem 2).
      dongKetNoi();
      baoTrangThai("dong");
      thamSo.onChet?.("ket noi bi dong han, trinh duyet khong thu lai");
      return;
    }

    // Dut duong truyen. KHONG goi close() — de trinh duyet tu reconnect, no
    // se gui `Last-Event-ID` va server phat tiep tu dung cho (§7.2 ②).
    baoTrangThai("dang-noi-lai");
  }

  function moKetNoi(): void {
    dongKetNoi();
    const url = cursor === "" ? thamSo.url : `${thamSo.url}?cursor=${encodeURIComponent(cursor)}`;
    // `withCredentials` la chu cua Phu luc F, va la duong danh tinh di qua
    // (NQ-33): `EventSource` khong dat duoc header nen cookie la thu duy nhat
    // no mang theo.
    const nguon = new EventSource(url, { withCredentials: true });
    es = nguon;

    nguon.addEventListener("open", () => baoTrangThai("dang-chay"));
    for (const loai of LOAI_KHONG_PHAI_LOI) {
      nguon.addEventListener(loai, (ev) => nhanKhung(loai, ev as MessageEvent<string>));
    }
    nguon.addEventListener("error", xuLySuKienError);

    baoTrangThai("dang-mo");
  }

  /**
   * C6 — iOS Safari dong ket noi nen MA KHONG bao loi: `EventSource` van bao
   * `readyState === OPEN`, chi la khong con chu nao toi. Vi vay moc vao
   * `visibilitychange` chu KHONG vao su kien `error` — su kien do khong bao
   * gio ban.
   *
   * Dong roi mo lai vo dieu kien khi tab hien lai: `cursor` lam cho viec do
   * khong mat va khong lap mot chu nao, nen khong can doan xem ket noi con
   * song hay khong — mot phep doan sai o day la treo man hinh.
   */
  function khiDoiHienThi(): void {
    if (daKetThuc || document.visibilityState !== "visible") {
      return;
    }
    moKetNoi();
  }

  document.addEventListener("visibilitychange", khiDoiHienThi);
  moKetNoi();

  return {
    dong: () => {
      daKetThuc = true;
      document.removeEventListener("visibilitychange", khiDoiHienThi);
      dongKetNoi();
    },
    cursor: () => cursor,
  };
}
