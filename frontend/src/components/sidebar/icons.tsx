/**
 * Icon cua khung chinh — chep nguyen tu `AppShell.tsx` cua ban T-HD2.
 *
 * KH tham chieu: tasks.md T-3.3 · CLAUDE.md A3.
 *
 * SVG noi dong chu khong mot thu vien icon: repo chua cai thu vien nao, va
 * bay hinh duoi day la toan bo nhu cau cua T-HD2 cho khung chinh. `currentColor`
 * nghia la mau den tu class cua nut (`text-muted`, `text-accent-text`, …) —
 * khong mot gia tri mau nao song trong file nay (A3).
 */

const iconProps = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

/** Nut bat/tat sidebar o header. */
export const PanelIcon = () => (
  <svg {...iconProps}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9 4v16" />
  </svg>
);

export const SearchIcon = () => (
  <svg {...iconProps} width={16} height={16}>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.5-3.5" />
  </svg>
);

export const PinIcon = () => (
  <svg {...iconProps} width={13} height={13}>
    <path d="M12 17v4M8 3h8l-1 6 3 3H6l3-3-1-6z" />
  </svg>
);

export const MoreIcon = () => (
  <svg {...iconProps}>
    <circle cx="12" cy="5" r="1.4" />
    <circle cx="12" cy="12" r="1.4" />
    <circle cx="12" cy="19" r="1.4" />
  </svg>
);
