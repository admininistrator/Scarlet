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
 * con so Performance thi ham `runLighthouse()` khong doc no, va ban tom tat noi
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

const CONFIG_PATH = new URL("../config/audit.json", import.meta.url);

// Chrome chay bang root trong container nen sandbox cua nhan phai tat; va
// /dev/shm mac dinh cua Docker chi 64 MB, du de Chrome chet giua chung.
const CHROME_FLAGS = ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"];

// ─────────────────────────────────────────────────────────────────────────────

/** Chay mot lenh, tra { code, stdout, stderr }. Khong nem khi code != 0. */
function run(command, args, timeoutMs) {
  return new Promise((resolve) => {
    execFile(
      command,
      args,
      { timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024, encoding: "utf8" },
      (error, out, err) => {
        resolve({
          code: error?.code ?? (error ? 1 : 0),
          killed: error?.killed === true,
          stdout: out ?? "",
          stderr: err ?? "",
        });
      },
    );
  });
}

/** Tach doi tuong JSON dau tien trong mot chuoi co the lan ca log. */
function parseJson(text) {
  const first = text.indexOf("{");
  const last = text.lastIndexOf("}");
  if (first === -1 || last <= first) {
    throw new Error(`khong tim thay JSON trong dau ra (${text.length} ky tu)`);
  }
  return JSON.parse(text.slice(first, last + 1));
}

