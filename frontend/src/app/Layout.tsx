import { Outlet, useLocation, useOutletContext } from "react-router";

import { AppIsland } from "../components/island/AppIsland";
import { useIslandAnchor } from "../components/island/islandAnchor";
import { useSessionState, type SessionState } from "../features/auth/useSessionState";
import { PATHS } from "./paths";

/**
 * Layout shell — vung noi dung (+ dao dieu huong, T-S.19a). T-3.1a.
 *
 * KH tham chieu: §16.3 · tasks.md T-3.1a, T-2.19.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  PHIEN DUOC HOI MOT LAN, O DAY                                         ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `useSessionState()` goi `GET /auth/me` luc mount. Goi no trong tung man hinh se
 * cho N loi goi cho mot cau hoi, va te hon: hai man hinh co the doc hai cau
 * tra loi khac nhau trong cung mot lan xem. Nen no duoc hoi MOT lan o day
 * roi day xuong qua `Outlet context`, va cac route con lay lai bang
 * `useSession()`.
 *
 * Vi sao `useOutletContext` chu khong mot React Context tu dung: day dung la
 * co che React Router sinh ra cho quan he layout → route con, nen no khong
 * them mot khai niem nao vao dau nguoi doc file nay. Neu sau nay co thanh
 * phan nam SAU mot route con can phien (ung vien gan nhat: thanh quota cua
 * T-3.11), luc do hay dung mot Context that — va doi ca cum mot lan, chu
 * dung de hai duong cung song.
 */
export function useSession(): SessionState {
  return useOutletContext<SessionState>();
}

/** Sau duong auth cua T-3.1b — ve bang `AuthLayout`, khong header (T-S.16). */
const AUTH_PATHS: ReadonlySet<string> = new Set([
  PATHS.login,
  PATHS.register,
  PATHS.forgotPassword,
  PATHS.resetPassword,
  PATHS.verifyEmail,
  PATHS.pendingApproval,
]);

/**
 * NQ-136 — neo hai ben, sidebar LUON mo va DAY noi dung (ban v3-beta `contentL`):
 * le phia co sidebar = le dao 16 + sidebar 256. Khong co chuyen dong: `theme.css`
 * chua co `.motion-*` nao cho `padding` (B-326).
 */
const INSET = {
  top: "",
  left: " pl-[calc(var(--spacing-island-gap)_+_var(--spacing-sidebar))]",
  right: " pr-[calc(var(--spacing-island-gap)_+_var(--spacing-sidebar))]",
} as const;

/**
 * T-S.19a — duong co dao dieu huong ngoai man chat. Man chat (`/`) dung dao
 * cua chinh no (`ChatScreen`), vi dao o do noi thang vao `useChat`.
 */
function islandContextOf(pathname: string): "settings" | "admin" | null {
  if (pathname === PATHS.admin) {
    return "admin";
  }
  if (pathname === PATHS.settings || pathname.startsWith(`${PATHS.settings}/`)) {
    return "settings";
  }
  return null;
}

export function Layout() {
  const session = useSessionState();
  const { pathname } = useLocation();
  const anchor = useIslandAnchor();

  /*
    T-S.16 — ban T-HD8 ve sau man auth KHONG co header: chu Scarlet nam trong
    cot form va la loi ve trang chu duy nhat (NQ-131 d). Man "bi khoa" cung
    vay — no hien o bat ky duong nao `StatusGate`/`SignedInOnly` canh, nen
    hoi `session.locked` chu khong hoi duong.
  */
  const bare = AUTH_PATHS.has(pathname) || session.locked;
  /*
    T-S.19a (ban Khung chinh v3) — header 56 bi go: dao dieu huong noi thay no
    tren `/`, `/cai-dat/*`, `/admin`. Trang 404 de tran nhu man auth, chi con
    nut "Ve trang chu" cua chinh no (NQ-135 ④).
  */
  const islandContext = bare || session.user === null ? null : islandContextOf(pathname);
  // Man chat (`/`) dung dao cua chinh no nhung van nam trong khung nay.
  const islandHere = islandContext !== null || (!bare && session.user !== null && pathname === PATHS.home);

  return (
    /*
      Khung cao DUNG man hinh (`h-dvh`): thanh cuon nam O TRONG vung noi dung
      chu khong o `window`. Man chat tu chia tiep va chi cot tin nhan cuon.
      Dao noi (`fixed`) de len vung noi dung; `/cai-dat/*` va `/admin` chua
      cho no bang `pt-island-clear` (NQ-135 ②) — dem nam TRONG khung cuon, nen
      cuon xuong thi noi dung troi duoi kinh mo nhu luong chat.
    */
    <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      {islandContext !== null && <AppIsland session={session} context={islandContext} />}
      <div
        className={`min-h-0 flex-1 overflow-y-auto${islandContext !== null ? " pt-island-clear" : ""}${
          islandHere ? INSET[anchor] : ""
        }`}
      >
        <Outlet context={session} />
      </div>
    </div>
  );
}
