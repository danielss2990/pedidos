import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, errorMessage, login, setAccessToken } from "./api";
import { AuthProvider } from "./auth";
import { brl, customerName, phone, quantity, relative } from "./format";
import { formatAttributes, parseAttributes } from "./pages/CatalogPage";
import LoginPage from "./pages/LoginPage";
import { toRows } from "./pages/SettingsPage";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("formatação", () => {
  it("formata reais, quantidades e telefones", () => {
    expect(brl("1234.5").replace(/\s/g, " ")).toBe("R$ 1.234,50");
    expect(brl(null)).toBe("—");
    expect(quantity("2.500")).toBe("2,5");
    expect(phone("5511999998888")).toBe("+55 (11) 99999-8888");
    expect(phone(null)).toBe("Cliente anonimizado");
    expect(customerName({ nome: null, nome_whatsapp: "Maria", telefone_e164: "55" })).toBe("Maria");
  });

  it("descreve tempo relativo", () => {
    const now = new Date("2026-10-14T12:00:00Z");
    expect(relative("2026-10-14T11:59:30Z", now)).toBe("agora");
    expect(relative("2026-10-14T11:45:00Z", now)).toBe("há 15 min");
    expect(relative("2026-10-14T09:00:00Z", now)).toBe("há 3 h");
    expect(relative("2026-10-13T10:00:00Z", now)).toBe("ontem");
  });
});

describe("conversões dos formulários", () => {
  it("atributos no formato da planilha", () => {
    expect(parseAttributes("bitola_mm2=2.5; cor=Azul; vazio=; =x")).toEqual({
      bitola_mm2: "2.5",
      cor: "Azul",
    });
    expect(formatAttributes({ bitola_mm2: "2.5", cor: "Azul" })).toBe("bitola_mm2=2.5; cor=Azul");
  });

  it("horário: dias sem cadastro aparecem fechados", () => {
    const rows = toRows([{ dia_semana: 0, abre: "08:00:00", fecha: "18:00:00" }]);
    expect(rows[0]).toEqual({ aberto: true, abre: "08:00", fecha: "18:00" });
    expect(rows[6].aberto).toBe(false);
    expect(rows).toHaveLength(7);
  });
});

describe("cliente da API", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken(null);
  });
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("transforma erros de validação do FastAPI em texto", () => {
    expect(errorMessage("Sem permissão", 403)).toBe("Sem permissão");
    expect(errorMessage([{ loc: ["body", "preco"], msg: "valor inválido" }], 422)).toBe(
      "preco: valor inválido",
    );
    expect(errorMessage(undefined, 502)).toMatch(/servidor/);
  });

  it("renova o token uma vez e repete a chamada após 401", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: "Token inválido" }))
      .mockResolvedValueOnce(json(200, { access_token: "novo", user: { id: "u" } }))
      .mockResolvedValueOnce(json(200, { ok: true }));

    await expect(api("/api/v1/orders")).resolves.toEqual({ ok: true });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/auth/refresh");
    const retry = fetchMock.mock.calls[2][1] as RequestInit;
    expect((retry.headers as Record<string, string>).Authorization).toBe("Bearer novo");
  });

  it("propaga ApiError quando a renovação falha", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, { detail: "Token inválido" }))
      .mockResolvedValueOnce(json(401, { detail: "Sessão expirada" }));
    await expect(api("/api/v1/orders")).rejects.toBeInstanceOf(ApiError);
  });

  it("envia query string sem parâmetros vazios", async () => {
    fetchMock.mockResolvedValueOnce(json(200, { items: [], total: 0 }));
    await api("/api/v1/orders", { query: { status: "", limit: 50, conversation_id: undefined } });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/orders?limit=50");
  });

  it("login guarda o token para as próximas chamadas", async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { access_token: "abc", user: { nome: "Ana" } }))
      .mockResolvedValueOnce(json(200, []));
    await login("ana@loja.com", "senha");
    await api("/api/v1/users");
    const call = fetchMock.mock.calls[1][1] as RequestInit;
    expect((call.headers as Record<string, string>).Authorization).toBe("Bearer abc");
  });
});

describe("tela de login", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("mostra a mensagem de erro da API", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { detail: "Sem sessão" })) // refresh ao abrir
      .mockResolvedValueOnce(json(401, { detail: "E-mail ou senha inválidos" }));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
    );
    await userEvent.type(screen.getByLabelText("E-mail"), "ana@loja.com");
    await userEvent.type(screen.getByLabelText("Senha"), "errada123");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("E-mail ou senha inválidos");
  });
});
