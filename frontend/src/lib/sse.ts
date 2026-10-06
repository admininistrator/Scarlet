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
 * `MAX_ATTEMPTS` lan lien tiep khong len duoc moi bao `onFatal` — va luc
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
 * `cursor` va noi vao `?cursor=`. `parse_cursor` phia server doc header TRUOC
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
 * do; het `MAX_ATTEMPTS` chi doi trang thai duong day sang `dong` va goi
 * `onFatal`, no khong bia ra mot ket cuc cho cau tra loi.
 */

/** So token — payload cua `usage`. Khoa VANG MAT nghia la provider khong bao. */
export interface UsageOut {
  in: number;
  out: number;
  reasoning?: number;
  cached?: number;
}

/**
 * Chin loai event cua §7.4 / Phu luc F.
 *
 * `start.reasoning_effort` — truong THEM cua §24.2b·S4/S14 (T-S.6), khai o
 * T-S.15 (B-286). FE chua doc no: chip "model · muc" chi dung khi da xong, va
 * luc ay doc `MessageOut.reasoning_effort` cua duong di.
 *
 * `artifact.kind` / `artifact.title` — T-5.1 (Phu luc F khai `kind`; `title`
 * them de the hien ngay, B-360). `title` rong = khoi khong tieu de.
 */
export type StreamEvent =
  | {
      event: "start";
      data: { message_id: string; model_id: string; reasoning_effort?: string | null };
    }
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
  | {
      event: "artifact";
      data: { artifact_id: string; version: number; kind: string; title: string };
    }
  | { event: "usage"; data: UsageOut }
  | { event: "done"; data: { finish_reason: string | null; usage: UsageOut | null } }
  | { event: "error"; data: { code: string; message: string } };

export type EventType = StreamEvent["event"];

/**
 * T-S.13 — bon event cua stream TIEU DE (`GET /conversations/{id}/title/stream`,
 * §24.2b·S6, T-S.7, B-289). `start`/`delta`/`error` dung la ba loai cua §7.4;
 * `done` mang tieu de DANG NAM TRONG DB — co the la ten nguoi dung tu dat giua
 * chung — chu khong mang `finish_reason`/`usage`. Nguoi nghe THAY chu da chay
 * bang dung chuoi nay. `error` gom ca `JOB_LOST` (tieu de `NULL`, khong stream,
 * khong job).
 */
export type TitleStreamEvent =
  | { event: "start"; data: { message_id: string; model_id: string } }
  | { event: "delta"; data: { t: string } }
  | { event: "done"; data: { title: string } }
  | { event: "error"; data: { code: string; message: string } };

/**
 * Tam loai dang ky bang vong lap. `error` KHONG o day — no co mot handler
 * rieng vi ten do dung chung voi su kien dut duong truyen (diem 1).
 */
