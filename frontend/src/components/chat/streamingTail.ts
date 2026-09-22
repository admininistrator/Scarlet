/**
 * Tach phan DANG DO o cuoi chu, de markdown chua dong khong lam vo bo cuc.
 *
 * KH tham chieu: T-3.5 "Viec" dong 5 · ban T-HD3 hinh 2d ("markdown chua
 * dong" va "bang dang do") · quy tac 3 cua o hieu nang.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO PHAI CAT, THAY VI DE REMARK TU LO                              ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Remark **khong** dung sai: mot hang ``` chua dong duoc no coi la khoi code
 * chay toi het van ban, con mot bang thieu hang phan cach thi no de nguyen
 * thanh doan van. Khong cai nao lam vo bo cuc.
 *
 * Cai no khong lam duoc la **noi ra** rang khoi ay dang do. Ban T-HD3 doi hai
 * thu khac nhau ve hinh: khoi code dang mo co vien net dut, KHONG co nut Copy
 * (copy mot khoi code dang do la mot cai bay), va cao toi thieu hai dong nen
 * no khong co giat khi dong dau tien ve. Bang chua du hang phan cach thi hien
 * chu tho trong mot khoi don sac — dung `<table>` roi pha di giua luc stream
 * la nguon giat bo cuc lon nhat.
 *
 * Vi the ham nay chi chay khi `streaming === true`. Luc da xong, mot hang ```
 * lac loai la chu that su cua model, khong phai mot khoi dang do, va no duoc
 * ve nhu moi khoi code khac.
 */

export type StreamingTail =
  | { readonly kind: "code"; readonly language: string; readonly code: string }
  | { readonly kind: "raw"; readonly text: string }
  | null;

export interface SplitResult {
  /** Phan giao cho renderer markdown. */
  readonly body: string;
  /** Phan dang do, hoac `null`. */
  readonly tail: StreamingTail;
}

/** Hang mo/dong khoi code: toi da 3 dau cach, roi >= 3 ky tu ` hoac ~. */
const FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;

/** Mot hang phan cach GFM hoan chinh: `| --- | :---: |`. */
const DELIMITER = /^\s*\|?(?:\s*:?-+:?\s*\|)*\s*:?-+:?\s*\|?\s*$/;

/** Mot hang phan cach moi go duoc mot nua: `| --- | --`, `| :`, `|`. */
const DELIMITER_PREFIX = /^\s*\|?(?:\s*:?-*:?\s*\|)*\s*:?-*:?\s*$/;

function cellCount(row: string): number {
  const trimmed = row.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").length;
}

/**
 * Vi tri dong mo cua hang ``` chua duoc dong, hoac `-1`.
 *
 * Dong khoi doi dung ky tu ay va it nhat bang so luong ay (luat CommonMark),
 * nen mot hang ```` bên trong mot khoi mo bang ``` khong dong duoc no.
 */
function openFenceLine(lines: readonly string[]): number {
  let openAt = -1;
  let marker = "";
  for (let i = 0; i < lines.length; i += 1) {
    const m = FENCE.exec(lines[i]);
    if (m === null) {
      continue;
    }
    if (openAt === -1) {
      // Hang mo bang ` thi phan thong tin khong duoc chua ky tu `.
      if (m[1][0] === "`" && m[2].includes("`")) {
        continue;
      }
      openAt = i;
      marker = m[1];
    } else if (m[1][0] === marker[0] && m[1].length >= marker.length && m[2].trim() === "") {
      openAt = -1;
      marker = "";
    }
  }
  return openAt;
}

/**
 * So dong o CUOI van ban lap thanh mot bang chua hoan chinh, hoac `0`.
 *
 * Tra `0` cho ca hai ca "khong phai bang" va "bang da hop le" — ca sau remark
 * dung `<table>` duoc roi, khong viec gi phai cat.
 */
function danglingTableLines(lines: readonly string[]): number {
  let start = lines.length;
  while (start > 0 && lines[start - 1].trimStart().startsWith("|")) {
    start -= 1;
  }
  const run = lines.length - start;
  if (run === 0) {
    return 0;
  }
  if (run === 1) {
    // Moi co hang tieu de.
    return 1;
  }
  const header = lines[start];
  const delimiter = lines[start + 1];
  if (DELIMITER.test(delimiter) && cellCount(delimiter) === cellCount(header)) {
    return 0; // Bang that su — de remark dung <table>.
  }
  // Hang phan cach moi go duoc mot nua thi van la bang dang do; con neu no
  // khong giong hang phan cach chut nao thi day khong phai bang, de nguyen.
  return run === 2 && DELIMITER_PREFIX.test(delimiter) ? 2 : 0;
}

export function splitStreamingTail(text: string, streaming: boolean): SplitResult {
  if (!streaming || text === "") {
    return { body: text, tail: null };
  }

  const lines = text.split("\n");

  const fenceAt = openFenceLine(lines);
  if (fenceAt !== -1) {
    const info = FENCE.exec(lines[fenceAt])?.[2] ?? "";
    return {
      body: lines.slice(0, fenceAt).join("\n"),
      tail: {
        kind: "code",
        language: info.trim().split(/\s+/)[0] ?? "",
        code: lines.slice(fenceAt + 1).join("\n"),
      },
    };
  }

  const tableLines = danglingTableLines(lines);
  if (tableLines > 0) {
    const start = lines.length - tableLines;
    return {
      body: lines.slice(0, start).join("\n"),
      tail: { kind: "raw", text: lines.slice(start).join("\n") },
    };
  }

  return { body: text, tail: null };
}
