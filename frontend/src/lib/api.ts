// Wrapper fetch mong. Base URL doc tu bien moi truong Vite (A3: khong URL
// literal trong .tsx). Mac dinh "/api/v1" — cung origin voi nginx (Phu luc D),
// khong can biet host/port that cua backend.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, text || res.statusText);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
};
