#!/usr/bin/env node
/**
 * S12 tu dong — artifact khong doc duoc gi cua origin chinh (§2.3, §14.3,
 * ADR-10). KH tham chieu: tasks.md T-5.6, NQ-142 ④ (Q-P5-4).
 *
 *     make test-artifact-origin
 *
 * Chay trong image `audit` (Chromium + `puppeteer-core` ghim), CHUNG netns voi
 * `nginx` (service `artifact-origin`, `network_mode: service:nginx`): `https://
 * localhost` va `https://artifacts.localhost` toi dung Nginx — CSP va origin
 * deu do Nginx dat, nen khong ne duoc sang `http://web:5173` nhu `audit.mjs`.
 *
 * Chung chi: GHIM dung SPKI cua cert Nginx nap (`--ignore-certificate-errors-
 * spki-list`), khong tat kiem chung chi toan bo. CA mkcert khong o trong
 * container nao.
 *
 * Phien: stdin la `{"refresh", "conversation_id", "title", "version"}` do
 * `scripts/artifact_origin_session.py` phat trong `api`. Trang JSON cong khai
 * goi `/auth/refresh` ⇒ cookie phien (`scarlet_session`, NQ-36), cuoi cung
 * `/auth/logout` ⇒ thu hoi ca family.
 *
 * T-5.5: khung la iframe DO PANEL DUNG, khong tu dung — mo hoi thoai co
 * artifact `html` trong SPA, bam "Mo" tren the, cho panel bao `rendered`
 * (het dai "Dang chay artifact…", khong `alert`). SPA KHONG tu goi
 * `/auth/refresh` (chi `GET /auth/me`), nen dang nhap o trang JSON truoc roi
 * moi sang SPA thi khong co dua "tai su dung" nao.
 *
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │  TAM PHEP THU, MOI PHEP MOT LOP                                          │
 * └──────────────────────────────────────────────────────────────────────────┘
 *
 * Chay TRONG khung (`frame.evaluate`). Moi dong `chan` / `LOT`:
 *   (a) fetch API origin chinh, credentials: include   CSP; CORS; SameSite
 *   (b) fetch('/api/v1/conversations') tuong doi        origin phu khong co API
 *   (c) POST /auth/refresh, credentials: include        CSP; kiem `Origin`
 *   (d) document.cookie                                 sandbox (origin null)
 *   (e) localStorage.length                             sandbox
 *   (f) window.parent.document.title                    khac origin
 *   (g) fetch origin phu, mode: no-cors                 CHI CSP chan duoc
 *   (h) self.origin === 'null'                          sandbox
 * Doi chung o trang cha: `fetch('/api/v1/conversations')` ⇒ 200 + danh sach
 * khong rong — khong co no thi "tam dong chan" co the chi vi phien hong.
 *
 * T-5.7, sau doi chung: `render` HTML chua ma 6 chu so qua `postMessage` (bat
 * tay `ready` → `render` → `rendered`) ⇒ body khung chua ma; (i) mot trang
 * KHAC cung origin chinh `window.open` khung roi gui `render` ⇒ khung khong
 * doi (chi kiem `event.source` cua khung chan duoc).
 *
 * T-5.8, cuoi cung: khung RUNTIME React (`/react` — React 18 UMD + Babel +
 * Tailwind tu CDN) render component in ma sinh luc chay ⇒ body khung chua
 * ma; roi chay lai tam phep thu (a)…(h) TRONG khung ay. Runtime moi nap them
 * ~3.5 MB script khac origin vao khung — moi dong van phai `chan`.
 *
 * Chuoi `sandbox` doc tu `ArtifactFrame.tsx` va doi chieu voi thuoc tinh cua
 * iframe trong panel. Ma thoat = so dong truot (LOT + doi chung hong).
 */

import { createHash, randomInt, X509Certificate } from "node:crypto";
import { readFileSync } from "node:fs";

import puppeteer from "puppeteer-core";

const FRAME_SOURCE = "frontend/ArtifactFrame.tsx";
const CERT = "certs/nginx.pem";
const LOAD_TIMEOUT_MS = 15_000;

