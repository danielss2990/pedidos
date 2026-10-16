// Cliente HTTP da API. O access token fica só em memória; o refresh token é um
// cookie httpOnly que a API grava em /api/v1/auth.

import type { User } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Upload de arquivo (multipart); o navegador define o Content-Type. */
  form?: FormData;
  query?: Query;
}

let accessToken: string | null = null;
let refreshing: Promise<User | null> | null = null;
let onSessionExpired: () => void = () => {};

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler;
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const field = first.loc?.slice(-1)[0];
    return field ? `${String(field)}: ${first.msg}` : (first.msg ?? "Dados inválidos");
  }
  return status >= 500 ? "Erro no servidor. Tente de novo." : `Erro ${status}`;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  return fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
    credentials: "same-origin",
  });
}

/** Renova o access token pelo cookie. Chamadas simultâneas compartilham a mesma renovação. */
export function refreshSession(): Promise<User | null> {
  refreshing ??= (async () => {
    try {
      const res = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!res.ok) return null;
      const data = (await res.json()) as { access_token: string; user: User };
      accessToken = data.access_token;
      return data.user;
    } catch {
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function request(path: string, options: RequestOptions = {}): Promise<Response> {
  let res = await send(path, options);
  if (res.status === 401 && !path.startsWith("/api/v1/auth/")) {
    const user = await refreshSession();
    if (user) {
      res = await send(path, options);
    } else {
      accessToken = null;
      onSessionExpired();
    }
  }
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(res.status, errorMessage(detail, res.status));
  }
  return res;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const res = await request(path, options);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function apiBlob(path: string, query?: Query): Promise<Blob> {
  return (await request(path, { query })).blob();
}

/** Baixa um arquivo da API (com o token) e oferece ao navegador para salvar. */
export async function download(path: string, query: Query, filename: string): Promise<void> {
  const blob = await apiBlob(path, query);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export async function login(email: string, senha: string): Promise<User> {
  const data = await api<{ access_token: string; user: User }>("/api/v1/auth/login", {
    method: "POST",
    body: { email, senha },
  });
  accessToken = data.access_token;
  return data.user;
}

export async function logout(): Promise<void> {
  try {
    await api("/api/v1/auth/logout", { method: "POST" });
  } finally {
    accessToken = null;
  }
}
