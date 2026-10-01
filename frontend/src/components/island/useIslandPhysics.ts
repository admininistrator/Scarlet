import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";

import {
  ISLAND_DRAG_THRESHOLD_PX,
  ISLAND_SPRINGS,
  ISLAND_THROW_LOOKAHEAD,
  REDUCED_MOTION_QUERY,
  readDurationMs,
  type IslandSpringRole,
  type SpringConfig,
} from "../../lib/motion";
import type { Anchor } from "./islandAnchor";

/**
 * Vat ly cua dao dieu huong — T-S.19a, ban Khung chinh v3 (`useIslandPhysics.ts`).
 *
 * Nam lo xo doc lap x, y, w, h, bo goc, ghi thang vao `style` cua `<nav>` moi
 * khung hinh — khong transition, khong mili-giay (Cam bay ① cua T-S.19a: so do
 * luc chay, khong phai mau hay thoi luong). Moi hang (lo xo, nguong) o
 * `lib/motion.ts`, moi so do doc tu token cua `theme.css`.
 *
 * Giam chuyen dong ⇒ khong lo xo nao chay: moi khung gan thang hinh dich, nen
 * doi neo khong co khung hinh trung gian (DoD dong 4).
 */

export type IslandMeasure = { pillWidth: number; barHeight: number };

type Rect = { x: number; y: number; w: number; h: number; r: number };
type Point = { x: number; y: number };
type Sample = Point & { t: number };
const KEYS = ["x", "y", "w", "h", "r"] as const;
type SpringState = Record<(typeof KEYS)[number], { x: number; v: number }>;
type Phase = "rest" | "gather" | "follow" | "fly";

/** Token do dai → px. `rem` nhan voi co chu goc THAT (nguoi dung co the doi). */
export function tokenPx(name: string): number {
  const style = getComputedStyle(document.documentElement);
  const raw = style.getPropertyValue(name).trim();
  const value = parseFloat(raw) || 0;
  return raw.endsWith("rem") ? value * parseFloat(style.fontSize) : value;
}

/** `null` ⇒ dao nhay thang toi hinh dich (giam chuyen dong). */
function islandSpringFor(role: IslandSpringRole): SpringConfig | null {
  if (typeof window.matchMedia === "function" && window.matchMedia(REDUCED_MOTION_QUERY).matches) {
    return null;
  }
  return ISLAND_SPRINGS[role];
}

function readGeometry() {
  return {
    gap: tokenPx("--spacing-island-gap"),
    pill: tokenPx("--spacing-island-pill"),
    orb: tokenPx("--spacing-island-orb"),
    bar: tokenPx("--spacing-island-bar"),
    side: tokenPx("--spacing-sidebar"),
    radius: tokenPx("--radius-island"),
    sideRadius: tokenPx("--radius-island-side"),
  };
}
type Geometry = ReturnType<typeof readGeometry>;

function restRect(anchor: Anchor, expanded: boolean, m: IslandMeasure, g: Geometry): Rect {
  const W = window.innerWidth;
  const H = window.innerHeight;
  if (anchor === "top") {
    if (expanded) {
      const w = Math.min(g.bar, W - 2 * g.gap);
      return { x: (W - w) / 2, y: g.gap, w, h: m.barHeight, r: g.radius };
    }
    return { x: (W - m.pillWidth) / 2, y: g.gap, w: m.pillWidth, h: g.pill, r: g.pill / 2 };
  }
  // Hai ben: LUON la sidebar doc (NQ-136, ban v3-beta) — `expanded` chi co nghia o neo tren.
  return { x: anchor === "left" ? g.gap : W - g.gap - g.side, y: g.gap, w: g.side, h: H - 2 * g.gap, r: g.sideRadius };
}

const orbAt = (p: Point, orb: number): Rect => ({ x: p.x - orb / 2, y: p.y - orb / 2, w: orb, h: orb, r: orb / 2 });
const clamp = (v: number, low: number, hi: number) => Math.max(low, Math.min(hi, v));

/** Ban an, buoc con 1/240 s. `spring = null` (giam chuyen dong) ⇒ gan thang dich. */
export function step(s: SpringState, target: Rect, spring: SpringConfig | null, dt: number) {
  if (spring === null) {
    for (const k of KEYS) {
      s[k].x = target[k];
      s[k].v = 0;
    }
    return;
  }
  const n = Math.max(1, Math.ceil(dt * 240));
  const h = dt / n;
  for (let i = 0; i < n; i++) {
    for (const k of KEYS) {
      const q = s[k];
      q.v += (-spring.stiffness * (q.x - target[k]) - spring.damping * q.v) * h;
      q.x += q.v * h;
    }
  }
  // Du gan dich (duoi 0.01 px) ⇒ chot: lo xo dung han, khung sau khong con gi de ghi.
  for (const k of KEYS) {
    const q = s[k];
    if (Math.abs(q.x - target[k]) < 0.01 && Math.abs(q.v) < 0.01) {
      q.x = target[k];
      q.v = 0;
    }
  }
}