function required(name) {
  const value = process.env[name];
  if (!value) {
    console.error(`thieu bien moi truong ${name}`);
    process.exit(1);
  }
  return value;
}

const PUBLIC_BASE_URL = required("PUBLIC_BASE_URL");
const ARTIFACTS_BASE_URL = required("ARTIFACTS_BASE_URL");
// Trang khung theo `kind` (T-5.8): `/html` khong runtime, `/react` co.
const FRAME_URL = `${ARTIFACTS_BASE_URL}/html`;
const REACT_FRAME_URL = `${ARTIFACTS_BASE_URL}/react`;

const sandboxMatch = readFileSync(FRAME_SOURCE, "utf8").match(/ARTIFACT_SANDBOX = "([^"]*)"/);
if (!sandboxMatch) {
  console.error(`khong tim thay ARTIFACT_SANDBOX trong ${FRAME_SOURCE}`);
  process.exit(1);
}
const SANDBOX = sandboxMatch[1];

// KHONG `readFileSync(0)`: stdin la pipe non-blocking, `api` chua kip in ⇒
// EAGAIN (do 2026-10-07, mot lan trong ba).
let stdin = "";
for await (const chunk of process.stdin) stdin += chunk;
const session = JSON.parse(stdin);
const { refresh } = session;
const spki = createHash("sha256")
  .update(new X509Certificate(readFileSync(CERT)).publicKey.export({ type: "spki", format: "der" }))
  .digest("base64");

/** Chay trong khung. Tra `[[nhan, lot, chi tiet], ...]`. */
async function probes(publicBase, artifactsBase) {
  const error = (e) => `${e.name}: ${e.message}`;
  const readJson = async (url, init) => {
    try {
      const res = await fetch(url, init);
      const text = await res.text();
      try {
        JSON.parse(text);
        return [res.ok, `${res.status} JSON`];
      } catch {
        return [false, `${res.status} khong phai JSON`];
      }
    } catch (e) {
      return [false, error(e)];
    }
  };
  const sync = (read) => {
    try {
      return [true, String(read())];
    } catch (e) {
      return [false, error(e)];
    }
  };
  const result = [];
  result.push(["(a)", ...(await readJson(`${publicBase}/api/v1/conversations`, { credentials: "include" }))]);
  result.push(["(b)", ...(await readJson("/api/v1/conversations"))]);
  try {
    const res = await fetch(`${publicBase}/api/v1/auth/refresh`, { method: "POST", credentials: "include" });
    result.push(["(c)", res.status === 200, `${res.status}`]);
  } catch (e) {
    result.push(["(c)", false, error(e)]);
  }
  result.push(["(d)", ...sync(() => `document.cookie dai ${document.cookie.length}`)]);
  result.push(["(e)", ...sync(() => `localStorage.length = ${localStorage.length}`)]);
  result.push(["(f)", ...sync(() => `parent title "${window.parent.document.title}"`)]);
  try {
    await fetch(`${artifactsBase}/`, { mode: "no-cors" });
    result.push(["(g)", true, "fetch no-cors toi duoc"]);
  } catch (e) {
    result.push(["(g)", false, error(e)]);
  }
  result.push(["(h)", self.origin !== "null", `self.origin = ${self.origin}`]);
  return result;
}

