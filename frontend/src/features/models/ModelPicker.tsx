/**
 * Model Picker — T-3.6, ban thiet ke T-HD4.
 *
 * KH tham chieu: §9.3, §9.4, UC-05, RR-5 · tasks.md T-3.6 · ADR-16.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHONG MOT ID MODEL NAO TRONG FILE NAY                                 ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Component nhan `models` qua prop va khong so `model.id` voi mot hang chuoi
 * nao. Tang mac dinh cung la du lieu: no chi so `model.id` voi ba gia tri
 * trong `phanTang`. Do la ly do lenh grep cua DoD T-3.6 tra ve rong khi chay
 * tren thu muc nay (A3).
 *
 * ── Hai hinh dang, mot noi dung ───────────────────────────────────────────
 *
 * Desktop la dropdown 384 px neo vao nut; duoi 640 px la **sheet tu day len**.
 * Ba ly do cua ban T-HD4, theo thu tu quan trong:
 *
 *   1. Khong co hover thi khong co tooltip. Ly do khoa la mot cau dai khong
 *      doan truoc, tren cam ung no phai nam THANG trong hang.
 *   2. Nut mo nam sat day man hinh — dropdown se bi ban phim ao de hoac phai
 *      lat huong lien tuc.
 *   3. Bon hang cao 64 px cong strip trang thai da qua nua man hinh 667 px.
 *
 * ── Hang khoa: `aria-disabled`, KHONG phai `disabled` ─────────────────────
 *
 * Hang khong dung duoc giu nguyen `tabIndex 0` va van focus duoc — nguoi dung
 * ban phim phai DOC duoc ly do. `disabled` se lam hang bien mat khoi tab
 * order va khoi screen reader, tuc giau di dung cau can noi.
 *
 * "Khong chon duoc" la that chu khong chi la mo di: hang khoa **khong gan**
 * `onClick`/`onKeyDown` (Cam bay ③). FE khong phai lop bao ve — lop do la
 * lan goi model — nhung no cung khong duoc tu mau thuan.
 */

import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Popover from "@radix-ui/react-popover";
import * as Tooltip from "@radix-ui/react-tooltip";

import { t, type KhoaChu } from "../../lib/i18n";
import type { ModelRa } from "../../lib/api";
import type { KetQuaMacDinh, TangMacDinh } from "./macDinh";

/**
 * Bon capability cua §9.4 → khoa chuoi trong `vi.json`.
 *
 * Catalog la file sua nong, nen mot capability la (hoac mot cai moi cua §9.4
 * chua co ban dich) phai hien duoc chu khong duoc lam vo hang: `nhanKhaNang`
 * roi ve chinh chuoi tho.
 */
const NHAN_KHA_NANG: Record<string, KhoaChu> = {
  tools: "model.cap.tools",
  vision: "model.cap.vision",
  reasoning: "model.cap.reasoning",
  attachments: "model.cap.attachments",
};

const NHAN_TANG: Record<TangMacDinh, KhoaChu> = {
  hoiThoai: "model.tierConversation",
  taiKhoan: "model.tierAccount",
  catalog: "model.tierCatalog",
};

/** Duoi bề rong nay picker la sheet, khong phai dropdown (ban T-HD4, 3c). */
const NGUONG_HEP = "(max-width: 639px)";

export interface ModelPickerProps {
  models: ModelRa[];
  /** Ket qua cua `chonMacDinh()` — model dang dung + tang cua tung id. */
  macDinh: KetQuaMacDinh;
  /**
   * Moc gio da dinh dang SAN ben ngoai, vi du `"14:32"`.
   *
   * Dinh dang o ngoai chu khong o day vi ham `t()` cua FE khong co
   * interpolation (xem `lib/i18n.ts`): cau "Trang thai kiem luc" va con so la
   * hai phan tu canh nhau, khong phai mot chuoi ghep.
   */
  nhanDocLuc: string;
  dangLamMoi?: boolean;
  onLamMoi: () => void;
  onChon: (modelId: string) => void;
}

function nhanKhaNang(khaNang: string): string {
  const khoa = NHAN_KHA_NANG[khaNang];
  return khoa === undefined ? khaNang : t(khoa);
}

