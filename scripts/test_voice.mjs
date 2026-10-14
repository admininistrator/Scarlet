#!/usr/bin/env node
/**
 * Mic + Doc to tren trinh duyet THAT, qua Nginx (https) — T-8.4, ADR-13, §16.2,
 * §24.3 P8 ("Firefox khong hien nut voice — khong phai nut chet").
 *
 *     make test-voice
 *
 * Chay trong image `audit` (Chromium + Firefox ESR + `puppeteer-core` ghim),
 * CHUNG netns voi `nginx` (service `artifact-origin`): `https://localhost` la
 * Nginx that — secure context, khong phai `http://web:5173` cua `make audit`
 * (Cam bay ⑤).
 *
 * Phien: stdin `{"refresh", "conversation_id"}` tu `scripts/voice_session.py`.
 * Chromium goi `/auth/refresh` MOT lan roi CHEP cookie sang Firefox — refresh
 * token xoay vong, dung lai lan hai la tu thu hoi family. Cuoi cung
 * `/auth/logout` ⇒ thu hoi ca family.
 *
 * Container khong mic, khong giong (do): Chromium tra `not-allowed` va
 * `synthesis-failed` ⇒ do DUONG LOI + spy, khong "nghe thay tieng" (Cam bay ②).
 * Probe 375 "dang nghe" thay `SpeechRecognition` bang ban gia KHONG BAO GIO
 * loi (chi de giu trang thai nghe + chu tam dai) — mic that cua container tu
 * choi sau ~53 ms.
 *
 * Firefox: `browser: "firefox"` (WebDriver BiDi). BiDi khong co co ghim SPKI
 * nhu Chromium ⇒ `acceptInsecureCerts` (chi cho lan chay nay).
 *
 * Ma thoat = so dong HONG.
 */

import { createHash, X509Certificate } from "node:crypto";
import { readFileSync } from "node:fs";

import puppeteer from "puppeteer-core";

const CERT = "certs/nginx.pem";
const LOAD_TIMEOUT_MS = 15_000;
const MIC = "Nhập bằng giọng nói";
const READ = "Đọc to";
const DENIED = "Chưa có quyền dùng micro";
const READ_FAILED = "Không đọc được";

function required(name) {
  const value = process.env[name];
  if (!value) {
    console.error(`thieu bien moi truong ${name}`);
    process.exit(1);
  }
  return value;
}

const PUBLIC_BASE_URL = required("PUBLIC_BASE_URL");
const CHROME_PATH = required("CHROME_PATH");
const FIREFOX_PATH = required("FIREFOX_PATH");

let stdin = "";
for await (const chunk of process.stdin) stdin += chunk;
const session = JSON.parse(stdin);
const CHAT_URL = `${PUBLIC_BASE_URL}/?c=${encodeURIComponent(session.conversation_id)}`;
const spki = createHash("sha256")
  .update(new X509Certificate(readFileSync(CERT)).publicKey.export({ type: "spki", format: "der" }))
  .digest("base64");

