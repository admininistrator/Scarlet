import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, type Skill } from "../../lib/api";

/**
 * Skill cua nguoi dung — T-7.9, ban T-HD11 (`skillApi.ts`). Lop du lieu: khong
 * JSX, khong chuoi hien thi.
 *
 * KH tham chieu: UC-09 dong 1 · §18.3 · tasks.md T-7.5 (`PUT …/toggle` nhan
 * `{"enabled": bool}`), T-7.8b (bon skill dung san bat mac dinh — NQ-148).
 *
 * Goi o o nhap (mount cung `Composer`), khong o panel: so tren nut ⚡ phai co
 * ngay khi tai trang. Mo panel ⇒ nap lai lang le (giu danh sach dang co) de
 * muc bi go bien mat. Bat / tat co hieu luc tu luot gui KE TIEP.
 */

export type SkillRowStatus = "idle" | "saving" | "error" | "gone";
export type SkillList = { status: "loading" } | { status: "error" } | { status: "ready"; items: Skill[] };

const isGone = (error: unknown) => error instanceof ApiError && error.status === 404;

export function useSkills() {
  const [list, setList] = useState<SkillList>({ status: "loading" });
  const [rows, setRows] = useState<Record<string, SkillRowStatus>>({});
  const listRef = useRef(list);
  const rowsRef = useRef(rows);
  listRef.current = list;
  rowsRef.current = rows;
  const liveRef = useRef(0);

  const load = useCallback((silent = false) => {
    // Lan nap moi thang lan cu: ket qua cua lan cu ve muon bi bo.
    const run = ++liveRef.current;
    const keep = silent && listRef.current.status === "ready";
    if (!keep) {
      setList({ status: "loading" });
    }
    api.listSkills().then(
      (out) => {
        if (run !== liveRef.current) {
          return;
        }
        setList({ status: "ready", items: out.items });
        // Hang dang luu giu trang thai; loi cu va muc da go xoa cung lan nap.
        setRows((r) => Object.fromEntries(Object.entries(r).filter(([, v]) => v === "saving")));
      },
      () => {
        if (run === liveRef.current && !keep) {
          setList({ status: "error" });
        }
      },
    );
  }, []);

  useEffect(() => {
    load();
    return () => {
      liveRef.current += 1;
    };
  }, [load]);

  const patch = (name: string, next: Partial<Skill>) =>
    setList((l) =>
      l.status === "ready" ? { status: "ready", items: l.items.map((s) => (s.name === name ? { ...s, ...next } : s)) } : l,
    );
  const setRow = (name: string, status: SkillRowStatus) => setRows((r) => ({ ...r, [name]: status }));

  const toggle = useCallback(async (name: string) => {
    const l = listRef.current;
    const current = l.status === "ready" ? l.items.find((s) => s.name === name) : undefined;
    const row = rowsRef.current[name];
    if (current === undefined || row === "saving" || row === "gone") {
      return;
    }
    // Lac quan: num truot ngay, so tren nut ⚡ doi ngay.
    patch(name, { enabled: !current.enabled });
    setRow(name, "saving");
    try {
      patch(name, await api.toggleSkill(name, !current.enabled));
      setRow(name, "idle");
    } catch (error) {
      patch(name, { enabled: current.enabled });
      setRow(name, isGone(error) ? "gone" : "error");
    }
  }, []);

  const count = list.status === "ready" ? list.items.filter((s) => s.enabled).length : 0;
  return { list, rows, count, toggle, reload: load };
}

export type SkillsState = ReturnType<typeof useSkills>;