/** Bề rong nho hay khong. Theo doi song, khong doc mot lan roi thoi. */
function useBeRongHep(): boolean {
  const [hep, setHep] = useState(
    () => typeof window !== "undefined" && window.matchMedia(NGUONG_HEP).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(NGUONG_HEP);
    const khiDoi = (): void => setHep(mq.matches);
    mq.addEventListener("change", khiDoi);
    // Doc lai ngay: giua lan render dau va lan `useEffect` chay, be rong co
    // the da khac (xoay may, mo DevTools).
    khiDoi();
    return () => mq.removeEventListener("change", khiDoi);
  }, []);
  return hep;
}

/** Thanh doc ben trai hang — bao tang mac dinh, khong bao "dang chon". */
function VachTang({ tang }: { tang: TangMacDinh | null }) {
  const tone =
    tang === "hoiThoai"
      ? "bg-accent"
      : tang === "taiKhoan"
        ? "border border-accent-text"
        : tang === "catalog"
          ? "bg-border-strong"
          : "";
  return <span aria-hidden="true" className={`w-rail shrink-0 self-stretch rounded-full ${tone}`} />;
}

function ChipKhaNang({ khaNang }: { khaNang: string[] }) {
  if (khaNang.length === 0) {
    return <span className="text-xs text-muted">{t("model.capNone")}</span>;
  }
  return (
    <ul className="flex flex-wrap items-center gap-1">
      {khaNang.map((kn) => (
        <li
          key={kn}
          className="rounded-sm border border-border bg-background px-1.5 py-0.5 text-2xs font-medium text-muted"
        >
          {nhanKhaNang(kn)}
        </li>
      ))}
    </ul>
  );
}

