/**
 * Renderer markdown — DoD dong 1 va dong 2 cua T-3.5.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  VI SAO CO MOT KHOI "CA AM" O CUOI FILE                                ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * DoD viet: *"Mot bo test XSS xanh ca khi khong co sanitizer la mot bo test
 * dang do cho khac"*. Doi voi cach dung o day — `react-markdown` KHONG kem
 * `rehype-raw` — cau ay can duoc doc cho dung, vi bien phong thu la BA lop
 * chu khong mot:
 *
 *   1. HTML tho khong bao gio duoc phan tich  ← manh nhat
 *   2. allowlist the/thuoc tinh cua `rehype-sanitize`
 *   3. allowlist giao thuc URL (`safeUrl`)
 *
 * Go rieng lop 2 ra thi lop 1 van do duoc bon trong nam ca, nen phep thu ay
 * khong noi len dieu gi. Phep thu noi len dieu gi la go **ca ba** — dung mot
 * renderer khong phong thu, co `rehype-raw`, khong `rehype-sanitize`, khong
 * `urlTransform` — va chung minh nam chuoi tan cong kia THAT SU chay duoc
 * tren mot renderer nhu vay. Do la khoi cuoi cung cua file nay, va no chay
 * mai mai chu khong phai mot lan sua tay roi quen.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import { describe, expect, it, vi } from "vitest";

import { Markdown } from "./Markdown";
import { safeUrl } from "./markdownPolicy";

/** Nam chuoi tan cong ma DoD dong 1 goi ten. */
const ATTACKS = {
  imgOnerror: '<img src=x onerror=alert(1)>',
  script: "<script>alert(1)</script>",
  javascriptUrl: "[bam vao day](javascript:alert(1))",
  dataUrl: '<a href="data:text/html,<script>alert(1)</script>">bam</a>',
  iframe: '<iframe src="https://ke-tan-cong.example/x"></iframe>',
} as const;

function renderSettled(text: string) {
  return render(<Markdown text={text} streaming={false} />);
}

// ──────────────────────────── markdown chay dung ────────────────────────────

describe("markdown", () => {
  it("1 — dung <strong> va <em>", () => {
    const { container } = renderSettled("Mot cau **dam** va mot cau *nghieng*.");
    expect(container.querySelector("strong")).toHaveTextContent("dam");
    expect(container.querySelector("em")).toHaveTextContent("nghieng");
  });

  it("2 — dung tieu de", () => {
    renderSettled("## Han muc thang nay");
    expect(screen.getByRole("heading", { name: "Han muc thang nay" })).toBeInTheDocument();
  });

  it("3 — dung danh sach", () => {
    const { container } = renderSettled("- mot\n- hai\n- ba");
    expect(container.querySelectorAll("li")).toHaveLength(3);
  });

  it("4 — dung <table> khi bang DA DU hang phan cach (remark-gfm)", () => {
    const { container } = renderSettled("| Ten | Han muc |\n| --- | --- |\n| Bob | 100 |");
    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelectorAll("th")).toHaveLength(2);
  });

  it("5 — lien ket https mo tab moi va mang rel day du", () => {
    renderSettled("[trang chu](https://scarlet.example/tai-lieu)");
    const a = screen.getByRole("link", { name: "trang chu" });
    expect(a).toHaveAttribute("href", "https://scarlet.example/tai-lieu");
    expect(a).toHaveAttribute("target", "_blank");
    expect(a.getAttribute("rel")).toContain("noopener");
  });

  it("6 — code noi dong khong bien thanh khoi code", () => {
    const { container } = renderSettled("Chay lenh `docker compose up -d` truoc.");
    expect(container.querySelector("code")).toHaveTextContent("docker compose up -d");
    expect(container.querySelector("figure")).toBeNull();
  });

  it("7 — giu nguyen tieng Viet co dau va emoji", () => {
    const { container } = renderSettled("Đã lưu hạn mức của người dùng 🎉");
    expect(container.textContent).toContain("Đã lưu hạn mức của người dùng 🎉");
  });

  it("8 — blockquote", () => {
    const { container } = renderSettled("> mot trich dan");
    expect(container.querySelector("blockquote")).toHaveTextContent("mot trich dan");
  });
});

// ───────────────────────── khoi code trong markdown ─────────────────────────

