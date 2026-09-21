#!/usr/bin/env node
/**
 * S8 — Lighthouse Accessibility + axe-core tren bon duong cua Phase 3.
 *
 * KH tham chieu: §2.3 (S8), §19.1 · tasks.md T-3.2, T-3.10, B-203/NQ-77.
 *
 *     make audit
 *     make audit DUONG=/dang-nhap          # chi mot duong, dung luc sua loi
 *
 * Script nay KHONG chay tren host: no can mot Chrome that, va cho duy nhat co
 * Chrome trong he nay la container `audit` (xem `audit/Dockerfile`). `make
 * audit` boc no bang `docker compose run --rm`.
 *
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │  HAI CONG CU, HAI CAU HOI KHAC NHAU                                      │
 * └──────────────────────────────────────────────────────────────────────────┘
 *
 *   lighthouse   mot DIEM 0..100 cho ca trang. Nguong S8: >= 90.
 *   axe-core     mot DANH SACH vi pham, moi vi pham co `impact`. Nguong DoD:
 *                khong duoc co `serious` hay `critical`.
 *
 * Hai cong cu deu chay axe-core ben trong, nhung chung KHONG thay the nhau:
 * diem cua lighthouse la trung binh co trong so, nen ba loi nho va mot loi
 * `critical` co the ra cung mot con so. Nguoc lai, axe khong cho mot con so de
 * theo doi qua thoi gian. Nen o day ca hai cung chay, va mot trong hai truot
 * la ca lan chay do.
 *
 * Do duoc 2026-09-21, va day la ly do cu the nhat de giu ca hai: khi ca am
 * cua DoD lam chu chim hoan toan vao nen (fgColor == bgColor), **lighthouse
 * van cham 100**. Chi axe bat duoc — va cung chi bat duoc neu doc ca muc
 * `incomplete`, xem ngay duoi.
 *
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │  NAM QUYET DINH CUA PHEP DO                                              │
 * └──────────────────────────────────────────────────────────────────────────┘
 *
 * **1. Do `http://web:5173`, khong `https://localhost`.** CA cua mkcert nam
 * tren host Windows (T-H1), khong trong trust store cua bat ky container nao.
 * Do thang Vite dev server tren network `internal` xoa han van de ay bang
 * cach khong tao ra no — thay vi bom CA vao image hay bat mot co "bo qua
 * chung chi" roi song chung voi no mai mai. Danh doi da biet truoc: phep do
 * nay KHONG di qua Nginx, nen no khong noi gi ve header, ve nen hay ve C1.
 *
 * **2. Performance bi bo qua TUONG MINH, khong bi lo di.** `only_categories`
 * trong `config/audit.json` co dung mot phan tu. Neu lighthouse van in ra mot
 * con so Performance thi ham `chayLighthouse()` khong doc no, va ban tom tat noi
 * thanh loi rang no khong duoc doc — vi ly do gi (NQ-77: Vite dev server phuc
 * vu ES module chua minify cong client HMR, mot diem cham o day khong noi gi
 * ve san pham se deploy; `Performance >= 80` da chuyen sang T-9.4 / P9).
 * Nguoi chay tiep theo se nhin thay con so do; im lang la de ho tu ket luan.
 *
 * **3. Moi nguong va moi duong den tu `config/audit.json`** (A3/L4). Doi
 * nguong tu 90 xuong 80 phai la mot dong diff trong `config/`, tuc mot dong
 * ai cung thay trong review — khong phai mot con so nam giua 300 dong script.
 *
 * **4. Cho `web` san sang truoc khi do, va cho co GIOI HAN.** Vite dev server
 * mat vai giay de dung dependency optimizer o lan chay dau. Khong cho thi lan
 * chay dau tien sau `make up` luon do voi mot loi mang, va nguoi ta se hoc
 * cach chay `make audit` hai lan — tuc hoc cach bo qua lan do dau tien.
 *
 * **5. Ma thoat = so duong TRUOT, khong phai 1.** Cung khuon `make bench` cua
 * T-1.12. `echo $?` sau mot lan chay do noi duoc "mot duong hong" hay "ca bon
 * duong hong" ma khong phai cuon nguoc ban tom tat.
 *
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │  CA AM CUA DoD, VA MOT THU NO PHAT HIEN RA                               │
 * └──────────────────────────────────────────────────────────────────────────┘
 *
 * DoD cua T-3.2 doi mot lan chay DO co chu dich: dat tam
 * `--color-muted: var(--color-background)` trong `theme.css` roi chay lai.
 * Lan chay ay lo ra mot cho ma mot ban script "dem `violations`" se im lang:
 *
 *     axe-core tra ket qua tuong phan 1:1 vao muc `incomplete`
 *     (`messageKey: "equalRatio"`), KHONG vao `violations`.
 *
 * No khong phan biet duoc "chu chim vao nen vi loi" voi "chu bi an co y", nen
 * no tu choi ket luan. Voi mot cong kiem, "khong ket luan duoc" khong phai
 * "dat" — nen `axe.fail_incomplete_rules` trong `config/audit.json` liet ke
 * cac luat ma mot ket qua `incomplete` cung lam do ca lan chay. Hom nay danh
 * sach do co dung `color-contrast`, tuc dung thu `make audit` ton tai de do.
 *
 * Bao cao duoi day phai noi duoc *loi tuong phan o dau* — vi vay phan axe in
 * nguyen `target` (CSS selector) va cap mau cua tung vi pham, chu khong chi
 * dem so luong. Mot ban bao cao chi co con so khong phan biet duoc "khong co
 * loi" voi "khong do gi".
 */