function HangModel({
  model,
  tang,
  dangChon,
  hep,
  onChon,
}: {
  model: ModelRa;
  tang: TangMacDinh | null;
  dangChon: boolean;
  hep: boolean;
  onChon: (modelId: string) => void;
}) {
  const khoa = !model.available;
  const idLyDo = `${model.id}-ly-do`;

  const hang = (
    <li
      role="option"
      aria-selected={dangChon}
      aria-disabled={khoa || undefined}
      /*
        CHI o nhanh hep, vi chi o do cau ly do co that trong DOM. O desktop
        no nam trong tooltip — thu chua ton tai khi tooltip dong — nen mot
        `aria-describedby` co dinh se tro vao mot `id` khong co that suot
        thoi gian con lai. Duong desktop de Radix tu gan: no dat
        `aria-describedby` khi mo va go khi dong, va no dung mot ban
        `role="tooltip"` an cho screen reader.

        SPREAD CO DIEU KIEN chu khong `? idLyDo : undefined`, va khac biet
        ay co that: `Tooltip.Trigger asChild` gop props bang
        `{...slotProps, ...childProps}`, nen mot `aria-describedby:
        undefined` viet ro trong childProps se GHI DE gia tri Radix vua dat
        — tuc tooltip mo ma screen reader khong duoc bao. Khong truyen khoa
        do thi khong co gi de ghi de. (Bat duoc bang ca test 13.)
      */
      {...(khoa && hep ? { "aria-describedby": idLyDo } : {})}
      tabIndex={0}
      // Cam bay ③ — hang khoa KHONG co duong nao vao `onChon`, ke ca ban phim.
      onClick={khoa ? undefined : () => onChon(model.id)}
      onKeyDown={
        khoa
          ? undefined
          : (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onChon(model.id);
              }
            }
      }
      className={
        khoa
          ? "motion-control flex min-h-row-model shrink-0 cursor-not-allowed items-stretch gap-3 rounded-md bg-surface-disabled px-2 py-2 text-disabled-foreground"
          : dangChon
            ? "motion-control flex min-h-row-model shrink-0 cursor-pointer items-stretch gap-3 rounded-md bg-accent-subtle px-2 py-2"
            : "motion-control flex min-h-row-model shrink-0 cursor-pointer items-stretch gap-3 rounded-md px-2 py-2 hover:bg-surface-hover"
      }
    >
      <VachTang tang={tang} />
      <span className="flex w-5 shrink-0 items-start justify-center pt-0.5">
        {dangChon ? <IconTich /> : null}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className={khoa ? "text-base font-semibold" : "text-base font-semibold text-foreground"}>
            {model.display_name}
          </span>
          {model.badge ? (
            <span className="rounded-full border border-border-strong px-2 py-0.5 text-2xs font-medium">
              {model.badge}
            </span>
          ) : null}
        </span>
        <span className="text-xs text-muted">{model.provider}</span>
        <ChipKhaNang khaNang={model.capabilities} />
        {/*
          Be rong nho: khong co hover nen ly do nam THANG trong hang. Cung
          phan tu `id` voi tooltip cua desktop, nen `aria-describedby` tro
          dung cho o ca hai hinh dang.
        */}
        {khoa && hep ? (
          <span
            id={idLyDo}
            className="rounded-sm border border-border bg-background px-2 py-1.5 text-xs text-muted"
          >
            {model.unavailable_reason}
          </span>
        ) : null}
      </span>
      <span className="flex shrink-0 flex-col items-end justify-start gap-1">
        {tang ? (
          <span
            className={
              tang === "hoiThoai"
                ? "rounded-full bg-accent px-2 py-0.5 text-2xs font-semibold text-accent-foreground"
                : tang === "taiKhoan"
                  ? "rounded-full border border-accent-text px-2 py-0.5 text-2xs font-semibold text-accent-text"
                  : "rounded-full border border-border px-2 py-0.5 text-2xs font-medium text-muted"
            }
          >
            {t(NHAN_TANG[tang])}
          </span>
        ) : null}
        {khoa ? <span className="text-2xs font-semibold uppercase">{t("model.unavailable")}</span> : null}
      </span>
    </li>
  );

  if (!khoa || hep) {
    return hang;
  }
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{hang}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="right"
          align="start"
          collisionPadding={16}
          className="motion-popover z-50 max-w-tooltip rounded-md bg-surface-tooltip px-3 py-2 text-xs leading-relaxed text-tooltip-foreground shadow-popover"
        >
          {model.unavailable_reason}
          <Tooltip.Arrow className="fill-surface-tooltip" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function StripTrangThai({
  nhanDocLuc,
  dangLamMoi,
  onLamMoi,
}: Pick<ModelPickerProps, "nhanDocLuc" | "dangLamMoi" | "onLamMoi">) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5">
      <p className="min-w-0 text-xs text-muted">
        <span>{t("model.checkedAtPrefix")}</span>{" "}
        <span className="tabular font-medium text-foreground">{nhanDocLuc}</span>
      </p>
      <button
        type="button"
        onClick={onLamMoi}
        aria-label={dangLamMoi ? t("model.refreshing") : t("model.refresh")}
        aria-busy={dangLamMoi || undefined}
        className="motion-control flex size-touch shrink-0 items-center justify-center rounded-md text-muted hover:bg-surface-hover hover:text-foreground"
      >
        <IconLamMoi quay={dangLamMoi} />
      </button>
    </div>
  );
}

function ThanPicker({
  models,
  macDinh,
  hep,
  onChon,
  ...strip
}: ModelPickerProps & { hep: boolean }) {
  return (
    <>
      <StripTrangThai {...strip} />
      {models.length === 0 ? (
        <p className="px-3 py-4 text-xs text-muted">{t("model.trong")}</p>
      ) : (
        <ul role="listbox" aria-label={t("model.listLabel")} className="flex flex-col gap-0.5 p-2">
          {models.map((m) => (
            <HangModel
              key={m.id}
              model={m}
              tang={tangCua(m.id, macDinh)}
              dangChon={m.id === macDinh.modelId}
              hep={hep}
              onChon={onChon}
            />
          ))}
        </ul>
      )}
      {/*
        Cho chua cho canh bao "model nay khong co vision ma hoi thoai da co
        anh" — T-4.5, KHONG lam o T-3.6. `empty:hidden` nen hom nay no khong
        chiem mot pixel nao; task ay chi phai bom noi dung vao, khong phai
        doi bo cuc.
      */}
      <div data-slot="capability-warning" aria-live="polite" className="px-2 pb-2 empty:hidden" />
      <p className="border-t border-border px-3 py-2 text-2xs text-muted">{t("model.tierOrder")}</p>
    </>
  );
}