describe("khoi code", () => {
  it("9 — nhan ngon ngu, so dong khong nam trong DOM text, co nut Copy", () => {
    const { container } = renderSettled("```typescript\nconst a = 1;\nconst b = 2;\n```");
    expect(screen.getByText("typescript")).toBeInTheDocument();

    const lines = container.querySelectorAll(".code-line");
    expect(lines).toHaveLength(2);
    // So dong den tu counter() trong ::before — khong mot chu so nao o DOM.
    expect(lines[0].textContent).toBe("const a = 1;\n");
    expect(lines[1].textContent).toBe("const b = 2;");

    expect(screen.getByRole("button", { name: "Sao chép code" })).toBeInTheDocument();
  });

  it("10 — to mau cu phap: khoi da dong co lop .tk-*", () => {
    const { container } = renderSettled("```typescript\nconst a = 1;\n```");
    expect(container.querySelector(".tk-keyword")).toHaveTextContent("const");
    expect(container.querySelector(".tk-number")).toHaveTextContent("1");
  });

  it("11 — ngon ngu khong biet van co so dong, chi la khong co mau", () => {
    const { container } = renderSettled("```khongtontai\nabc\n```");
    expect(container.querySelectorAll(".code-line")).toHaveLength(1);
    expect(container.querySelector(".tk-keyword")).toBeNull();
  });
});

// ──────────────────── render tang dan — markdown chua dong ──────────────────

describe("markdown chua dong", () => {
  it("12 — hang ``` chua dong: vien net dut, KHONG nut Copy, khong to mau", () => {
    const { container } = render(
      <Markdown text={"Chay thu:\n\n```bash\ndocker compose up -d\ndocker compose logs -f sca"} streaming />,
    );
    const figure = container.querySelector("figure");
    expect(figure?.className).toContain("border-dashed");
    expect(screen.queryByRole("button", { name: "Sao chép code" })).toBeNull();
    expect(screen.getByText("Khối code đang mở")).toBeInTheDocument();
    expect(container.querySelector(".tk-function")).toBeNull();
    // Phan chu truoc khoi code van duoc ve binh thuong.
    expect(container.textContent).toContain("Chay thu:");
  });

  it("13 — bang chua du hang phan cach: KHONG dung <table>", () => {
    const { container } = render(
      <Markdown text={"| Nguoi dung | Han muc | Da dung |\n| --- | ---"} streaming />,
    );
    expect(container.querySelector("table")).toBeNull();
    expect(container.textContent).toContain("| --- | ---");
  });

  it("14 — cung chuoi ay luc da xong thi khong bi cat ra nua", () => {
    const { container } = render(
      <Markdown text={"```bash\ndocker compose up -d"} streaming={false} />,
    );
    expect(container.querySelector("figure")?.className).not.toContain("border-dashed");
    expect(screen.getByRole("button", { name: "Sao chép code" })).toBeInTheDocument();
  });
});

// ─────────────────────────── nam ca tan cong (§20) ──────────────────────────

/** Hai khang dinh ma DoD dong 1 doi cho MOI ca. */
function assertNoScript(container: HTMLElement): void {
  expect(container.querySelector("script")).toBeNull();
  expect(container.innerHTML).not.toContain("onerror");
}

describe("XSS — nam ca tan cong", () => {
  it("15 — <img src=x onerror=alert(1)>", () => {
    const { container } = renderSettled(ATTACKS.imgOnerror);
    assertNoScript(container);
    expect(container.querySelector("img")).toBeNull();
  });

  it("16 — <script>alert(1)</script>", () => {
    const { container } = renderSettled(ATTACKS.script);
    assertNoScript(container);
  });

  it("17 — [x](javascript:alert(1))", () => {
    const { container } = renderSettled(ATTACKS.javascriptUrl);
    assertNoScript(container);
    const a = container.querySelector("a");
    expect(a?.getAttribute("href") ?? "").not.toContain("javascript:");
  });

  it('18 — <a href="data:text/html,…">', () => {
    const { container } = renderSettled(ATTACKS.dataUrl);
    assertNoScript(container);
    expect(container.innerHTML).not.toContain("data:text/html");
  });

  it("19 — <iframe src=…>", () => {
    const { container } = renderSettled(ATTACKS.iframe);
    assertNoScript(container);
    expect(container.querySelector("iframe")).toBeNull();
  });

  it("20 — bien the: JaVaScRiPt: co ky tu dieu khien chen giua", () => {
    const { container } = renderSettled("[bam](java\u0000script:alert(1))");
    assertNoScript(container);
    expect(container.querySelector("a")?.getAttribute("href") ?? "").not.toMatch(/javascript/i);
  });

  it("21 — thuoc tinh su kien tren the DUOC PHEP cung bi go", () => {
    const { container } = renderSettled('<p onclick="alert(1)">chu</p>');
    expect(container.innerHTML).not.toContain("onclick");
  });

  it("22 — safeUrl: giu URL tuong doi, bo giao thuc la", () => {
    expect(safeUrl("https://a.example/x")).toBe("https://a.example/x");
    expect(safeUrl("mailto:ai@do.example")).toBe("mailto:ai@do.example");
    expect(safeUrl("#neo")).toBe("#neo");
    expect(safeUrl("/duong-dan")).toBe("/duong-dan");
    expect(safeUrl("javascript:alert(1)")).toBe("");
    expect(safeUrl("data:text/html,<script>alert(1)</script>")).toBe("");
    expect(safeUrl("vbscript:msgbox(1)")).toBe("");
  });
});

