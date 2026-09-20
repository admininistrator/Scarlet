import { Component, type ErrorInfo, type ReactNode } from "react";

import { ServerErrorPage } from "./pages/ServerErrorPage";

interface Props {
  children: ReactNode;
}

interface State {
  error: unknown;
}

/**
 * Error boundary boc TOAN APP — T-3.1a.
 *
 * KH tham chieu: §16.3 · tasks.md T-3.1a.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  MOT CLASS COMPONENT, VA DO KHONG PHAI LUA CHON PHONG CACH             ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * React chua co hook nao tuong duong `getDerivedStateFromError` /
 * `componentDidCatch`; error boundary la thu DUY NHAT trong React 19 con bat
 * buoc phai la class. Neu khong co no, mot ngoai le luc render khong bi bat
 * se lam React thao SACH cay va de lai mot `<div id="root">` rong — mot man
 * hinh trang, khong mot dong chu nao, khong mot loi nao tren giao dien.
 *
 * `error: unknown` chu khong `Error`: `throw` trong JavaScript nem duoc moi
 * gia tri. Mot `throw "hong"` (chuoi) hay `throw { code: 500 }` deu toi day,
 * va go kieu no thanh `Error` la noi doi voi trinh bien dich ngay tai cho
 * dang xu ly hau qua cua mot thu khong theo quy tac nao.
 *
 * Ranh gioi voi `RouteErrorPage`: xem docstring cua `pages/ServerErrorPage`.
 * Tom tat — React Router bat ngoai le nem tu trong cay route; class nay bat
 * phan con lai.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Ghi ra console truoc khi ve trang 500: `ServerErrorPage` chi hien
    // `error.message`, con chuoi component dan toi cho nem thi chi o day moi
    // co. Mot bao cao loi khong co no la mot bao cao khong lan nguoc duoc.
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error !== null) {
      return <ServerErrorPage error={this.state.error} />;
    }
    return this.props.children;
  }
}