import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { env, exit } from "node:process";

const DUONG_CONFIG = new URL("../config/audit.json", import.meta.url);

// Chrome chay bang root trong container nen sandbox cua nhan phai tat; va
// /dev/shm mac dinh cua Docker chi 64 MB, du de Chrome chet giua chung.
const CO_CHROME = ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"];

// ─────────────────────────────────────────────────────────────────────────────

/** Chay mot lenh, tra { code, stdout, stderr }. Khong nem khi code != 0. */
function chay(lenh, thamSo, timeoutMs) {
  return new Promise((resolve) => {
    execFile(
      lenh,
      thamSo,
      { timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024, encoding: "utf8" },
      (loi, out, err) => {
        resolve({
          code: loi?.code ?? (loi ? 1 : 0),
          killed: loi?.killed === true,
          stdout: out ?? "",
          stderr: err ?? "",
        });
      },
    );
  });
}

/** Tach doi tuong JSON dau tien trong mot chuoi co the lan ca log. */
function docJSON(chuoi) {
  const dau = chuoi.indexOf("{");
  const cuoi = chuoi.lastIndexOf("}");
  if (dau === -1 || cuoi <= dau) {
    throw new Error(`khong tim thay JSON trong dau ra (${chuoi.length} ky tu)`);
  }
  return JSON.parse(chuoi.slice(dau, cuoi + 1));
}

async function choWebSanSang(baseUrl, { so_lan_thu, nghi_giua_hai_lan_ms }) {
  for (let i = 1; i <= so_lan_thu; i += 1) {
    try {
      const res = await fetch(baseUrl, { redirect: "manual" });
      if (res.status < 500) {
        return;
      }
    } catch {
      // chua len — thu lai
    }
    if (i === so_lan_thu) {
      throw new Error(
        `${baseUrl} khong tra loi sau ${so_lan_thu} lan thu. ` +
          `Service \`web\` da chay chua? \`make up\` roi chay lai.`,
      );
    }
    await new Promise((r) => setTimeout(r, nghi_giua_hai_lan_ms));
  }
}

// ─────────────────────────────────────────────────────────────────────────────

