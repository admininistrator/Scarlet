/**
 * Dau doc SSE cua FE — §7 phia client (§23 ghi dung mot dong: `sse.ts` = §7).
 *
 * KH tham chieu: §7.2 ②, §7.4, Phu luc F, C1, C6 · tasks.md T-1.14 · B-115.
 *
 * File nay KHONG biet React, khong biet cay message, khong biet hoi thoai nao.
 * No nhan mot URL va tra lai mot dong su kien da go kieu. Nho vay cai kho cua
 * §7 — cursor, reconnect, chin loai event — kiem duoc ma khong phai dung mot
 * component nao.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  NAM DIEU DE SAI, VA CA NAM DEU SAI TRONG IM LANG                      ║
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
 * **2. `readyState === CLOSED` KHONG co nghia la "khong con gi de lam".**
 * Day la cho ban dau tu viet SAI va DoD cua T-1.14 bat duoc (B-115): DevTools
 * → Offline 5 s, Chrome **fail** ket noi chu khong phai chi dut no, tuc
 * `readyState` thanh `CLOSED` ngay — dung trang thai ma mot response 404/401
 * cung tao ra. Coi CLOSED la "chet han" roi `close()` nghia la khi mang ve thi
 * KHONG CON GI de noi lai, va man hinh dung im vinh vien.
 *
 * Luat dung la: **trinh duyet bo cuoc thi MINH nhan viec**, khong phai minh
 * cung bo cuoc. `CONNECTING` ⇒ de trinh duyet tu thu (no se gui
 * `Last-Event-ID`); `CLOSED` ⇒ tu hen gio mo lai, luy thua co tran, cong mot
 * lan mo NGAY khi su kien `online` bao mang da ve. Chi sau
 * `SO_LAN_THU_TOI_DA` lan lien tiep khong len duoc moi bao `onChet` — va luc
 * do no that su la 404/401 chu khong phai mot lan rot mang.
 *
 * Dieu nay KHONG mau thuan voi "khong tu dong khi `error`" cua task: cai bi
 * cam la **ket thuc** mot luot sinh vi duong truyen, va o day khong luot nao
 * bi ket thuc — chi co mot ket noi TCP duoc thay bang mot ket noi khac, mang
 * theo dung cursor cu.
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
 *
 * **5. Im lang KHONG bao gio la "xong" (§7.4).** Khong co bo dem thoi gian nao
 * trong file nay ket thuc mot luot sinh. Chi `done` va `error` lam duoc viec
 * do; het `SO_LAN_THU_TOI_DA` chi doi trang thai duong day sang `dong` va goi
 * `onChet`, no khong bia ra mot ket cuc cho cau tra loi.
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

/** Cho bao lau truoc lan thu DAU khi trinh duyet bo cuoc (diem 2). */
const CHO_DAU_MS = 1_000;
/** Tran cua luy thua. Lon hon nua thi mot lan mat mang ngan cung phai cho lau. */
const CHO_TOI_DA_MS = 15_000;
/**
 * Bao nhieu lan lien tiep khong len duoc thi thoi.
 *
 * Voi luy thua co tran o tren, tam lan la ~1+2+4+8+15+15+15 ≈ 60 s co gang.
 * Mot lan Offline 5 s cua DoD len lai o lan thu nhat (va thuong la ngay lap
 * tuc, nho su kien `online`); mot message 404 that thi dung sau ~60 s va noi
 * ra — thay vi quay vong mai voi mot con tro nhap nhay.
 */
const SO_LAN_THU_TOI_DA = 8;

/**
 * Trang thai duong day, de man hinh noi dung su that.
 *
 * `dang-noi-lai` khac `dong`: cai dau la "van dang co" (trinh duyet tu thu,
 * hoac minh dang hen gio thu), cai sau la "da thoi". Gop hai cai vao mot la
 * mat dung thu nguoi dung can biet.
 */
export type TrangThaiKetNoi = "dang-mo" | "dang-chay" | "dang-noi-lai" | "dong";

export interface ThamSoStream {
  /** Duong dan tuong doi, lay nguyen tu `stream_url` cua `202`. */
  url: string;
  onSuKien: (suKien: SuKienStream) => void;
  onTrangThai?: (trangThai: TrangThaiKetNoi) => void;
  /** Da thu het `SO_LAN_THU_TOI_DA` lan ma khong len — xem diem 2. */
  onChet?: (lyDo: string) => void;
  /** Khung doc khong duoc. Mac dinh in ra console, khong nuot. */
  onCanhBao?: (lyDo: string) => void;
}

export interface TayCamStream {
  /** Dong han. Go het listener va hen gio. Goi nhieu lan khong sao. */
  dong: () => void;
  /** Redis Stream ID cuoi cung DA NHAN — de kiem trong DevTools. */
  cursor: () => string;
}

