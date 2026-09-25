import { Check } from "lucide";
import { useCallback, useEffect, useId, useState, type FormEvent, type ReactNode } from "react";

import { useSession } from "../../app/Layout";
import { toApiError, useResource } from "../../features/admin/useResource";
import { api } from "../../lib/api";
import { t } from "../../lib/i18n";
import { StaticIcon } from "../ui/Icon";
import { SaveRow } from "./SaveRow";
import { saveErrorText } from "./saveError";

/**
 * Tab Model — model mac dinh cua TAI KHOAN. T-S.11, ban T-HD9 C.
 *
 * KH tham chieu: §9.2, §18.4, UC-05 dong 4 · tasks.md T-3.0, T-3.6, T-3.12, T-S.11.
 *
 * Luu qua `changeDefaultModel` ⇒ `saveSettings`: body DU bon truong (Cam bay ①).
 *
 * ── Hang "Theo mac dinh cua he thong" (chot 2026-09-26) ────────────────────
 *
 * Ban ve chi co cac model; trang T-3.12 co them lua chon `null` (bo chon, quay
 * ve `default: true` cua catalog — §9.2). Bo no thi nguoi da chon mot model
 * khong bao gio bo chon duoc qua giao dien, nen hang dau giu lua chon ay, dung
 * kieu hang 64 px cua ban ve. Dong phu la ten model catalog dang mac dinh.
 *
 * Model `available: false` (UC-05 dong 2 — "hien xam", khong bien mat): nen
 * `surface-disabled`, vong chon net dut, `input disabled`. Model dang la mac
 * dinh ma tam khong dung duoc van hien DANG CHON — noi that ve gia tri da luu.
 */

type RowState = "selected" | "idle" | "off";

export function ModelPanel() {
  const session = useSession();
  const loadModels = useCallback(() => api.listModels(), []);
  const models = useResource(loadModels);
  const current = session.profile?.default_model ?? null;
  const [value, setValue] = useState<string | null>(current);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const groupName = useId();

  // `/auth/me` ve SAU lan render dau (Layout hoi luc mount), va sau khi luu.
  useEffect(() => {
    setValue(current);
  }, [current]);

  const choose = (next: string | null) => {
    setValue(next);
    setSaved(false);
    setError(null);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await session.changeDefaultModel(value);
      setSaved(true);
    } catch (err) {
      setError(saveErrorText(toApiError(err)));
    } finally {
      setSaving(false);
    }
  };

  const catalogDefault = models.data?.find((m) => m.default)?.display_name ?? "";

  return (
    <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-5">
      <fieldset className="flex min-w-0 flex-col gap-2.5">
        <legend className="text-sm font-semibold">{t("settings.model.accountDefault")}</legend>
        <span className="text-sm text-muted">{t("model.tierOrder")}</span>
        <div className="flex flex-col gap-px overflow-hidden rounded-lg border border-border bg-divider">
          <ModelRow
            groupName={groupName}
            state={value === null ? "selected" : "idle"}
            name={t("settings.model.catalogDefault")}
            detail={catalogDefault}
            onChoose={() => choose(null)}
          />
          {(models.data ?? []).map((m) => (
            <ModelRow
              key={m.id}
              groupName={groupName}
              state={m.id === value ? "selected" : m.available ? "idle" : "off"}
              name={m.display_name}
              detail={m.provider}
              onChoose={() => choose(m.id)}
            />
          ))}
        </div>
      </fieldset>
      <SaveRow dirty={value !== current} saving={saving} saved={saved} error={error} />
    </form>
  );
}

const ROW_CLASS: Record<RowState, string> = {
  selected: "bg-accent-subtle",
  idle: "bg-surface-panel hover:bg-surface-hover",
  off: "bg-surface-disabled text-disabled-foreground",
};

const RING_CLASS: Record<RowState, string> = {
  selected: "border-accent",
  idle: "border-border-strong",
  off: "border-dashed border-disabled-foreground",
};

function ModelRow({
  groupName,
  state,
  name,
  detail,
  onChoose,
}: {
  groupName: string;
  state: RowState;
  name: string;
  detail: ReactNode;
  onChoose: () => void;
}) {
  return (
    <label
      className={`relative flex min-h-row-model items-center gap-3.5 px-4 has-[:focus-visible]:outline-2 has-[:focus-visible]:-outline-offset-2 has-[:focus-visible]:outline-ring ${ROW_CLASS[state]}`}
    >
      <input
        type="radio"
        name={groupName}
        checked={state === "selected"}
        disabled={state === "off"}
        onChange={onChoose}
        className="sr-only"
      />
      <span
        aria-hidden="true"
        className={`grid size-5 shrink-0 place-items-center rounded-full border-2 ${RING_CLASS[state]}`}
      >
        {state === "selected" && <span className="size-2.5 rounded-full bg-accent" />}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={state === "selected" ? "text-base font-semibold" : "text-base font-medium"}>
          {name}
        </span>
        <span className={state === "off" ? "text-xs" : "text-xs text-muted"}>{detail}</span>
      </span>
      {state === "selected" && (
        <StaticIcon icon={Check} size={18} strokeWidth={2.5} className="shrink-0 text-accent-text" />
      )}
      {state === "off" && <span className="shrink-0 text-xs">{t("model.unavailable")}</span>}
    </label>
  );
}