function tangCua(modelId: string, macDinh: KetQuaMacDinh): TangMacDinh | null {
  if (modelId === macDinh.theoTang.hoiThoai) {
    return "hoiThoai";
  }
  if (modelId === macDinh.theoTang.taiKhoan) {
    return "taiKhoan";
  }
  if (modelId === macDinh.theoTang.catalog) {
    return "catalog";
  }
  return null;
}

export function ModelPicker(props: ModelPickerProps) {
  const hep = useBeRongHep();
  const [mo, setMo] = useState(false);
  const dangChon = props.models.find((m) => m.id === props.macDinh.modelId);
  const tangDangChon = props.macDinh.tang;

  const nutMo = (
    <button
      type="button"
      aria-label={t("model.pickerOpen")}
      className="motion-control flex min-h-touch max-w-full items-center gap-2 rounded-lg border border-border bg-surface-panel px-3 py-1.5 text-left hover:bg-surface-hover"
    >
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-base font-semibold text-foreground">
          {dangChon?.display_name ?? t("model.trong")}
        </span>
        {/*
          Dong thu hai la cho tra loi "model nay den tu dau" (ban T-HD4, 3d).
          Vang mat khi khong tang nao dat ra no — xem `chonMacDinh`.
        */}
        {tangDangChon ? (
          <span className="truncate text-2xs text-muted">{t(NHAN_TANG[tangDangChon])}</span>
        ) : null}
      </span>
      <IconChevron />
    </button>
  );

  const chonRoiDong = (id: string): void => {
    props.onChon(id);
    setMo(false);
  };

  if (hep) {
    return (
      <Dialog.Root open={mo} onOpenChange={setMo}>
        <Dialog.Trigger asChild>{nutMo}</Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="motion-scrim fixed inset-0 z-40 bg-scrim" />
          <Dialog.Content className="motion-sheet fixed inset-x-0 bottom-0 z-50 flex max-h-sheet-max flex-col overflow-y-auto rounded-t-xl border-t border-border bg-surface-panel shadow-popover">
            <div className="flex justify-center pt-2">
              <span aria-hidden="true" className="h-1 w-grabber rounded-full bg-border-strong" />
            </div>
            <div className="flex items-center justify-between gap-2 px-3 pt-2">
              <Dialog.Title className="text-lg font-semibold">{t("model.picker")}</Dialog.Title>
              <Dialog.Close
                aria-label={t("model.closeSheet")}
                className="motion-control flex size-touch items-center justify-center rounded-md text-muted hover:bg-surface-hover hover:text-foreground"
              >
                <IconDong />
              </Dialog.Close>
            </div>
            <ThanPicker {...props} hep onChon={chonRoiDong} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }

  return (
    <Tooltip.Provider delayDuration={200}>
      <Popover.Root open={mo} onOpenChange={setMo}>
        <Popover.Trigger asChild>{nutMo}</Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            side="top"
            align="start"
            sideOffset={8}
            collisionPadding={16}
            className="motion-popover z-50 w-picker max-w-picker-max rounded-lg border border-border bg-surface-panel shadow-popover"
          >
            <ThanPicker {...props} hep={false} onChon={chonRoiDong} />
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </Tooltip.Provider>
  );
}

/* Icon: mau lay `currentColor`, khong mot gia tri mau tho nao (§19.4 lenh 3). */
function IconTich() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="text-accent-text">
      <path d="M3 8.5 6.2 11.6 13 4.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function IconChevron() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="shrink-0 text-muted">
      <path d="M4 6.5 8 10.5 12 6.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function IconDong() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="M4.5 4.5l9 9m0-9-9 9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
function IconLamMoi({ quay }: { quay?: boolean }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 18 18"
      fill="none"
      aria-hidden="true"
      className={quay ? "motion-spin" : undefined}
    >
      <path d="M15 9a6 6 0 1 1-1.8-4.3M15 2.5V6h-3.4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