const NON_ERROR_EVENTS = [
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
export const ALL_EVENT_TYPES: readonly EventType[] = [...NON_ERROR_EVENTS, "error"];

/** Cho bao lau truoc lan thu DAU khi trinh duyet bo cuoc (diem 2). */
const INITIAL_DELAY_MS = 1_000;
/** Tran cua luy thua. Lon hon nua thi mot lan mat mang ngan cung phai cho lau. */
const MAX_DELAY_MS = 15_000;
/**
 * Bao nhieu lan lien tiep khong len duoc thi thoi.
 *
 * Voi luy thua co tran o tren, tam lan la ~1+2+4+8+15+15+15 ≈ 60 s co gang.
 * Mot lan Offline 5 s cua DoD len lai o lan thu nhat (va thuong la ngay lap
 * tuc, nho su kien `online`); mot message 404 that thi dung sau ~60 s va noi
 * ra — thay vi quay vong mai voi mot con tro nhap nhay.
 */
const MAX_ATTEMPTS = 8;

/**
 * Trang thai duong day, de man hinh noi dung su that.
 *
 * `dang-noi-lai` khac `dong`: cai dau la "van dang co" (trinh duyet tu thu,
 * hoac minh dang hen gio thu), cai sau la "da thoi". Gop hai cai vao mot la
 * mat dung thu nguoi dung can biet.
 */
export type ConnectionStatus = "dang-mo" | "dang-chay" | "dang-noi-lai" | "dong";

/**
 * `E` = hinh dang event cua stream dang mo: `StreamEvent` (cau tra loi, mac
 * dinh) hoac `TitleStreamEvent` (T-S.13). Dau doc khong doi: cung ten event,
 * cung cursor, cung luat `done`/`error` ket thuc — chi kieu cua `data` khac.
 */
export interface StreamParams<E extends { event: EventType } = StreamEvent> {
  /** Duong dan tuong doi, lay nguyen tu `stream_url` cua `202`. */
  url: string;
  onEvent: (event: E) => void;
  onStatus?: (status: ConnectionStatus) => void;
  /** Da thu het `MAX_ATTEMPTS` lan ma khong len — xem diem 2. */
  onFatal?: (reason: string) => void;
  /** Khung doc khong duoc. Mac dinh in ra console, khong nuot. */
  onWarning?: (reason: string) => void;
}

export interface StreamHandle {
  /** Dong han. Go het listener va hen gio. Goi nhieu lan khong sao. */
  close: () => void;
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
export function openStream<E extends { event: EventType } = StreamEvent>(
  params: StreamParams<E>,
): StreamHandle {
  const warn = params.onWarning ?? ((reason: string) => console.error("[sse]", reason));

  let es: EventSource | null = null;
  //: Redis Stream ID cua ban ghi CUOI CUNG DA GIAO CHO NGUOI DUNG (§7.3).
  let cursor = "";
  //: `done`/`error` da toi, hoac nguoi goi da `dong()`. Khong noi lai nua.
  let finished = false;
  //: So lan mo KHONG len lien tiep. Ve 0 moi khi `open`, hoac khi mang vua ve.
  let attempt = 0;
  let timer: number | null = null;

  function reportStatus(status: ConnectionStatus): void {
    params.onStatus?.(status);
  }

  function clearReconnect(): void {
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
  }

  function closeConnection(): void {
    if (es !== null) {
      es.close();
      es = null;
    }
  }

  function handleFrame(kind: EventType, ev: MessageEvent<string>): void {
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
      warn(`khung ${kind} khong phai JSON: ${ev.data.slice(0, 120)}`);
      return;
    }

    // `data` la JSON chua kiem hinh dang — tin server nhu truoc T-S.13; `E` chi
    // chon bang loai nao nguoi goi doc (cau tra loi hay tieu de).
    params.onEvent({ event: kind, data } as unknown as E);

    if (kind === "done" || kind === "error") {
      finished = true;
      clearReconnect();
      closeConnection();
      reportStatus("dong");
    }
  }

  /** Hen mo lai — chi goi khi TRINH DUYET da bo cuoc (diem 2). */
  function scheduleReconnect(): void {
    if (finished || timer !== null) {
      return;
    }
    attempt += 1;
    if (attempt > MAX_ATTEMPTS) {
      closeConnection();
      reportStatus("dong");
      params.onFatal?.(
        `da thu noi lai ${MAX_ATTEMPTS} lan ma khong len duoc — ` +
          `kiem tra mang, hoac message nay khong con doc duoc`,
      );
      return;
    }
    const delay = Math.min(INITIAL_DELAY_MS * 2 ** (attempt - 1), MAX_DELAY_MS);
    timer = window.setTimeout(() => {
      timer = null;
      openConnection();
    }, delay);
  }

  /** Mot ten, hai chuyen — xem diem 1 trong docstring module. */
  function handleErrorEvent(ev: Event): void {
    const frame = ev as MessageEvent<unknown>;
    if (typeof frame.data === "string") {
      handleFrame("error", frame as MessageEvent<string>);
      return;
    }

    reportStatus("dang-noi-lai");

    if (es === null || es.readyState === EventSource.CLOSED) {
      // Trinh duyet da bo cuoc (Offline, 404, 401...) va se KHONG thu lai.
      // MINH nhan viec — khong phai minh cung bo cuoc (diem 2, B-115).
      closeConnection();
      scheduleReconnect();
      return;
    }

    // `CONNECTING`: trinh duyet dang tu thu lai va no se gui `Last-Event-ID`.
    // KHONG goi close() o day — do dung la thu task cam.
  }

  function openConnection(): void {
    clearReconnect();
    closeConnection();
    const url = cursor === "" ? params.url : `${params.url}?cursor=${encodeURIComponent(cursor)}`;
    // `withCredentials` la chu cua Phu luc F, va la duong danh tinh di qua
    // (NQ-33): `EventSource` khong dat duoc header nen cookie la thu duy nhat
    // no mang theo.
    const eventSource = new EventSource(url, { withCredentials: true });
    es = eventSource;

    eventSource.addEventListener("open", () => {
      attempt = 0;
      reportStatus("dang-chay");
    });
    for (const kind of NON_ERROR_EVENTS) {
      eventSource.addEventListener(kind, (ev) => handleFrame(kind, ev as MessageEvent<string>));
    }
    eventSource.addEventListener("error", handleErrorEvent);

    reportStatus("dang-mo");
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
  function handleVisibilityChange(): void {
    if (finished || document.visibilityState !== "visible") {
      return;
    }
    openConnection();
  }

  /**
   * Mang vua ve — mo lai NGAY, khong doi het luy thua.
   *
   * Day la thu bien "Offline 5 s roi bat lai" tu "cho toi 8 giay" thanh "chay
   * tiep gan nhu tuc thi". `attempt` ve 0 vi mot lan chuyen trang thai mang la
   * thong tin moi: nhung lan truot truoc do khong noi gi ve lan nay.
   */
  function handleOnline(): void {
    if (finished) {
      return;
    }
    attempt = 0;
    openConnection();
  }

  document.addEventListener("visibilitychange", handleVisibilityChange);
  window.addEventListener("online", handleOnline);
  openConnection();

  return {
    close: () => {
      finished = true;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", handleOnline);
      clearReconnect();
      closeConnection();
    },
    cursor: () => cursor,
  };
}
