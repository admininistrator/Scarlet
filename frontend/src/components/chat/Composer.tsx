import { useState } from "react";
import { t } from "../../lib/i18n";

/**
 * O nhap + nut Gui/Dung — tasks.md T-1.14 ("Nut gui → Dung trong luc stream").
 *
 * MOT nut, hai nghia, va do la co y: hai nut canh nhau thi luon co mot cai vo
 * nghia dang bat, va nguoi dung phai doc de biet cai nao. Nut doi chu theo
 * `dangChay` — thu do den tu event `done`/`error` cua §7.4 chu khong tu mot
 * bo dem thoi gian nao.
 */
export function Composer({
  dangChay,
  moDuoc,
  onGui,
  onDung,
}: {
  dangChay: boolean;
  moDuoc: boolean;
  onGui: (noiDung: string) => void;
  onDung: () => void;
}) {
  const [ban, setBan] = useState("");

  function gui(): void {
    if (ban.trim() === "") {
      return;
    }
    onGui(ban);
    setBan("");
  }

  return (
    <form
      className="flex flex-col gap-2 border-t border-border px-6 py-4"
      onSubmit={(e) => {
        e.preventDefault();
        gui();
      }}
    >
      <textarea
        value={ban}
        onChange={(e) => setBan(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            gui();
          }
        }}
        rows={3}
        disabled={!moDuoc}
        placeholder={t("chat.oNhap")}
        className="w-full rounded-md border border-border bg-background p-2 text-foreground disabled:opacity-50"
      />
      <div>
        {dangChay ? (
          <button
            type="button"
            onClick={onDung}
            className="rounded-md border border-border px-3 py-1.5 text-sm text-danger-emphasis"
          >
            {t("chat.dung")}
          </button>
        ) : (
          <button
            type="submit"
            disabled={!moDuoc}
            className="rounded-md border border-border px-3 py-1.5 text-sm text-foreground hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
          >
            {t("chat.gui")}
          </button>
        )}
      </div>
    </form>
  );
}