async function chayLighthouse(url, cauHinh, timeoutMs) {
  const kq = await chay(
    "lighthouse",
    [
      url,
      "--quiet",
      "--output=json",
      "--output-path=stdout",
      `--only-categories=${cauHinh.only_categories.join(",")}`,
      `--chrome-flags=${CO_CHROME.join(" ")}`,
    ],
    timeoutMs,
  );

  if (kq.killed) {
    return { loi: `lighthouse qua han ${timeoutMs / 1000}s` };
  }
  // Ma thoat doc TRUOC JSON: khi lighthouse gap "runtime error" no van do mot
  // ban bao cao DANG DO ra stdout, va mot loi cu phap JSON o dong 2316 la cau
  // tra loi te nhat co the co cho cau hoi "vi sao trang khong tai duoc".
  if (kq.code !== 0) {
    return { loi: `lighthouse thoat ${kq.code}: ${kq.stderr.trim().split("\n").pop()}` };
  }
  let bao;
  try {
    bao = docJSON(kq.stdout);
  } catch (e) {
    return { loi: `lighthouse: ${e.message}${kq.stderr ? ` · stderr: ${kq.stderr.trim()}` : ""}` };
  }

  const diem = {};
  for (const ten of cauHinh.only_categories) {
    // Lighthouse tra 0..1; nhan 100 de cung thang voi nguong trong config.
    const raw = bao.categories?.[ten]?.score;
    diem[ten] = raw === null || raw === undefined ? null : Math.round(raw * 100);
  }

  // Cac audit thuoc nhom accessibility da TRUOT — de in ra khi diem thap.
  const truot = Object.values(bao.audits ?? {})
    .filter((a) => a.score !== null && a.score < 1 && a.scoreDisplayMode === "binary")
    .map((a) => a.id);

  return { diem, truot };
}

async function chayAxe(url, cauHinh, timeoutMs) {
  const kq = await chay(
    "axe",
    [
      url,
      "--stdout",
      "--chromedriver-path=/usr/bin/chromedriver",
      `--chrome-options=${CO_CHROME.map((c) => c.replace(/^--/, "")).join(",")}`,
    ],
    timeoutMs,
  );

  if (kq.killed) {
    return { loi: `axe qua han ${timeoutMs / 1000}s` };
  }
  let bao;
  try {
    // `--stdout` in mot MANG mot phan tu (mot phan tu cho moi url).
    const dau = kq.stdout.indexOf("[");
    const cuoi = kq.stdout.lastIndexOf("]");
    if (dau === -1 || cuoi <= dau) {
      throw new Error(`khong tim thay JSON trong dau ra (${kq.stdout.length} ky tu)`);
    }
    bao = JSON.parse(kq.stdout.slice(dau, cuoi + 1))[0];
  } catch (e) {
    return { loi: `axe: ${e.message}${kq.stderr ? ` · stderr: ${kq.stderr.trim()}` : ""}` };
  }

  // `target` la CSS selector cua dung phan tu hong, va `data` mang fgColor /
  // bgColor / contrastRatio — day la thu tra loi cau hoi "loi tuong phan o
  // dau" ma ca am cua DoD doi.
  const gon = (r) => ({
    id: r.id,
    impact: r.impact,
    help: r.help,
    noi: r.nodes.map((n) => ({
      target: n.target.join(" "),
      chiTiet: [...(n.any ?? []), ...(n.none ?? []), ...(n.all ?? [])]
        .flatMap((c) => Object.entries(c.data ?? {}))
        .map(([k, val]) => `${k}=${val}`)
        .join(" "),
    })),
  });

  const viPham = (bao?.violations ?? []).map(gon);
  const chuaKetLuan = (bao?.incomplete ?? []).map(gon);

  return {
    viPham,
    chuaKetLuan,
    nang: viPham.filter((v) => cauHinh.fail_impacts.includes(v.impact)),
    // `incomplete` cua nhung luat ma "khong ket luan duoc" != "dat".
    canSoat: chuaKetLuan.filter((v) => cauHinh.fail_incomplete_rules.includes(v.id)),
  };
}

// ─────────────────────────────────────────────────────────────────────────────

function inViPham(tienTo, v) {
  console.log(`  ${tienTo}[${v.impact ?? "—"}] ${v.id} — ${v.help}`);
  for (const n of v.noi) {
    console.log(`      ${n.target}${n.chiTiet ? `  (${n.chiTiet})` : ""}`);
  }
}

