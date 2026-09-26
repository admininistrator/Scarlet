/**
 * Phien dang nhap cua FE — nua client cua §11.2 (NQ-36).
 *
 * KH tham chieu: §11.2, §11.1, §16.3 · tasks.md T-2.3, T-2.7, T-2.19 · NQ-36.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  KHONG CO "TRANG THAI DANG NHAP" NAO DUOC LUU O FE                     ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Access token nam trong cookie `scarlet_session` voi co `HttpOnly` (NQ-36),
 * tuc JS cua trang khong doc duoc no — co chu y. Hau qua: FE khong co cach
 * nao TU BIET minh dang la ai; no phai HOI, va cau hoi do la `GET /auth/me`.
 *
 * Vi vay khong co `localStorage.setItem("user", ...)` o day va khong duoc
 * them. Mot ban sao danh tinh trong `localStorage` se song sot qua ca luc
 * cookie het han va luc admin bam Suspend (§11.3) — tuc man hinh van hien ten
 * mot nguoi da bi khoa, trong khi moi loi goi API deu 401. Nguon su that o
 * phia server, va gia phai tra la mot lan `GET /auth/me` luc mo trang.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  ERROR_CODES,
  api,
  type ProfileOut,
  type SettingsOut,
  type UserOut,
} from "../../lib/api";

export interface SessionState {
  /** `null` = chua dang nhap (hoac phien da het). */
  user: UserOut | null;
  /**
   * Cau tra loi DAY DU cua `GET /auth/me` — `quota`, `message_max_chars`,
   * `default_model` (§18.1, B-213).
   *
   * Tach khoi `user` chu khong mo rong no, vi `/auth/login` KHONG tra
   * hai truong dau: chung dat hai luot doc Redis (`ProfileOut` cua backend giai
   * thich vi sao), va mot cai ten kieu `UserOut` hua ba truong ma chi hai
   * duong trong ba tra ve la mot cai bay im lang.
   *
   * `null` khi chua hoi xong, khi chua dang nhap, hoac khi lan hoi do hong.
   * Ben doc phai co duong lui: mot `message_max_chars` khong biet la "khong
   * dem duoc", khong phai "khong co tran" — tran that o `422` cua server.
   */
  profile: ProfileOut | null;
  /**
   * T-3.11 — `Date.now()` luc cau tra loi `/auth/me` dang nam trong `hoSo`
   * VE TOI trinh duyet. `retry_after` la so giay TINH TU LUC DO, nen doi no
   * thanh mot moc gio can dung moc nay chu khong `Date.now()` luc render.
   *
   * Mot truong rieng chu khong suy tu danh tinh object `hoSo`: `changeDefaultModel`
   * cung thay `hoSo` bang mot object moi ma khong doc lai quota nao.
   */
  profileReadAt: number | null;
  /** Lan hoi `GET /auth/me` dau tien con dang chay hay khong. */
  loading: boolean;
  /**
   * `GET /auth/me` tra `403 ACCOUNT_DISABLED` — tai khoan `rejected` hoac
   * `suspended` (§11.1). **Khac** `nguoiDung === null`, xem chu thich trong
   * `useEffect` ben duoi.
   */
  locked: boolean;
  /** Loi cua lan `login()` gan nhat; `null` khi chua thu hoac da thanh cong. */
  error: ApiError | null;
  /** Tra `UserOut` khi thanh cong — caller can `status` de dinh tuyen (§11.1). */
  login: (email: string, password: string) => Promise<UserOut | null>;
  logout: () => Promise<void>;
  /**
   * T-3.6 — ghi `users.default_model` (`PUT /settings`) va cap nhat `hoSo`
   * tai cho. UC-05 dong 4: *"user doi duoc va duoc nho theo user"*.
   *
   * O DAY chu khong trong `useChat`, vi day la mot truong cua `/auth/me` va
   * `Layout` la nguoi duy nhat hoi cau hoi ay (xem docstring `Layout`). Giu
   * mot ban sao thu hai trong man chat nghia la sau khi doi model, hai cho
   * tren cung mot trang se noi hai chuyen khac nhau cho toi lan F5.
   *
   * Nem lai loi cho ben goi: `400 MODEL_UNKNOWN` la mot ket cuc co that
   * (catalog sua nong — Cam bay ③ cua T-3.0) va man hinh phai noi duoc.
   */
  changeDefaultModel: (modelId: string | null) => Promise<void>;
  /**
   * T-S.11 — ghi `PUT /settings` voi DU bon truong: `patch` (phan doi) ghep
   * len ban day du doc tu `/auth/me`. Moi lan luu cua FE di qua day, ke ca
   * `changeDefaultModel` (Cam bay ① cua T-S.11: PUT thay ca tai nguyen, mot
   * lan doi ten ma quen `default_model` la mot lan mat model mac dinh).
   *
   * Chua co ho so (`/auth/me` hong luc mount) ⇒ hoi lai `/auth/me` TRUOC khi
   * ghi, khong bao gio gui mot body thieu truong. Nem lai loi cho ben goi.
   */
  saveSettings: (patch: Partial<SettingsOut>) => Promise<void>;
  /**
   * T-S.14 — nho muc suy luan `level` cho RIENG `modelId` (§24.2b·S4: nho
   * theo user × model). Di qua `saveSettings`, nen body van du bon truong.
   *
   * Ghep len `reasoning_prefs` cua ban ho so MOI NHAT (`profileRef`), khong
   * cua ban luc render: hai lan chon lien tiep cho hai model khac nhau ma doc
   * ban cu thi lan sau xoa mat lan truoc.
   */
  changeReasoningPref: (modelId: string, level: string) => Promise<void>;
  /**
   * T-3.11 — hoi lai `GET /auth/me` de lam tuoi thanh quota.
   *
   * Goi SAU moi luot sinh (`done`/`error`) va sau mot `429 QUOTA_EXCEEDED`,
   * khong theo mot bo dem thoi gian: quota chi doi khi `usage_events` co dong
   * moi (B-209). Loi o day giu nguyen `hoSo` cu — mot lan lam tuoi hong khong
   * phai la "da dang xuat", va dinh tuyen van la viec cua lan hoi luc mount.
   */
  refreshProfile: () => Promise<void>;
}