/** Neo gan nhat voi diem tha + van toc × lookahead. Man hep chi co neo tren. */
export function nearestAnchor(p: Point, compact: boolean): Anchor {
  if (compact) {
    return "top";
  }
  const g = readGeometry();
  const W = window.innerWidth;
  const H = window.innerHeight;
  const points: Record<Anchor, Point> = {
    top: { x: W / 2, y: g.gap + g.pill / 2 },
    left: { x: g.gap + g.orb / 2, y: H / 2 },
    right: { x: W - g.gap - g.orb / 2, y: H / 2 },
  };
  let best: Anchor = "top";
  let distance = Infinity;
  for (const key of Object.keys(points) as Anchor[]) {
    const d = Math.hypot(p.x - points[key].x, p.y - points[key].y);
    if (d < distance) {
      distance = d;
      best = key;
    }
  }
  return best;
}

function project(samples: Sample[]): Point {
  const a = samples[0];
  const b = samples[samples.length - 1];
  const dt = Math.max(0.016, (b.t - a.t) / 1000);
  return {
    x: b.x + ((b.x - a.x) / dt) * ISLAND_THROW_LOOKAHEAD,
    y: b.y + ((b.y - a.y) / dt) * ISLAND_THROW_LOOKAHEAD,
  };
}

export function useIslandPhysics(options: {
  islandRef: RefObject<HTMLElement | null>;
  glassRef: RefObject<HTMLElement | null>;
  trailRef: RefObject<HTMLCanvasElement | null>;
  anchor: Anchor;
  expanded: boolean;
  compact: boolean;
  measure: () => IslandMeasure;
  onRelease: (next: Anchor) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [near, setNear] = useState<Anchor | null>(null);
  const live = useRef(options);
  live.current = options;
  const phase = useRef<Phase>("rest");
  const role = useRef<IslandSpringRole>("islandMorph");
  const state = useRef<SpringState | null>(null);
  const pointer = useRef<Point>({ x: 0, y: 0 });
  const grab = useRef<Point>({ x: 0, y: 0 });
  const trail = useRef<Sample[]>([]);
  const trailStyle = useRef({ life: 0, color: "" });
  /** Chuoi `style` da ghi o khung truoc — dao dung yen thi KHONG ghi lai (khong lam ban style moi khung). */
  const written = useRef({ shape: "", glass: "" });

  // Doi neo khi khong keo (ban phim, tha) → bay; doi `expanded` → morph.
  useEffect(() => {
    if (phase.current === "rest" || phase.current === "fly") {
      phase.current = "fly";
      role.current = "islandFly";
    }
  }, [options.anchor]);
  useEffect(() => {
    if (phase.current === "rest") {
      role.current = "islandMorph";
    }
  }, [options.expanded]);

  useEffect(() => {
    let geometry = readGeometry();
    const onResize = () => {
      geometry = readGeometry();
    };
    window.addEventListener("resize", onResize);
    let last = performance.now();
    let raf = requestAnimationFrame(function tick(now) {
      raf = requestAnimationFrame(tick);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const o = live.current;
      const el = o.islandRef.current;
      if (el === null) {
        return;
      }
      const target =
        phase.current === "gather"
          ? orbAt(grab.current, geometry.orb)
          : phase.current === "follow"
            ? orbAt(pointer.current, geometry.orb)
            : restRect(o.anchor, o.expanded, o.measure(), geometry);
      if (state.current === null) {
        state.current = Object.fromEntries(KEYS.map((k) => [k, { x: target[k], v: 0 }])) as SpringState;
      }
      const s = state.current;
      step(s, target, islandSpringFor(role.current), dt);

      if (phase.current === "gather" && Math.abs(s.w.x - geometry.orb) < 6 && Math.abs(s.h.x - geometry.orb) < 6) {
        phase.current = "follow";
        role.current = "islandFollow";
      }
      if (phase.current === "fly" && KEYS.every((k) => Math.abs(s[k].v) < 6 && Math.abs(s[k].x - target[k]) < 0.5)) {
        phase.current = "rest";
        role.current = "islandMorph";
      }

      const box = [
        `translate3d(${s.x.x}px, ${s.y.x}px, 0)`,
        `${Math.max(8, s.w.x)}px`,
        `${Math.max(8, s.h.x)}px`,
        `${Math.max(0, Math.min(s.r.x, s.w.x / 2, s.h.x / 2))}px`,
      ];
      if (box.join("|") !== written.current.shape) {
        written.current.shape = box.join("|");
        [el.style.transform, el.style.width, el.style.height, el.style.borderRadius] = box;
      }

      // Kinh gian theo huong bay, tran 20%.
      const glass = o.glassRef.current;
      if (glass !== null) {
        const vx = s.x.v + s.w.v / 2;
        const vy = s.y.v + s.h.v / 2;
        const moving = phase.current === "follow" || phase.current === "fly";
        const k = moving ? Math.min(Math.hypot(vx, vy) / 2600, 0.2) : 0;
        const angle = Math.atan2(vy, vx);
        const stretch = k > 0.004 ? `rotate(${angle}rad) scale(${1 + k}, ${1 - k * 0.55}) rotate(${-angle}rad)` : "";
        if (stretch !== written.current.glass) {
          written.current.glass = stretch;
          glass.style.transform = stretch;
        }
      }

      const cx = s.x.x + s.w.x / 2;
      const cy = s.y.x + s.h.x / 2;
      if (phase.current === "follow" && trailStyle.current.life > 0) {
        const lastPoint = trail.current[trail.current.length - 1];
        if (lastPoint === undefined || Math.hypot(lastPoint.x - cx, lastPoint.y - cy) > 1.5) {
          trail.current.push({ x: cx, y: cy, t: now });
        }
      }
      drawTrail(o.trailRef.current, trail, trailStyle.current, now);
    });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  const handlers = {
    onPointerDown(event: ReactPointerEvent<HTMLElement>) {
      if (event.button !== 0 || live.current.compact) {
        return;
      }
      const start = { x: event.clientX, y: event.clientY };
      const samples: Sample[] = [{ ...start, t: performance.now() }];
      let active = false;
      const move = (ev: PointerEvent) => {
        const orb = tokenPx("--spacing-island-orb");
        const p = {
          x: clamp(ev.clientX, orb / 2, window.innerWidth - orb / 2),
          y: clamp(ev.clientY, orb / 2, window.innerHeight - orb / 2),
        };
        pointer.current = p;
        const now = performance.now();
        samples.push({ ...p, t: now });
        while (samples.length > 2 && now - samples[0].t > 90) {
          samples.shift();
        }
        if (
          !active &&
          Math.hypot(ev.clientX - start.x, ev.clientY - start.y) > ISLAND_DRAG_THRESHOLD_PX &&
          state.current !== null
        ) {
          active = true;
          const s = state.current;
          const fit = (a: number, low: number, span: number) =>
            span <= orb ? low + span / 2 : clamp(a, low + orb / 2, low + span - orb / 2);
          grab.current = { x: fit(start.x, s.x.x, s.w.x), y: fit(start.y, s.y.x, s.h.x) };
          phase.current = "gather";
          role.current = "islandGrab";
          trail.current = [];
          const root = getComputedStyle(document.documentElement);
          trailStyle.current = {
            life: readDurationMs("--duration-trail"),
            color: root.getPropertyValue("--color-accent").trim(),
          };
          const focused = document.activeElement;
          if (focused instanceof HTMLElement && live.current.islandRef.current?.contains(focused)) {
            focused.blur();
          }
          setDragging(true);
        }
        if (active) {
          setNear(nearestAnchor(project(samples), false));
        }
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", up);
        if (!active) {
          return;
        }
        const next = nearestAnchor(project(samples), live.current.compact);
        phase.current = "fly";
        role.current = "islandFly";
        setDragging(false);
        setNear(null);
        // Nha sau khi keo khong duoc tinh la mot cu bam vao nut ben duoi con tro.
        const el = live.current.islandRef.current;
        const swallow = (e: Event) => {
          e.stopPropagation();
          e.preventDefault();
        };
        el?.addEventListener("click", swallow, { capture: true, once: true });
        window.setTimeout(() => el?.removeEventListener("click", swallow, { capture: true }), 0);
        live.current.onRelease(next);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", up);
    },
  };

  return { dragging, near, handlers };
}

function drawTrail(
  canvas: HTMLCanvasElement | null,
  trail: { current: Sample[]; drawn?: boolean },
  style: { life: number; color: string },
  now: number,
) {
  // Khong co gi tren canvas va khong co diem nao ⇒ khong dong toi canvas (jsdom
  // khong co canvas 2D: `getContext` in canh bao).
  if (canvas === null || (trail.current.length === 0 && trail.drawn !== true)) {
    return;
  }
  const ctx = canvas.getContext("2d");
  if (ctx === null) {
    return;
  }
  const dpr = window.devicePixelRatio || 1;
  const W = window.innerWidth;
  const H = window.innerHeight;
  if (canvas.width !== Math.round(W * dpr)) {
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
  }
  const life = style.life || 1;
  trail.current = trail.current.filter((p) => now - p.t < life);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const pts = trail.current;
  trail.drawn = pts.length >= 2 && style.color !== "";
  if (!trail.drawn) {
    return;
  }
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.strokeStyle = style.color; // gia tri cua --color-accent, doc luc bat dau keo
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 1; i < pts.length; i++) {
      const f = Math.max(0, 1 - (now - pts[i].t) / life);
      ctx.globalAlpha = pass === 0 ? 0.08 * f : 0.42 * f * f;
      ctx.lineWidth = pass === 0 ? 8 + 44 * f : 2 + 12 * f;
      ctx.beginPath();
      ctx.moveTo(pts[i - 1].x, pts[i - 1].y);
      ctx.lineTo(pts[i].x, pts[i].y);
      ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;
}