// ─────────────────────────────── nut Copy ───────────────────────────────────

describe("nut Copy cua khoi code", () => {
  it("23 — chep dung noi dung code, KHONG kem so dong", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const code = "def cong(a, b):\n    return a + b\n\nprint(cong(1, 2))";
    renderSettled("```python\n" + code + "\n```");

    await userEvent.click(screen.getByRole("button", { name: "Sao chép code" }));

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(code);
    // Khong mot chu so dau dong nao lot vao chuoi da chep.
    expect(writeText.mock.calls[0][0]).not.toMatch(/^\s*1\s*def/);
  });
});

// ───────────────────────────────── CA AM ────────────────────────────────────

/**
 * Renderer KHONG phong thu — ba lop cua `markdownPolicy.ts` deu bi go:
 * `rehype-raw` bat, `rehype-sanitize` khong co, `urlTransform` khong co.
 *
 * Neu mot ngay nao do khoi nay chuyen sang mau xanh cua "khong con tan cong
 * nao chay duoc" thi nam ca o tren khong con do phong thu cua Scarlet nua —
 * chung dang do mot thay doi nao do cua thu vien, va phai viet lai.
 */
function renderUnguarded(text: string) {
  return render(
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      urlTransform={(url) => url}
    >
      {text}
    </ReactMarkdown>,
  );
}

describe("ca am — nam chuoi tren THAT SU la tan cong", () => {
  it("24 — khong phong thu thi <script> vao duoc DOM", () => {
    const { container } = renderUnguarded(ATTACKS.script);
    expect(container.querySelector("script")).not.toBeNull();
  });

  /*
    Do duoc luc viet test nay, va no dang mot dong ghi lai: rieng ca `<img
    onerror>`, chuoi `onerror` KHONG BAO GIO vao duoc DOM trong mot renderer
    React — React tu choi mot listener dang chuoi ("Expected `onError`
    listener to be a function, instead got a value of `string` type") va bo
    thuoc tinh di. Do la mot lop phong thu thu tu, nam trong chinh React, va
    no dung ca khi ba lop cua `markdownPolicy.ts` deu bi go.

    Nen cai ca am nay do duoc — va la cai duy nhat no do duoc — la **the
    <img> co duoc dung hay khong**: khong phong thu thi co, phong thu thi
    khong (ca 15). Khac biet ay moi la thu do allowlist cua Scarlet.
  */
  it("25 — khong phong thu thi the <img> vao duoc DOM", () => {
    const { container } = renderUnguarded(ATTACKS.imgOnerror);
    expect(container.querySelector("img")).not.toBeNull();
  });

  it("26 — khong phong thu thi href javascript: con nguyen", () => {
    const { container } = renderUnguarded(ATTACKS.javascriptUrl);
    expect(container.querySelector("a")?.getAttribute("href")).toContain("javascript:");
  });

  it("27 — khong phong thu thi href data:text/html con nguyen", () => {
    const { container } = renderUnguarded(ATTACKS.dataUrl);
    expect(container.innerHTML).toContain("data:text/html");
  });

  it("28 — khong phong thu thi <iframe> vao duoc DOM", () => {
    const { container } = renderUnguarded(ATTACKS.iframe);
    expect(container.querySelector("iframe")).not.toBeNull();
  });
});