let failures = 0;
function line(ok, label, detail) {
  if (!ok) failures += 1;
  console.log(`${ok ? "đạt " : "HỎNG"}  ${label}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
}

/** Cho hang nut cua cau tra loi la (nut "Thu lai" la nut that dau tien cua T-3.7). */
async function openChat(page) {
  await page.goto(CHAT_URL, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelector('button[aria-label="Thử lại"]') !== null, {
    timeout: LOAD_TIMEOUT_MS,
  });
}

/** Feature-detect cua trang + hai nut, cung mot ham cho ca hai trinh duyet. */
const detect = (mic, read) => ({
  SpeechRecognition: typeof window.SpeechRecognition,
  webkitSpeechRecognition: typeof window.webkitSpeechRecognition,
  speechSynthesis: typeof window.speechSynthesis,
  isSecureContext: window.isSecureContext,
  micButton: document.querySelector(`button[aria-label="${mic}"]`)?.outerHTML.match(/^<[^>]*>/)[0] ?? null,
  readAloudButtons: document.querySelectorAll(`button[aria-label="${read}"]`).length,
  planned: document.querySelectorAll('[data-planned="T-8.4"]').length,
});

/** NQ-103 — phan tu cua o nhap + cau loi tran khoi be ngang man. */
const overflowProbe = () => {
  const vw = document.documentElement.clientWidth;
  const probed = [...document.querySelectorAll("form, form *")].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  const over = probed
    .filter((el) => {
      const r = el.getBoundingClientRect();
      return r.right > vw + 0.5 || r.left < -0.5;
    })
    .map((el) => el.outerHTML.match(/^<[^>]*>/)[0]);
  return { vw, scrollWidth: document.documentElement.scrollWidth, probed: probed.length, over };
};

const chromium = await puppeteer.launch({
  executablePath: CHROME_PATH,
  args: ["--no-sandbox", "--disable-dev-shm-usage", `--ignore-certificate-errors-spki-list=${spki}`],
});
const page = await chromium.newPage();
await page.setViewport({ width: 1440, height: 900 });
let loggedIn = false;
try {
  await page.setCookie({
    name: "scarlet_refresh",
    value: session.refresh,
    domain: new URL(PUBLIC_BASE_URL).hostname,
    path: "/api/v1/auth",
    secure: true,
    httpOnly: true,
    sameSite: "Lax",
  });
  await page.goto(`${PUBLIC_BASE_URL}/api/v1/models`, { waitUntil: "domcontentloaded" });
  const login = await page.evaluate(async () => (await fetch("/api/v1/auth/refresh", { method: "POST" })).status);
  if (login !== 200) throw new Error(`/auth/refresh ⇒ ${login}`);
  loggedIn = true;
  console.log(`hội thoại ${session.conversation_id}`);

  // ── Chromium 1440: doi chung feature-detect ─────────────────────────────
  await openChat(page);
  const chromeDetect = await page.evaluate(detect, MIC, READ);
  line(
    chromeDetect.micButton !== null && chromeDetect.readAloudButtons > 0 && chromeDetect.planned === 0,
    `Chromium ${await chromium.version()} @1440 — mic CÓ, Đọc to có, [data-planned="T-8.4"] = 0`,
    chromeDetect,
  );

  // ── Mic: container khong mic ⇒ `not-allowed` ⇒ cau loi, nut ve nghi ────
  const mic = await page.evaluate(
    async (mic, denied, timeout) => {
      const started = performance.now();
      document.querySelector(`button[aria-label="${mic}"]`).click();
      const sawStop = document.querySelector('button[aria-label="Dừng nghe"]') !== null;
      while (performance.now() - started < timeout) {
        const alert = [...document.querySelectorAll('[role="alert"]')].find((el) => el.textContent.includes(denied));
        if (alert) {
          await new Promise((r) => setTimeout(r, 50));
          return {
            alert: alert.textContent,
            ms: Math.round(performance.now() - started),
            listeningAfterClick: sawStop,
            idleAgain: document.querySelector(`button[aria-label="${mic}"]`) !== null,
            stillListening: document.querySelector('button[aria-label="Dừng nghe"]') !== null,
          };
        }
        await new Promise((r) => setTimeout(r, 5));
      }
      return null;
    },
    MIC,
    DENIED,
    LOAD_TIMEOUT_MS,
  );
  line(mic !== null && mic.idleAgain && !mic.stillListening, "mic bấm ⇒ not-allowed ⇒ câu lỗi + về nghỉ", mic);

  // ── Doc to: spy `speak`, doc cau tra loi la ─────────────────────────────
  const read = await page.evaluate(
    async (read, failed, timeout) => {
      const spoken = [];
      const original = speechSynthesis.speak.bind(speechSynthesis);
      speechSynthesis.speak = (u) => {
        spoken.push(u);
        original(u);
      };
      const button = [...document.querySelectorAll(`button[aria-label="${read}"]`)].at(-1);
      const article = button.closest("article");
      const codeLine = article
        .querySelector("figure pre")
        ?.textContent.split("\n")
        .find((l) => l.trim().length > 8)
        ?.trim();
      const voices = speechSynthesis.getVoices().length;
      button.click();
      const pressed = button.getAttribute("aria-pressed");
      const started = performance.now();
      while (performance.now() - started < timeout) {
        const alert = [...article.querySelectorAll('[role="alert"]')].find((el) => el.textContent.includes(failed));
        if (alert) break;
        await new Promise((r) => setTimeout(r, 5));
      }
      const u = spoken[0];
      return {
        speakCalls: spoken.length,
        locale: u?.lang,
        voice: u?.voice?.name ?? null,
        voices,
        textLength: u?.text.length,
        textHead: u?.text.slice(0, 60),
        codeLine,
        includesCodeLine: codeLine === undefined ? null : u?.text.includes(codeLine),
        pressedAfterClick: pressed,
        alert: article.querySelector('[role="alert"]')?.textContent ?? null,
        idleAgain: button.getAttribute("aria-label") === read && button.getAttribute("aria-pressed") === "false",
      };
    },
    READ,
    READ_FAILED,
    LOAD_TIMEOUT_MS,
  );
  line(
    read.speakCalls === 1 &&
      read.locale === "vi-VN" &&
      read.textLength > 0 &&
      typeof read.codeLine === "string" &&
      read.includesCodeLine === false &&
      read.idleAgain &&
      read.alert !== null,
    "Đọc to ⇒ một utterance vi-VN, không chứa dòng của khối mã; synthesis-failed ⇒ về nghỉ + câu lỗi",
    read,
  );

  // ── 375: menu "…" mo ⇒ khong nut cho; dang nghe ⇒ khong tran ngang ─────
  await page.setViewport({ width: 375, height: 812 });
  await openChat(page);
  const more = await page.$$('button[aria-label="Thêm thao tác"]');
  await more.at(-1).click();
  await page.waitForSelector('[role="menu"]', { timeout: LOAD_TIMEOUT_MS });
  const menu = await page.evaluate((read) => {
    const items = [...document.querySelectorAll('[role="menu"] [role="menuitem"]')].map((el) => el.textContent.trim());
    return {
      items,
      readAloudItem: items.includes(read),
      planned: document.querySelectorAll('[data-planned="T-8.4"]').length,
    };
  }, READ);
  line(menu.readAloudItem && menu.planned === 0, '375 menu "…" mở — mục Đọc to thật, [data-planned="T-8.4"] = 0', menu);
  await page.keyboard.press("Escape");

  await page.evaluate(() => {
    class Listening {
      start() {
        setTimeout(() => {
          const transcript =
            "đây là một câu đang nói dở rất dài để xem chữ tạm có tràn ra ngoài khung ô nhập ở bề ngang ba trăm bảy mươi lăm điểm ảnh không";
          this.onresult?.({ resultIndex: 0, results: [{ isFinal: false, 0: { transcript } }] });
        }, 20);
      }
      stop() {
        this.onend?.();
      }
      abort() {}
    }
    window.SpeechRecognition = Listening;
    window.webkitSpeechRecognition = Listening;
  });
  // `el.click()` chu khong `page.click`: menu Radix vua dong con giu
  // `pointer-events: none` tren body trong luc animation ra.
  await page.$eval(`button[aria-label="${MIC}"]`, (el) => el.click());
  await page.waitForSelector('button[aria-label="Dừng nghe"]', { timeout: LOAD_TIMEOUT_MS });
  await page.waitForFunction(() => document.querySelector("form p span[aria-hidden]")?.textContent.length > 0);
  const probe = await page.evaluate(overflowProbe);
  line(probe.over.length === 0 && probe.scrollWidth === probe.vw, "375 đang nghe (chữ tạm dài) — probe tràn ngang", probe);

  // ── Firefox ESR: cung man, cung phien (cookie chep tu Chromium) ─────────
  const cookies = (await page.cookies(`${PUBLIC_BASE_URL}/`, `${PUBLIC_BASE_URL}/api/v1/auth/refresh`)).map(
    ({ name, value, domain, path, secure, httpOnly, sameSite, expires }) => ({
      name,
      value,
      domain,
      path,
      secure,
      httpOnly,
      sameSite,
      ...(expires > 0 ? { expires: Math.floor(expires) } : {}),
    }),
  );
  const firefox = await puppeteer.launch({
    browser: "firefox",
    executablePath: FIREFOX_PATH,
    acceptInsecureCerts: true,
  });
  try {
    const fx = await firefox.newPage();
    await fx.setViewport({ width: 1440, height: 900 });
    await fx.goto(`${PUBLIC_BASE_URL}/api/v1/models`, { waitUntil: "domcontentloaded" });
    await fx.setCookie(...cookies);
    await openChat(fx);
    const fxDetect = await fx.evaluate(detect, MIC, READ);
    line(
      fxDetect.micButton === null && fxDetect.readAloudButtons > 0 && fxDetect.planned === 0,
      `Firefox ${await firefox.version()} @1440 — mic null, Đọc to CÓ`,
      fxDetect,
    );
  } finally {
    await firefox.close();
  }
} catch (e) {
  line(false, "chạy", `${e.name}: ${e.message}`);
} finally {
  if (loggedIn) {
    const out = await page.evaluate(async () => (await fetch("/api/v1/auth/logout", { method: "POST" })).status);
    console.log(`logout ⇒ ${out}`);
  }
  await chromium.close();
}
console.log(failures === 0 ? "T-8.4 voice: đạt" : `T-8.4 voice: ${failures} dòng HỎNG`);
process.exit(failures);