export function useSessionState(): SessionState {
  const [user, setUser] = useState<UserOut | null>(null);
  const [profile, setProfile] = useState<ProfileOut | null>(null);
  const [profileReadAt, setProfileReadAt] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  /*
    Ban ho so MOI NHAT cho `saveSettings` — mot ref chu khong doc `profile`
    trong closure: hai lan luu lien nhau (doi ten roi doi mau) thi lan hai
    phai ghep len ket qua cua lan mot, khong len ban cu cua lan render truoc.
  */
  const profileRef = useRef<ProfileOut | null>(null);
  profileRef.current = profile;

  useEffect(() => {
    let mounted = true;
    void (async () => {
      try {
        const output = await api.me();
        if (mounted) {
          setUser(output);
          setProfile(output);
          setProfileReadAt(Date.now());
          setLocked(false);
        }
      } catch (e) {
        // T-2.19 gop 401 va 403 vao mot ket cuc vi luc do chung dan toi cung
        // mot man hinh. T-3.1b tach chung ra, va ly do la mot dong cua "Viec
        // can lam": *"`suspended` -> man giai thich. **Khong** roi ve man
        // chat"*. Ke tu day hai ma loi ay dan toi hai man hinh khac nhau, nen
        // gop chung lai chinh la danh mat thong tin duy nhat phan biet duoc.
        //
        // `user` VAN la `null` o ca hai ca: khong co phien dung duoc.
        // `locked` la mot truong RIENG chu khong mot gia tri thu ba cua
        // `user`, de moi cho dang doc `nguoiDung === null` giu nguyen
        // nghia cu.
        if (mounted) {
          setUser(null);
          setProfile(null);
          setLocked(e instanceof ApiError && e.code === ERROR_CODES.ACCOUNT_DISABLED);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string): Promise<UserOut | null> => {
      setError(null);
      try {
        const output = await api.login(email, password);
        setUser(output);
        setLocked(false);
        /*
          Hoi them `GET /auth/me` sau khi dang nhap — B-213.

          `Layout` goi `useSessionState()` MOT lan luc mount, va dieu huong sau dang
          nhap la dieu huong phia client: khong co lan mount thu hai nao de
          `/auth/me` tu chay lai. Khong co dong nay thi ca mot phien bat dau
          bang man dang nhap se khong bao gio biet `message_max_chars` —
          nguoi dung go bao nhieu cung khong thay bo dem, roi nhan `422`.

          Loi o day KHONG lam hong lan dang nhap: phien da that su mo (cookie
          da duoc dat), chi la phan "biet them" chua ve. `hoSo` o lai `null`
          va ben doc di duong lui cua no.
        */
        void api
          .me()
          .then((nextProfile) => {
            setProfile(nextProfile);
            setProfileReadAt(Date.now());
          })
          .catch(() => setProfile(null));
        // Tra `ra` chu khong `true`: caller phai dinh tuyen theo `status`
        // (§11.1) NGAY trong cung mot nhip, va `user` cua state thi chua
        // cap nhat o thoi diem promise nay resolve.
        return output;
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError(0, "HTTP_ERROR", String(e)));
        return null;
      }
    },
    [],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      await api.logout();
    } finally {
      // Xoa danh tinh o FE DU cho loi goi that bai: `POST /auth/logout` co y
      // khong doi xac thuc (NQ-42) va khong co ket cuc thu hai de bao, nen mot
      // loi o day gan nhu chac chan la mang chu khong phai "chua dang xuat".
      // Giu man hinh o trang thai "van dang dang nhap" chi lam nguoi dung
      // tuong minh chua thoat.
      setUser(null);
      setProfile(null);
      setLocked(false);
    }
  }, []);

  /*
    `build` nhan ban ho so se lam NEN cho body — de phan doi nao can doc nen
    (T-S.14: ghep mot muc vao `reasoning_prefs`) doc dung ban ay, ke ca khi
    no vua duoc hoi lai vi `hoSo` con `null`.
  */
  const saveWith = useCallback(
    async (build: (base: ProfileOut) => Partial<SettingsOut>): Promise<void> => {
      let base = profileRef.current;
      if (base === null) {
        base = await api.me();
        setProfileReadAt(Date.now());
      }
      const output = await api.updateSettings({
        default_model: base.default_model,
        display_name: base.display_name,
        avatar_color: base.avatar_color,
        reasoning_prefs: base.reasoning_prefs,
        ...build(base),
      });
      /*
        Doc lai tu RESPONSE chu khong tu `patch` vua gui: server la noi quyet
        dinh (vd. `display_name` da cat khoang trang, chuoi rong thanh `null` —
        T-S.5 Cam bay ②), va no tra `SettingsOut` dung de ben goi khong phai
        suy ra.

        `default_model` va `display_name` la cot cua hang `users`, nen `user`
        (`UserOut` cua login/refresh/me) cung mang — cap nhat mot cho roi de
        cho kia lech la dung cai bay B-213 noi toi.
      */
      const next: ProfileOut = { ...base, ...output };
      profileRef.current = next;
      setProfile(next);
      setUser((prev) =>
        prev === null
          ? prev
          : { ...prev, default_model: output.default_model, display_name: output.display_name },
      );
    },
    [],
  );

  const saveSettings = useCallback(
    (patch: Partial<SettingsOut>): Promise<void> => saveWith(() => patch),
    [saveWith],
  );

  const changeDefaultModel = useCallback(
    (modelId: string | null): Promise<void> => saveSettings({ default_model: modelId }),
    [saveSettings],
  );

  const changeReasoningPref = useCallback(
    (modelId: string, level: string): Promise<void> =>
      saveWith((base) => ({ reasoning_prefs: { ...base.reasoning_prefs, [modelId]: level } })),
    [saveWith],
  );

  const refreshProfile = useCallback(async (): Promise<void> => {
    try {
      const output = await api.me();
      setProfile(output);
      setProfileReadAt(Date.now());
    } catch {
      // Giu `hoSo` cu — xem docstring `Phien.refreshProfile`.
    }
  }, []);

  return {
    user,
    profile,
    profileReadAt,
    loading,
    locked,
    error,
    login,
    logout,
    changeDefaultModel,
    saveSettings,
    changeReasoningPref,
    refreshProfile,
  };
}