async function main() {
  const cauHinh = JSON.parse(await readFile(DUONG_CONFIG, "utf8"));
  const timeoutMs = cauHinh.timeout_moi_lenh_s * 1000;

  const loc = env.DUONG?.trim();
  const duongs = loc ? cauHinh.routes.filter((d) => d === loc) : cauHinh.routes;
  if (duongs.length === 0) {
    console.error(
      `DUONG=${loc} khong nam trong \`routes\` cua config/audit.json ` +
        `(${cauHinh.routes.join(" ")})`,
    );
    return 1;
  }

  const nguongA11y = cauHinh.lighthouse.min_scores.accessibility;

  console.log(`Scarlet — audit S8 · ${cauHinh.base_url} · ${cauHinh.lighthouse.form_factor}`);
  console.log(
    `Nguong: Lighthouse Accessibility >= ${nguongA11y} · axe 0 loi ` +
      `${cauHinh.axe.fail_impacts.join("/")} · 0 ket qua \`incomplete\` cua ` +
      `${cauHinh.axe.fail_incomplete_rules.join("/")}`,
  );
  console.log(
    "Performance: KHONG do o day. Phep do chay tren Vite dev server " +
      "(ES module chua minify + HMR), nen con so ay khong noi gi ve ban " +
      "production. NQ-77 da chuyen `Performance >= 80` sang T-9.4 (P9).",
  );
  console.log("");

  await choWebSanSang(cauHinh.base_url, cauHinh.cho_san_sang);

  const ketQua = [];
  for (const duong of duongs) {
    const url = new URL(duong, cauHinh.base_url).toString();
    const batDau = Date.now();
    const lh = await chayLighthouse(url, cauHinh.lighthouse, timeoutMs);
    const ax = await chayAxe(url, cauHinh.axe, timeoutMs);
    ketQua.push({ duong, url, lh, ax });
    console.log(`  da do ${url}  (${((Date.now() - batDau) / 1000).toFixed(1)}s)`);
  }
  console.log("");

  // ── Bang tom tat ──────────────────────────────────────────────────────────
  const rong = Math.max(...duongs.map((d) => d.length), "DUONG".length);
  console.log(`${"DUONG".padEnd(rong)}  A11Y  AXE nang  AXE can soat  KET LUAN`);
  console.log(`${"-".repeat(rong)}  ----  --------  ------------  --------`);

  let soTruot = 0;
  for (const r of ketQua) {
    const diem = r.lh.loi ? "LOI" : String(r.lh.diem.accessibility ?? "?");
    const soNang = r.ax.loi ? "LOI" : String(r.ax.nang.length);
    const soSoat = r.ax.loi ? "LOI" : String(r.ax.canSoat.length);
    r.dat =
      !r.lh.loi &&
      !r.ax.loi &&
      r.lh.diem.accessibility !== null &&
      r.lh.diem.accessibility >= nguongA11y &&
      r.ax.nang.length === 0 &&
      r.ax.canSoat.length === 0;
    if (!r.dat) soTruot += 1;
    console.log(
      `${r.duong.padEnd(rong)}  ${diem.padStart(4)}  ${soNang.padStart(8)}  ` +
        `${soSoat.padStart(12)}  ${r.dat ? "DAT" : "TRUOT"}`,
    );
  }
  console.log("");

  // ── Chi tiet cho tung duong truot ─────────────────────────────────────────
  for (const r of ketQua) {
    if (r.dat) continue;

    console.log(`--- ${r.duong} ---`);
    if (r.lh.loi) console.log(`  lighthouse: ${r.lh.loi}`);
    if (!r.lh.loi && (r.lh.diem.accessibility ?? 0) < nguongA11y) {
      console.log(
        `  lighthouse accessibility = ${r.lh.diem.accessibility} (< ${nguongA11y}); ` +
          `audit truot: ${r.lh.truot.join(", ") || "(khong co audit binary nao truot)"}`,
      );
    }
    if (r.ax.loi) console.log(`  axe: ${r.ax.loi}`);
    for (const v of r.ax.nang ?? []) inViPham("", v);
    for (const v of r.ax.canSoat ?? []) inViPham("chua ket luan · ", v);
    console.log("");
  }

  if (soTruot > 0) {
    console.log(`audit: THAT BAI — ${soTruot}/${ketQua.length} duong truot`);
    return soTruot;
  }
  console.log(`audit: OK — ${ketQua.length}/${ketQua.length} duong dat`);
  return 0;
}

main().then(exit, (e) => {
  console.error(`audit: ${e.message}`);
  exit(1);
});
