import { useCallback, useEffect, useRef, useState } from "react";

import type { PendingAttachment } from "../../components/chat/Attachments";
import { ApiError, api, type MessageAttachment } from "../../lib/api";
import { t } from "../../lib/i18n";
import { newKey } from "../../lib/idempotency";

/**
 * Khay tep CHO GUI cua o nhap — T-4.7.
 *
 * KH tham chieu: UC-06, §15.1, §19.1 · NQ-138 (Q-P4-8) · tasks.md T-4.2 ⑥,
 * B-343, B-355.
 *
 * - **Chan TRUOC khi tai len** theo ba tran cua `/auth/me` (UC-06 dong 3): tep
 *   bi chan khong vao khay va KHONG co `POST` nao. `limits === null` (profile
 *   chua ve) ⇒ khong chan gi, cua that van la server.
 * - **Moi tep mot `POST /attachments` ngay khi chon, mot khoa moi tep** (T-4.2
 *   ⑥) — khac khoa cua lan soan (C22) ma `Composer` giu.
 * - **Anh xem truoc bang `blob:`**, khong bang `url` cua `201`: chu ky ay chet
 *   sau `PRESIGN_TTL_S`, va ban phat lai cua §11.4 tra lai dung chu ky cu
 *   (B-343). Moi `createObjectURL` co dung mot `revokeObjectURL` — luc go, luc
 *   gui xong (`clear`), luc unmount.
 * - **Go = bo khoi khay**, khong goi API nao (NQ-138 ⑧; object o lai, B-338).
 */

export type UploadLimits = {
  max_upload_mb: number;
  max_attachments: number;
  allowed_upload_mime: readonly string[];
};

type Item = PendingAttachment & {
  /** `id` cua server — `null` toi khi `201` ve. */
  serverId: string | null;
  extractStatus: string | null;
};

const BYTES_PER_MB = 1024 * 1024;
// ponytail: hoi lai moi giay toi khi roi `pending`; doi sang SSE neu job
// `extract` co stream rieng. Hang `pending` ket (B-352) ⇒ hoi toi khi go tep.
const EXTRACT_POLL_MS = 1_000;

/**
 * MIME cua trinh duyet chi la goi y (§15.2 — server doc magic bytes). Rong ⇒
 * de server quyet. `text/*` qua neu `text/plain` duoc phep: tep `.md` di duoi
 * ten `text/plain` (NQ-138 ②) trong khi trinh duyet goi no `text/markdown`.
 */
function mimeAllowed(type: string, allowed: readonly string[]): boolean {
  return (
    type === "" || allowed.includes(type) || (type.startsWith("text/") && allowed.includes("text/plain"))
  );
}

const isImage = (file: File) => file.type.startsWith("image/");

/** Loi cua `POST /attachments` thanh mot cau. `413` cua Nginx la HTML (T-4.2 ⑤). */
function uploadError(error: unknown, limits: UploadLimits | null): string {
  if (error instanceof ApiError) {
    if (error.status === 413) {
      const cap = limits === null ? "" : ` (${limits.max_upload_mb} MB)`;
      return `${t("composer.reject.tooLarge")}${cap}`;
    }
    if (error.status === 415) {
      return t("composer.reject.type");
    }
    if (error.code === "ATTACHMENT_IMAGE_INVALID") {
      return t("composer.reject.imageInvalid");
    }
  }
  return t("composer.reject.failed");
}

/** `extract_status` → trang thai khay. `failed` van gui duoc (T-4.6a ③). */
function fromServer(out: MessageAttachment): Partial<Item> {
  const base = { serverId: out.id, kind: out.kind, extractStatus: out.extract_status };
  if (out.extract_status === "pending") {
    return { ...base, state: "processing" };
  }
  if (out.extract_status === "too_many_pages") {
    return { ...base, state: "error", error: t("composer.reject.tooManyPages") };
  }
  return { ...base, state: undefined };
}

