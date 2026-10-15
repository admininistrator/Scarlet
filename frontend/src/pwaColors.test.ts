/**
 * T-8.8 — ban chep mau PWA khop theme.css (A3; theo `pwaColors.test.ts` cua T-HD12 · v1).
 * manifest, `<meta name="theme-color">` va favicon SVG khong doc duoc var(), nen hex
 * duoc CHEP tu theme.css; ai doi mau nen / accent ma quen ban chep thi ca nay do.
 *   theme_color = background_color = --color-background (sang)
 *   theme-color cua index.html = --color-background (sang · [data-theme="dark"])
 *   favicon(-dark).svg: <rect fill> = --color-accent, <path stroke> = --color-accent-foreground
 */
import { describe, expect, it } from "vitest";

import indexHtml from "../index.html?raw";
import faviconDark from "../public/favicon-dark.svg?raw";
import favicon from "../public/favicon.svg?raw";
import manifestRaw from "../public/manifest.webmanifest?raw";
import theme from "./styles/theme.css?raw";

/** Than cua khoi dau tien mo bang `opener` (dem ngoac, vi @theme co khoi long). */
function block(css: string, opener: RegExp): string {
  const m = opener.exec(css);
  if (!m) throw new Error(`khong thay khoi ${opener}`);
  let depth = 0;
  for (let i = m.index + m[0].length - 1; i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}" && --depth === 0) return css.slice(m.index + m[0].length, i);
  }
  throw new Error(`khoi ${opener} khong dong`);
}

const hex = (body: string, name: string) => {
  const m = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`).exec(body);
  if (!m) throw new Error(`thieu ${name}`);
  return m[1].toLowerCase();
};

/** Gia tri hex cua thuoc tinh `name` tren the `<tag …>` dau tien. */
const attr = (svg: string, tag: string, name: string) => {
  const el = new RegExp(`<${tag}\\b[^>]*>`).exec(svg)?.[0] ?? "";
  return new RegExp(`\\b${name}="(#[0-9a-fA-F]{6})"`).exec(el)?.[1].toLowerCase();
};

const metaThemeColor = (scheme: string) =>
  new RegExp(`<meta name="theme-color" media="\\(prefers-color-scheme: ${scheme}\\)" content="(#[0-9a-fA-F]{6})"`)
    .exec(indexHtml)?.[1]
    .toLowerCase();

const light = block(theme, /@theme\s*\{/);
const dark = block(theme, /\[data-theme="dark"\]\s*\{/);
const manifest = JSON.parse(manifestRaw) as { theme_color: string; background_color: string };

describe("PWA khop theme.css", () => {
  it("manifest: theme_color va background_color = --color-background (sang)", () => {
    expect(manifest.theme_color.toLowerCase()).toBe(hex(light, "--color-background"));
    expect(manifest.background_color.toLowerCase()).toBe(hex(light, "--color-background"));
  });

  it("index.html: theme-color sang / toi = --color-background cua tung theme", () => {
    expect(metaThemeColor("light")).toBe(hex(light, "--color-background"));
    expect(metaThemeColor("dark")).toBe(hex(dark, "--color-background"));
  });

  it("favicon.svg / favicon-dark.svg: nen = --color-accent, chu S = --color-accent-foreground", () => {
    expect(attr(favicon, "rect", "fill")).toBe(hex(light, "--color-accent"));
    expect(attr(favicon, "path", "stroke")).toBe(hex(light, "--color-accent-foreground"));
    expect(attr(faviconDark, "rect", "fill")).toBe(hex(dark, "--color-accent"));
    expect(attr(faviconDark, "path", "stroke")).toBe(hex(dark, "--color-accent-foreground"));
  });
});