/**
 * Mo mot stream SSE toi mot message va giu no song cho toi `done`/`error`.
 *
 * Hop dong: ham nay KHONG bao gio tu ket luan "xong" tu im lang (§7.4). Chi
 * `done` hoac `error` dong duoc mot luot sinh; moi thu khac chi doi trang thai
 * duong day.
 */
export function moStream(thamSo: ThamSoStream): TayCamStream {
  const canhBao = thamSo.onCanhBao ?? ((lyDo: string) => console.error("[sse]", lyDo));

  let es: EventSource | null = null;
  //: Redis Stream ID cua ban ghi CUOI CUNG DA GIAO CHO NGUOI DUNG (§7.3).
  let cursor = "";
  //: `done`/`error` da toi, hoac nguoi goi da `dong()`. Khong noi lai nua.
  let daKetThuc = false;
  //: So lan mo KHONG len lien tiep. Ve 0 moi khi `open`, hoac khi mang vua ve.
  let lanThu = 0;
  let hen: number | null = null;

  function baoTrangThai(trangThai: TrangThaiKetNoi): void {
    thamSo.onTrangThai?.(trangThai);
  }

  function huyHen(): void {
    if (hen !== null) {
      window.clearTimeout(hen);
      hen = null;
    }
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
      huyHen();
      dongKetNoi();
      baoTrangThai("dong");
    }
  }

  /** Hen mo lai — chi goi khi TRINH DUYET da bo cuoc (diem 2). */
  function henMoLai(): void {
    if (daKetThuc || hen !== null) {
      return;
    }
    lanThu += 1;
    if (lanThu > SO_LAN_THU_TOI_DA) {
      dongKetNoi();
      baoTrangThai("dong");
      thamSo.onChet?.(
        `da thu noi lai ${SO_LAN_THU_TOI_DA} lan ma khong len duoc — ` +
          `kiem tra mang, hoac message nay khong con doc duoc`,
      );
      return;
    }
    const cho = Math.min(CHO_DAU_MS * 2 ** (lanThu - 1), CHO_TOI_DA_MS);
    hen = window.setTimeout(() => {
      hen = null;
      moKetNoi();
    }, cho);
  }

  /** Mot ten, hai chuyen — xem diem 1 trong docstring module. */
  function xuLySuKienError(ev: Event): void {
    const khung = ev as MessageEvent<unknown>;
    if (typeof khung.data === "string") {
      nhanKhung("error", khung as MessageEvent<string>);
      return;
    }

    baoTrangThai("dang-noi-lai");

    if (es === null || es.readyState === EventSource.CLOSED) {
      // Trinh duyet da bo cuoc (Offline, 404, 401...) va se KHONG thu lai.
      // MINH nhan viec — khong phai minh cung bo cuoc (diem 2, B-115).
      dongKetNoi();
      henMoLai();
      return;
    }

    // `CONNECTING`: trinh duyet dang tu thu lai va no se gui `Last-Event-ID`.
    // KHONG goi close() o day — do dung la thu task cam.
  }

  function moKetNoi(): void {
    huyHen();
    dongKetNoi();
    const url = cursor === "" ? thamSo.url : `${thamSo.url}?cursor=${encodeURIComponent(cursor)}`;
    // `withCredentials` la chu cua Phu luc F, va la duong danh tinh di qua
    // (NQ-33): `EventSource` khong dat duoc header nen cookie la thu duy nhat
    // no mang theo.
    const nguon = new EventSource(url, { withCredentials: true });
    es = nguon;

    nguon.addEventListener("open", () => {
      lanThu = 0;
      baoTrangThai("dang-chay");
    });
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

  /**
   * Mang vua ve — mo lai NGAY, khong doi het luy thua.
   *
   * Day la thu bien "Offline 5 s roi bat lai" tu "cho toi 8 giay" thanh "chay
   * tiep gan nhu tuc thi". `lanThu` ve 0 vi mot lan chuyen trang thai mang la
   * thong tin moi: nhung lan truot truoc do khong noi gi ve lan nay.
   */
  function khiCoMang(): void {
    if (daKetThuc) {
      return;
    }
    lanThu = 0;
    moKetNoi();
  }

  document.addEventListener("visibilitychange", khiDoiHienThi);
  window.addEventListener("online", khiCoMang);
  moKetNoi();

  return {
    dong: () => {
      daKetThuc = true;
      document.removeEventListener("visibilitychange", khiDoiHienThi);
      window.removeEventListener("online", khiCoMang);
      huyHen();
      dongKetNoi();
    },
    cursor: () => cursor,
  };
}