async function waitForWeb(baseUrl, { so_lan_thu, nghi_giua_hai_lan_ms }) {
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

async function runLighthouse(url, config, timeoutMs) {
  const kq = await run(
    "lighthouse",
    [
      url,
      "--quiet",
      "--output=json",
      "--output-path=stdout",
      `--only-categories=${config.only_categories.join(",")}`,
      `--chrome-flags=${CHROME_FLAGS.join(" ")}`,
    ],
    timeoutMs,
  );

  if (kq.killed) {
    return { error: `lighthouse qua han ${timeoutMs / 1000}s` };
  }
  // Ma thoat doc TRUOC JSON: khi lighthouse gap "runtime error" no van do mot
  // ban bao cao DANG DO ra stdout, va mot loi cu phap JSON o dong 2316 la cau
  // tra loi te nhat co the co cho cau hoi "vi sao trang khong tai duoc".
  if (kq.code !== 0) {
    return { error: `lighthouse thoat ${kq.code}: ${kq.stderr.trim().split("\n").pop()}` };
  }
  let report;
  try {
    report = parseJson(kq.stdout);
  } catch (e) {
    return { error: `lighthouse: ${e.message}${kq.stderr ? ` · stderr: ${kq.stderr.trim()}` : ""}` };
  }

  const scores = {};
  for (const name of config.only_categories) {
    // Lighthouse tra 0..1; nhan 100 de cung thang voi nguong trong config.
    const raw = report.categories?.[name]?.score;
    scores[name] = raw === null || raw === undefined ? null : Math.round(raw * 100);
  }

  // Cac audit thuoc nhom accessibility da TRUOT — de in ra khi diem thap.
  const failing = Object.values(report.audits ?? {})
    .filter((a) => a.score !== null && a.score < 1 && a.scoreDisplayMode === "binary")
    .map((a) => a.id);

  return { scores, failing };
}

async function runAxe(url, config, timeoutMs) {
  const kq = await run(
    "axe",
    [
      url,
      "--stdout",
      "--chromedriver-path=/usr/bin/chromedriver",
      `--chrome-options=${CHROME_FLAGS.map((c) => c.replace(/^--/, "")).join(",")}`,
    ],
    timeoutMs,
  );

  if (kq.killed) {
    return { error: `axe qua han ${timeoutMs / 1000}s` };
  }
  let report;
  try {
    // `--stdout` in mot MANG mot phan tu (mot phan tu cho moi url).
    const first = kq.stdout.indexOf("[");
    const last = kq.stdout.lastIndexOf("]");
    if (first === -1 || last <= first) {
      throw new Error(`khong tim thay JSON trong dau ra (${kq.stdout.length} ky tu)`);
    }
    report = JSON.parse(kq.stdout.slice(first, last + 1))[0];
  } catch (e) {
    return { error: `axe: ${e.message}${kq.stderr ? ` · stderr: ${kq.stderr.trim()}` : ""}` };
  }

  // `target` la CSS selector cua dung phan tu hong, va `data` mang fgColor /
  // bgColor / contrastRatio — day la thu tra loi cau hoi "loi tuong phan o
  // dau" ma ca am cua DoD doi.
  const compact = (r) => ({
    id: r.id,
    impact: r.impact,
    help: r.help,
    nodes: r.nodes.map((n) => ({
      target: n.target.join(" "),
      details: [...(n.any ?? []), ...(n.none ?? []), ...(n.all ?? [])]
        .flatMap((c) => Object.entries(c.data ?? {}))
        .map(([k, val]) => `${k}=${val}`)
        .join(" "),
    })),
  });

  const violations = (report?.violations ?? []).map(compact);
  const incomplete = (report?.incomplete ?? []).map(compact);

  return {
    violations,
    incomplete,
    severe: violations.filter((v) => config.fail_impacts.includes(v.impact)),
    // `incomplete` cua nhung luat ma "khong ket luan duoc" != "dat".
    needsReview: incomplete.filter((v) => config.fail_incomplete_rules.includes(v.id)),
  };
}

// ─────────────────────────────────────────────────────────────────────────────

function printViolation(prefix, v) {
  console.log(`  ${prefix}[${v.impact ?? "—"}] ${v.id} — ${v.help}`);
  for (const n of v.nodes) {
    console.log(`      ${n.target}${n.details ? `  (${n.details})` : ""}`);
  }
}

async function main() {
  const config = JSON.parse(await readFile(CONFIG_PATH, "utf8"));
  const timeoutMs = config.timeout_moi_lenh_s * 1000;

  const routeFilter = env.DUONG?.trim();
  const duongs = routeFilter ? config.routes.filter((d) => d === routeFilter) : config.routes;
  if (duongs.length === 0) {
    console.error(
      `DUONG=${routeFilter} khong nam trong \`routes\` cua config/audit.json ` +
        `(${config.routes.join(" ")})`,
    );
    return 1;
  }

  const a11yThreshold = config.lighthouse.min_scores.accessibility;

  console.log(`Scarlet — audit S8 · ${config.base_url} · ${config.lighthouse.form_factor}`);
  console.log(
    `Nguong: Lighthouse Accessibility >= ${a11yThreshold} · axe 0 loi ` +
      `${config.axe.fail_impacts.join("/")} · 0 ket qua \`incomplete\` cua ` +
      `${config.axe.fail_incomplete_rules.join("/")}`,
  );
  console.log(
    "Performance: KHONG do o day. Phep do chay tren Vite dev server " +
      "(ES module chua minify + HMR), nen con so ay khong noi gi ve ban " +
      "production. NQ-77 da chuyen `Performance >= 80` sang T-9.4 (P9).",
  );
  console.log("");

  await waitForWeb(config.base_url, config.cho_san_sang);

  const results = [];
  for (const route of duongs) {
    const url = new URL(route, config.base_url).toString();
    const startedAt = Date.now();
    const lh = await runLighthouse(url, config.lighthouse, timeoutMs);
    const ax = await runAxe(url, config.axe, timeoutMs);
    results.push({ route, url, lh, ax });
    console.log(`  da do ${url}  (${((Date.now() - startedAt) / 1000).toFixed(1)}s)`);
  }
  console.log("");

  // ── Bang tom tat ──────────────────────────────────────────────────────────
  const width = Math.max(...duongs.map((d) => d.length), "DUONG".length);
  console.log(`${"DUONG".padEnd(width)}  A11Y  AXE nang  AXE can soat  KET LUAN`);
  console.log(`${"-".repeat(width)}  ----  --------  ------------  --------`);

  let failedCount = 0;
  for (const r of results) {
    const scores = r.lh.error ? "LOI" : String(r.lh.scores.accessibility ?? "?");
    const severeCount = r.ax.error ? "LOI" : String(r.ax.severe.length);
    const reviewCount = r.ax.error ? "LOI" : String(r.ax.needsReview.length);
    r.passed =
      !r.lh.error &&
      !r.ax.error &&
      r.lh.scores.accessibility !== null &&
      r.lh.scores.accessibility >= a11yThreshold &&
      r.ax.severe.length === 0 &&
      r.ax.needsReview.length === 0;
    if (!r.passed) failedCount += 1;
    console.log(
      `${r.route.padEnd(width)}  ${scores.padStart(4)}  ${severeCount.padStart(8)}  ` +
        `${reviewCount.padStart(12)}  ${r.passed ? "DAT" : "TRUOT"}`,
    );
  }
  console.log("");

  // ── Chi tiet cho tung duong truot ─────────────────────────────────────────
  for (const r of results) {
    if (r.passed) continue;

    console.log(`--- ${r.route} ---`);
    if (r.lh.error) console.log(`  lighthouse: ${r.lh.error}`);
    if (!r.lh.error && (r.lh.scores.accessibility ?? 0) < a11yThreshold) {
      console.log(
        `  lighthouse accessibility = ${r.lh.scores.accessibility} (< ${a11yThreshold}); ` +
          `audit truot: ${r.lh.failing.join(", ") || "(khong co audit binary nao truot)"}`,
      );
    }
    if (r.ax.error) console.log(`  axe: ${r.ax.error}`);
    for (const v of r.ax.severe ?? []) printViolation("", v);
    for (const v of r.ax.needsReview ?? []) printViolation("chua ket luan · ", v);
    console.log("");
  }

  if (failedCount > 0) {
    console.log(`audit: THAT BAI — ${failedCount}/${results.length} duong truot`);
    return failedCount;
  }
  console.log(`audit: OK — ${results.length}/${results.length} duong dat`);
  return 0;
}

main().then(exit, (e) => {
  console.error(`audit: ${e.message}`);
  exit(1);
});
