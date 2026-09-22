import { useCallback, useMemo, useRef, useState } from "react";

import { saoChep } from "../../lib/clipboard";
import { t } from "../../lib/i18n";
import { highlightLines, plainLines, type CodeLine } from "./highlight";

/**
 * Khoi code — ban T-HD3 hinh 2d.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  SO DONG KHONG NAM TRONG DOM TEXT                                      ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Chu so den tu `counter()` trong `::before` (`.code-line` o `theme.css`),
 * khong phai mot cot `<span>` chua chu so. Day la rang buoc ban thiet ke viet
 * hoa: nut Copy phai tra ve code KHONG kem so dong, va cach re nhat de bao
 * dam dieu do la so dong khong ton tai trong `textContent`. Nho vay `onCopy`
 * chi la mot dong `codeRef.current.textContent` — khong co phep cat chuoi nao
 * de mot ngay nao do cat nham.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHOI DANG MO KHAC KHOI DA DONG BA CHO                                 ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `open` = hang ``` dong chua ve (xem `streamingTail.ts`). Khi ay:
 *   • vien net dut + nhan "Khoi code dang mo" — noi ra rang no chua xong;
 *   • KHONG co nut Copy — copy mot khoi code dang do la mot cai bay;
 *   • KHONG to mau — Prism to lai ca khoi o moi lan goi, va o day moi delta
 *     la mot lan goi (309 delta / 3,768 s, T-1.14). To mot lan khi dong.
 *   • cao toi thieu hai dong, nen dong dau tien ve khong lam nhay bo cuc.
 */
export function CodeBlock({
  language,
  code,
  open,
}: {
  language: string;
  code: string;
  /** `true` khi hang ``` dong chua ve — markdown chua dong. */
  open: boolean;
}) {
  const codeRef = useRef<HTMLElement>(null);
  const [copied, setCopied] = useState(false);

  /*
    `useMemo` la phan con lai cua rang buoc hieu nang: mot khoi da dong nam
    truoc con tro tren cung mot message van bi dung lai o moi delta, nhung
    `code` cua no khong doi nen Prism chi chay dung mot lan.
  */
  const lines: CodeLine[] = useMemo(
    () => (open ? plainLines(code) : highlightLines(code, language)),
    [code, language, open],
  );

  /*
    `saoChep` chu khong `navigator.clipboard` truc tiep (T-3.7, Cam bay ③):
    nut Copy duoi cau tra loi dung chung dung ham nay, va duong lui cho ngoai
    secure context chi co MOT ban. "Da sao chep" chi hien khi that su chep
    duoc — `saoChep` tra `false` chu khong nem.
  */
  const onCopy = useCallback(() => {
    const text = codeRef.current?.textContent ?? "";
    void saoChep(text).then((xong) => {
      if (!xong) {
        return;
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    });
  }, []);

  return (
    <figure
      className={
        open
          ? "my-3 overflow-hidden rounded-lg border border-dashed border-border-strong bg-surface-code"
          : "my-3 overflow-hidden rounded-lg border border-border bg-surface-code"
      }
    >
      <figcaption className="flex h-touch items-center gap-2 border-b border-border px-3">
        <span className="font-mono text-2xs tracking-wider uppercase text-muted">
          {language === "" ? t("code.plain") : language}
        </span>
        {open ? (
          <span className="text-2xs text-muted">{t("code.streaming")}</span>
        ) : (
          <button
            type="button"
            onClick={onCopy}
            className="ml-auto h-touch rounded-md px-3 text-sm font-medium text-foreground hover:bg-surface-hover motion-control"
          >
            {copied ? t("code.copied") : t("code.copy")}
          </button>
        )}
      </figcaption>

      <pre className={open ? "code-lines m-0 min-h-15 py-3 text-sm leading-6" : "code-lines m-0 py-3 text-sm leading-6"}>
        <code ref={codeRef} className="font-mono text-foreground">
          {lines.map((line, index) => (
            // Mot phan tu moi dong; chu so den tu ::before, khong phai o day.
            <span key={index} className="code-line px-3">
              {line.map((piece, j) =>
                piece.cls === null ? (
                  piece.text
                ) : (
                  <span key={j} className={piece.cls}>
                    {piece.text}
                  </span>
                ),
              )}
              {index < lines.length - 1 ? "\n" : null}
              {open && index === lines.length - 1 ? (
                <span aria-hidden="true" className="caret-stream ml-0.5" />
              ) : null}
            </span>
          ))}
        </code>
      </pre>
    </figure>
  );
}
