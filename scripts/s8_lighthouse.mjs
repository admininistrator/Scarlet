#!/usr/bin/env node
/**
 * S8 — Lighthouse mobile Performance + Accessibility qua Nginx https (§2.3,
 * NQ-77; T-9.4a localhost, T-9.4b domain that).
 *
 *     make s8
 *
 * Chay trong service `artifact-origin` (image `audit`, netns cua `nginx`): do
 * dung thu nguoi dung tai — TLS, nen, cache cua Nginx — khong phai
 * `http://web:5173` nhu `make audit`. Chung chi GHIM SPKI (lối
 * `test_artifact_origin.mjs`). Mobile = `--form-factor` mac dinh cua Lighthouse
 * 12 (`--preset=mobile` cua §2.3 khong ton tai — do 2026-10-15).
 *
 * Phien: stdin `{"refresh", "share"}` tu `scripts/s8_session.py`. Puppeteer
 * goi `/auth/refresh` ⇒ cookie `scarlet_session`; duong trong `logged_in` mo
 * kem cookie ay qua `--extra-headers` (tep tam, khong argv). Cuoi cung
 * `/auth/logout` ⇒ thu hoi ca family.
 *
 * Duong va nguong: `config/audit.json` khoi `s8` (A3). Ma thoat = so duong truot.
 */

import { execFile } from "node:child_process";
import { createHash, X509Certificate } from "node:crypto";
import { readFileSync, rmSync, writeFileSync } from "node:fs";

import puppeteer from "puppeteer-core";

const CERT = "certs/nginx.pem";
const HEADERS_FILE = "/tmp/s8-headers.json";

const config = JSON.parse(readFileSync("config/audit.json", "utf8"));
const { routes, logged_in: loggedInRoutes, min_scores: minScores, timeout_s: timeoutS } = config.s8;
const timeoutMs = timeoutS * 1000;
const base = process.env.PUBLIC_BASE_URL;
if (!base) {
  console.error("thieu bien moi truong PUBLIC_BASE_URL");
  process.exit(1);
}

let stdin = "";
for await (const chunk of process.stdin) stdin += chunk;
const { refresh, share } = JSON.parse(stdin);
const spki = createHash("sha256")
  .update(new X509Certificate(readFileSync(CERT)).publicKey.export({ type: "spki", format: "der" }))
  .digest("base64");
const chromeFlags = [
  "--headless=new",
  "--no-sandbox",
  "--disable-dev-shm-usage",
  "--disable-gpu",
  `--ignore-certificate-errors-spki-list=${spki}`,
];

function lighthouse(url, extraArgs) {
  const args = [
    url,
    "--quiet",
    "--output=json",
    "--output-path=stdout",
    "--only-categories=performance,accessibility",
    `--chrome-flags=${chromeFlags.join(" ")}`,
    ...extraArgs,
  ];
  return new Promise((resolve) => {
    execFile("lighthouse", args, { timeout: timeoutMs, maxBuffer: 256 * 1024 * 1024 }, (error, out, err) =>
      resolve(error ? { error: `${error.killed ? "qua han" : `thoat ${error.code}`}: ${err.trim().split("\n").pop()}` } : { report: JSON.parse(out) }),
    );
  });
}

const kb = (bytes) => `${(bytes / 1024).toFixed(1)} kB`;

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH,
  args: ["--no-sandbox", "--disable-dev-shm-usage", `--ignore-certificate-errors-spki-list=${spki}`],
});
const page = await browser.newPage();
let failures = 0;
try {
  await page.setCookie({
    name: "scarlet_refresh",
    value: refresh,
    domain: new URL(base).hostname,
    path: "/api/v1/auth",
    secure: true,
    httpOnly: true,
    sameSite: "Lax",
  });
  await page.goto(`${base}/api/v1/models`, { waitUntil: "domcontentloaded" });
  const login = await page.evaluate(async () => (await fetch("/api/v1/auth/refresh", { method: "POST" })).status);
  if (login !== 200) throw new Error(`/auth/refresh ⇒ ${login}`);
  const session = (await page.cookies()).find((c) => c.name === "scarlet_session");
  writeFileSync(HEADERS_FILE, JSON.stringify({ Cookie: `scarlet_session=${session.value}` }), { mode: 0o600 });

  console.log(`S8 · ${base} · Lighthouse mobile · nguong ${JSON.stringify(minScores)}`);
  for (const route of routes) {
    const path = route.replace("{share}", share);
    const shown = route.replace("{share}", `${share.slice(0, 6)}…`);
    const loggedIn = loggedInRoutes.includes(route);
    const result = await lighthouse(`${base}${path}`, loggedIn ? [`--extra-headers=${HEADERS_FILE}`] : []);
    if (result.error) {
      failures += 1;
      console.log(`${shown}: LOI ${result.error}`);
      continue;
    }
    const { categories, audits, finalDisplayedUrl } = result.report;
    const scores = Object.fromEntries(Object.keys(minScores).map((k) => [k, Math.round(categories[k].score * 100)]));
    const scripts = audits["network-requests"].details.items.filter((r) => r.resourceType === "Script");
    const jsBytes = scripts.reduce((sum, r) => sum + r.transferSize, 0);
    const ok = Object.entries(minScores).every(([k, min]) => scores[k] >= min);
    // Duong dang nhap ma bi day ve /dang-nhap = do nham trang (phien hong).
    const landed = new URL(finalDisplayedUrl).pathname;
    const sameRoute = landed === path;
    if (!ok || !sameRoute) failures += 1;
    console.log(
      `${shown}${loggedIn ? " (đăng nhập)" : ""}: performance ${scores.performance} · accessibility ${scores.accessibility}` +
        ` · LCP ${(audits["largest-contentful-paint"].numericValue / 1000).toFixed(2)} s` +
        ` · TBT ${Math.round(audits["total-blocking-time"].numericValue)} ms` +
        ` · JS ${scripts.length} tệp ${kb(jsBytes)} (truyền)` +
        `${sameRoute ? "" : ` · LANDED ${landed}`} ⇒ ${ok && sameRoute ? "đạt" : "TRƯỢT"}`,
    );
  }
} finally {
  rmSync(HEADERS_FILE, { force: true });
  const logout = await page.evaluate(async () => (await fetch("/api/v1/auth/logout", { method: "POST" })).status);
  console.log(`logout ${logout}`);
  await browser.close();
}
console.log(failures === 0 ? "S8 đạt" : `S8 TRƯỢT — ${failures} đường`);
process.exit(failures);