export function usePendingAttachments(limits: UploadLimits | null, noVision: boolean) {
  const [items, setItems] = useState<Item[]>([]);
  const [rejected, setRejected] = useState<string[]>([]);
  // Doc dong bo trong callback bat dong bo (upload/poll) va luc unmount.
  const itemsRef = useRef(items);
  itemsRef.current = items;

  const patch = useCallback((id: string, next: Partial<Item>) => {
    // Tep da bi go thi `map` khong khop gi — ket qua muon bi bo.
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, ...next } : item)));
  }, []);

  const poll = useCallback(
    async (id: string, serverId: string) => {
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, EXTRACT_POLL_MS));
        // Da go, da gui, hoac o nhap da unmount (`itemsRef` rong) ⇒ thoi hoi.
        if (!itemsRef.current.some((item) => item.id === id)) {
          return;
        }
        try {
          const out = await api.getAttachment(serverId);
          if (out.extract_status !== "pending") {
            patch(id, fromServer(out));
            return;
          }
        } catch {
          // Mang chap chon: hoi lai nhip sau. Go tep la cach dung.
        }
      }
    },
    [patch],
  );

  const upload = useCallback(
    async (id: string, file: File) => {
      try {
        const out = await api.uploadAttachment(file, newKey());
        patch(id, fromServer(out));
        if (out.extract_status === "pending") {
          void poll(id, out.id);
        }
      } catch (e) {
        patch(id, { state: "error", error: uploadError(e, limits) });
      }
    },
    [patch, poll, limits],
  );

  const add = useCallback(
    (files: readonly File[]) => {
      const reasons: string[] = [];
      const accepted: [Item, File][] = [];
      let room =
        limits === null
          ? Infinity
          : limits.max_attachments - itemsRef.current.filter((item) => item.state !== "error").length;
      for (const file of files) {
        let reason: string | null = null;
        if (noVision && isImage(file)) {
          reason = t("composer.noVision");
        } else if (limits !== null && file.size > limits.max_upload_mb * BYTES_PER_MB) {
          reason = `${t("composer.reject.tooLarge")} (${limits.max_upload_mb} MB)`;
        } else if (limits !== null && !mimeAllowed(file.type, limits.allowed_upload_mime)) {
          reason = t("composer.reject.type");
        } else if (room <= 0) {
          reason = `${t("composer.reject.tooMany")} (${limits?.max_attachments ?? ""})`;
        }
        if (reason !== null) {
          reasons.push(`${file.name}: ${reason}`);
          continue;
        }
        room -= 1;
        accepted.push([
          {
            id: newKey(),
            kind: isImage(file) ? "image" : "file",
            name: file.name,
            bytes: file.size,
            previewUrl: isImage(file) ? URL.createObjectURL(file) : undefined,
            state: "uploading",
            serverId: null,
            extractStatus: null,
          },
          file,
        ]);
      }
      setRejected(reasons);
      if (accepted.length === 0) {
        return;
      }
      itemsRef.current = [...itemsRef.current, ...accepted.map(([item]) => item)];
      setItems(itemsRef.current);
      for (const [item, file] of accepted) {
        void upload(item.id, file);
      }
    },
    [limits, noVision, upload],
  );

  const remove = useCallback((id: string) => {
    const item = itemsRef.current.find((candidate) => candidate.id === id);
    if (item?.previewUrl !== undefined) {
      URL.revokeObjectURL(item.previewUrl);
    }
    itemsRef.current = itemsRef.current.filter((candidate) => candidate.id !== id);
    setItems(itemsRef.current);
    setRejected([]);
  }, []);

  /** Gui xong (`202`): khay rong. Gui hong thi KHONG goi — khay giu. */
  const clear = useCallback(() => {
    for (const item of itemsRef.current) {
      if (item.previewUrl !== undefined) {
        URL.revokeObjectURL(item.previewUrl);
      }
    }
    itemsRef.current = [];
    setItems([]);
    setRejected([]);
  }, []);

  // Unmount: thu hoi moi `blob:` con lai, va lam rong `itemsRef` de vong hoi
  // `extract_status` tu dung.
  useEffect(() => clear, [clear]);

  return {
    items: items as PendingAttachment[],
    rejected,
    add,
    remove,
    clear,
    /** Moi tep da co id server va khong con cho/loi. */
    ready: items.every((item) => item.state === undefined),
    ids: items.flatMap((item) => (item.serverId === null ? [] : [item.serverId])),
    /** B-355 ② — anh, hoac PDF quet, ma model dang chon khong doc anh. */
    needsVision: items.some((item) => item.kind === "image" || item.extractStatus === "needs_vision"),
  };
}