const browser = await puppeteer.launch({
  executablePath: required("CHROME_PATH"),
  args: ["--no-sandbox", "--disable-dev-shm-usage", `--ignore-certificate-errors-spki-list=${spki}`],
});
let failures = 0;
const page = await browser.newPage();
let loggedIn = false;
try {
  await page.setCookie({
    name: "scarlet_refresh",
    value: refresh,
    domain: new URL(PUBLIC_BASE_URL).hostname,
    path: "/api/v1/auth",
    secure: true,
    httpOnly: true,
    sameSite: "Lax",
  });
  // Dang nhap o mot trang JSON cong khai, roi moi mo SPA (xem dau tep).
  await page.goto(`${PUBLIC_BASE_URL}/api/v1/models`, { waitUntil: "domcontentloaded" });
  const login = await page.evaluate(async () => (await fetch("/api/v1/auth/refresh", { method: "POST" })).status);
  if (login !== 200) throw new Error(`/auth/refresh o trang cha ⇒ ${login}`);
  loggedIn = true;

  // T-5.5 — iframe THAT cua panel: hoi thoai co artifact `html`, nut "Mo" cua the.
  // Vite HMR khong bao gio `load` xong ⇒ `domcontentloaded` (Cam bay ⑥ T-5.6).
  const label = `Mở ${session.title.replace(/\s+/g, " ").trim()}`;
  console.log(`hội thoại ${session.conversation_id} · thẻ "${label}" v${session.version}`);
  await page.goto(`${PUBLIC_BASE_URL}/?c=${encodeURIComponent(session.conversation_id)}`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    (name, version) =>
      [...document.querySelectorAll("button")].some(
        (b) => b.getAttribute("aria-label") === name && b.parentElement?.textContent?.includes(`v${version}`),
      ),
    { timeout: LOAD_TIMEOUT_MS },
    label,
    session.version,
  );
  await page.evaluate(
    (name, version) =>
      [...document.querySelectorAll("button")]
        .find((b) => b.getAttribute("aria-label") === name && b.parentElement?.textContent?.includes(`v${version}`))
        .click(),
    label,
    session.version,
  );
  // Panel bao `rendered` (khung tra loi bat tay) ⇒ het dai dang nap; `alert` = khung bao loi.
  await page.waitForFunction(
    () => {
      const panel = document.getElementById("artifact-panel");
      return panel?.querySelector("iframe") && !panel.querySelector('[role="status"], [role="alert"]');
    },
    { timeout: LOAD_TIMEOUT_MS },
  );
  const element = await page.$("#artifact-panel iframe");
  const attrs = await element.evaluate((el) => [el.getAttribute("sandbox"), el.getAttribute("src")]);
  const attrsOk = attrs[0] === SANDBOX && attrs[1] === FRAME_URL;
  console.log(`khung   ${attrsOk ? "đạt" : "HỎNG"}  iframe của panel: src ${attrs[1]} · sandbox "${attrs[0]}" (ArtifactFrame.tsx: "${SANDBOX}")`);
  if (!attrsOk) failures += 1;
  const frame = await element.contentFrame();
  if (!frame) throw new Error("khong lay duoc khung cua panel");

  for (const [label, leaked, detail] of await frame.evaluate(probes, PUBLIC_BASE_URL, ARTIFACTS_BASE_URL)) {
    console.log(`${label} ${leaked ? "LỌT" : "chặn"}  ${detail}`);
    if (leaked) failures += 1;
  }

  const control = await page.evaluate(async () => {
    const res = await fetch("/api/v1/conversations");
    return [res.status, res.ok ? (await res.json()).items.length : 0];
  });
  const controlOk = control[0] === 200 && control[1] > 0;
  console.log(`đối chứng ${controlOk ? "đạt" : "HỎNG"}  trang cha GET /api/v1/conversations ⇒ ${control[0]} (${control[1]} hội thoại)`);
  if (!controlOk) failures += 1;

  // T-5.7 — nap noi dung bang `postMessage`, dung bat tay cua `ArtifactFrame.tsx`:
  // listener gan TRUOC khi chen iframe, `render` chi gui sau `ready` tu dung
  // `contentWindow`. Ma sinh luc chay ⇒ `docker compose logs | grep -c <ma>`.
  const code = String(randomInt(100_000, 1_000_000));
  console.log(`mã      ${code}`);
  const reply = await page.evaluate(
    (src, sandbox, content, timeoutMs) =>
      new Promise((resolve) => {
        const frame = document.createElement("iframe");
        frame.id = "render";
        frame.setAttribute("sandbox", sandbox);
        addEventListener("message", (event) => {
          if (event.source !== frame.contentWindow) return;
          if (event.data?.type === "ready") {
            frame.contentWindow.postMessage({ type: "render", kind: "html", content }, "*");
          } else {
            resolve(JSON.stringify(event.data));
          }
        });
        frame.src = src;
        document.body.append(frame);
        setTimeout(() => resolve("hết giờ"), timeoutMs);
      }),
    FRAME_URL,
    SANDBOX,
    `<p>mã ${code}</p>`,
    LOAD_TIMEOUT_MS,
  );
  const rendered = await (await page.$("#render")).contentFrame();
  const text = await rendered.evaluate(() => document.body.innerText);
  const renderOk = reply === '{"type":"rendered"}' && text.includes(code);
  console.log(`render  ${renderOk ? "đạt" : "HỎNG"}  khung trả ${reply}; body ${JSON.stringify(text)}`);
  if (!renderOk) failures += 1;

  // T-5.8 — runtime React: cung bat tay, `kind: "react"`, component dung
  // `React` toan cuc. Tham do chay SAU khi React da render trong khung.
  const reactCode = String(randomInt(100_000, 1_000_000));
  const reactReply = await page.evaluate(
    (src, sandbox, content, timeoutMs) =>
      new Promise((resolve) => {
        const frame = document.createElement("iframe");
        frame.id = "render-react";
        frame.setAttribute("sandbox", sandbox);
        addEventListener("message", (event) => {
          if (event.source !== frame.contentWindow) return;
          if (event.data?.type === "ready") {
            frame.contentWindow.postMessage({ type: "render", kind: "react", content }, "*");
          } else if (event.data?.type !== "alive") {
            resolve(JSON.stringify(event.data));
          }
        });
        frame.src = src;
        document.body.append(frame);
        setTimeout(() => resolve("hết giờ"), timeoutMs);
      }),
    REACT_FRAME_URL,
    SANDBOX,
    `function App() { const [n] = React.useState(${reactCode}); return <p className="p-4">react {n}</p>; }`,
    LOAD_TIMEOUT_MS,
  );
  const reactFrame = await (await page.$("#render-react")).contentFrame();
  const reactText = await reactFrame.evaluate(() => document.body.innerText);
  const reactOk = reactReply === '{"type":"rendered"}' && reactText.includes(`react ${reactCode}`);
  console.log(`react   ${reactOk ? "đạt" : "HỎNG"}  khung ${REACT_FRAME_URL} trả ${reactReply}; body ${JSON.stringify(reactText)}`);
  if (!reactOk) failures += 1;
  for (const [label, leaked, detail] of await reactFrame.evaluate(probes, PUBLIC_BASE_URL, ARTIFACTS_BASE_URL)) {
    console.log(`react${label} ${leaked ? "LỌT" : "chặn"}  ${detail}`);
    if (leaked) failures += 1;
  }

  // (i) Mot trang KHAC cung origin chinh (khong phai cha cua khung) mo khung
  // bang `window.open` roi gui `render` — origin dung, `source` sai. Chi kiem
  // `event.source === window.parent` cua khung chan duoc ca nay.
  const intruderCode = String(randomInt(100_000, 1_000_000));
  const other = await browser.newPage();
  await other.goto(`${PUBLIC_BASE_URL}/api/v1/models`, { waitUntil: "domcontentloaded" });
  const [popup] = await Promise.all([
    new Promise((resolve) => other.once("popup", resolve)),
    other.evaluate((url) => {
      globalThis.opened = window.open(url);
    }, FRAME_URL),
  ]);
  await popup.waitForFunction(() => document.readyState === "complete", { timeout: LOAD_TIMEOUT_MS });
  await other.evaluate((content) => {
    globalThis.opened.postMessage({ type: "render", kind: "html", content }, "*");
  }, `<p>mã ${intruderCode}</p>`);
  await new Promise((resolve) => setTimeout(resolve, 1_000));
  const popupText = await popup.evaluate(() => document.body.innerText);
  const intruded = popupText.includes(intruderCode);
  console.log(`(i) ${intruded ? "LỌT" : "chặn"}  trang khác gửi render vào khung mở bằng window.open ⇒ body ${JSON.stringify(popupText)}`);
  if (intruded) failures += 1;
  await other.close();
} catch (e) {
  console.error(e.message);
  failures += 1;
} finally {
  if (loggedIn) {
    const logout = await page.evaluate(async () => (await fetch("/api/v1/auth/logout", { method: "POST" })).status);
    console.log(`logout ${logout}`);
  }
  await browser.close();
}
console.log(failures === 0 ? "S12 đạt" : `S12 TRƯỢT — ${failures} dòng`);
process.exit(failures);
