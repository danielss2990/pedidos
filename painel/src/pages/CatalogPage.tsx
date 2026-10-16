import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { api, download } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Empty, Field, Icon, Modal } from "../components/ui";
import { brl } from "../format";
import type { Page, Product } from "../types";

interface ImportResult {
  criados: number;
  atualizados: number;
  ignorados: number;
}

const UNITS = ["unidades", "metros", "rolos", "caixas", "pecas", "pacotes", "barras"];

export function formatAttributes(attrs: Record<string, string>): string {
  return Object.entries(attrs)
    .map(([k, v]) => `${k}=${v}`)
    .join("; ");
}

export function parseAttributes(text: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  for (const part of text.split(";")) {
    const [key, ...rest] = part.split("=");
    const value = rest.join("=").trim();
    if (key?.trim() && value) attrs[key.trim()] = value;
  }
  return attrs;
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

export default function CatalogPage() {
  const { can } = useAuth();
  const isAdmin = can("admin");
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const q = useDebounced(search, 300);

  const products = useQuery({
    queryKey: ["products", q, showInactive],
    queryFn: () =>
      api<Page<Product>>("/api/v1/products", {
        query: { q, ativo: showInactive ? undefined : true, limit: 200 },
      }),
  });
  const fileInput = useRef<HTMLInputElement>(null);
  const importFile = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("arquivo", file);
      return api<ImportResult>("/api/v1/products/import", { method: "POST", form });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["products"] }),
  });
  const exportFile = useMutation({
    mutationFn: () => download("/api/v1/products/export", { formato: "xlsx" }, "catalogo.xlsx"),
  });
  const items = products.data?.items ?? [];

  return (
    <div className="page">
      <header className="page-header">
        <h1>Catálogo</h1>
        <div className="search">
          <Icon name="search" size={16} />
          <input
            type="search"
            placeholder="Buscar por nome, SKU ou apelido"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Buscar produto"
          />
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
          />
          Mostrar inativos
        </label>
        {isAdmin && (
          <div className="actions">
            <input
              ref={fileInput}
              type="file"
              accept=".csv,.xlsx"
              hidden
              aria-label="Arquivo do catálogo"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) importFile.mutate(file);
                e.target.value = "";
              }}
            />
            <button
              className="btn"
              onClick={() => exportFile.mutate()}
              disabled={exportFile.isPending}
              title="Baixa o catálogo em XLSX; o mesmo arquivo serve de modelo para importar"
            >
              Exportar planilha
            </button>
            <button
              className="btn"
              onClick={() => fileInput.current?.click()}
              disabled={importFile.isPending}
            >
              <Icon name="refresh" /> {importFile.isPending ? "Importando…" : "Importar CSV/XLSX"}
            </button>
            <button className="btn primary" onClick={() => setEditing("new")}>
              <Icon name="plus" /> Novo produto
            </button>
          </div>
        )}
      </header>
      <ErrorBox error={products.error || importFile.error || exportFile.error} />
      {importFile.data && (
        <div className="notice good" role="status">
          Importação concluída: {importFile.data.criados} criado(s), {importFile.data.atualizados}{" "}
          atualizado(s)
          {importFile.data.ignorados > 0 &&
            `, ${importFile.data.ignorados} linha(s) ignorada(s) por falta de SKU, nome ou preço`}
          .
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th>Produto</th>
              <th>Categoria</th>
              <th>Unidade</th>
              <th className="num">Preço</th>
              {isAdmin && <th aria-label="Ações" />}
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id} className={p.ativo ? "" : "inactive"}>
                <td className="mono">{p.sku}</td>
                <td>
                  {p.nome_tecnico}
                  {p.sinonimos.length > 0 && (
                    <small className="muted block">Também: {p.sinonimos.join(", ")}</small>
                  )}
                </td>
                <td>{p.categoria ?? "—"}</td>
                <td>{p.unidade_venda}</td>
                <td className="num">{brl(p.preco)}</td>
                {isAdmin && (
                  <td>
                    <button className="btn small ghost" onClick={() => setEditing(p)}>
                      Editar
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {products.isSuccess && items.length === 0 && (
          <Empty title="Nenhum produto encontrado">
            {isAdmin ? "Cadastre produtos ou sincronize a planilha do catálogo." : null}
          </Empty>
        )}
      </div>
      {editing && (
        <ProductForm
          product={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void queryClient.invalidateQueries({ queryKey: ["products"] });
          }}
        />
      )}
    </div>
  );
}

function ProductForm({
  product,
  onClose,
  onSaved,
}: {
  product: Product | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    sku: product?.sku ?? "",
    nome_tecnico: product?.nome_tecnico ?? "",
    categoria: product?.categoria ?? "",
    unidade_venda: product?.unidade_venda ?? "unidades",
    preco: product?.preco ?? "",
    atributos: formatAttributes(product?.atributos ?? {}),
    sinonimos: (product?.sinonimos ?? []).join("; "),
    ativo: product?.ativo ?? true,
  });
  const set = (key: keyof typeof form) => (value: string | boolean) =>
    setForm((f) => ({ ...f, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const body = {
        nome_tecnico: form.nome_tecnico.trim(),
        categoria: form.categoria.trim() || null,
        unidade_venda: form.unidade_venda,
        preco: form.preco.replace(",", "."),
        atributos: parseAttributes(form.atributos),
        sinonimos: form.sinonimos
          .split(";")
          .map((s) => s.trim())
          .filter(Boolean),
        ativo: form.ativo,
      };
      return product
        ? api(`/api/v1/products/${product.id}`, { method: "PATCH", body })
        : api("/api/v1/products", { method: "POST", body: { ...body, sku: form.sku.trim() } });
    },
    onSuccess: onSaved,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <Modal
      title={product ? `Editar ${product.sku}` : "Novo produto"}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn primary" type="submit" form="product-form" disabled={save.isPending}>
            Salvar
          </button>
        </>
      }
    >
      <form id="product-form" className="form-grid" onSubmit={submit}>
        <Field label="SKU">
          <input
            required
            value={form.sku}
            disabled={!!product}
            onChange={(e) => set("sku")(e.target.value)}
          />
        </Field>
        <Field label="Preço (R$)">
          <input
            required
            inputMode="decimal"
            value={form.preco}
            onChange={(e) => set("preco")(e.target.value)}
          />
        </Field>
        <Field label="Nome técnico">
          <input
            required
            value={form.nome_tecnico}
            onChange={(e) => set("nome_tecnico")(e.target.value)}
          />
        </Field>
        <Field label="Categoria">
          <input value={form.categoria} onChange={(e) => set("categoria")(e.target.value)} />
        </Field>
        <Field label="Unidade de venda">
          <select value={form.unidade_venda} onChange={(e) => set("unidade_venda")(e.target.value)}>
            {UNITS.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </select>
        </Field>
        <Field
          label="Atributos"
          hint="Ex.: bitola_mm2=2.5; cor=Azul. Chaves: bitola_mm2, corrente_a, tensao_v, cor, polos, potencia_w, diametro_mm, tipo."
        >
          <input value={form.atributos} onChange={(e) => set("atributos")(e.target.value)} />
        </Field>
        <Field label="Apelidos e gírias" hint="Separados por ponto e vírgula.">
          <input value={form.sinonimos} onChange={(e) => set("sinonimos")(e.target.value)} />
        </Field>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.ativo}
            onChange={(e) => set("ativo")(e.target.checked)}
          />
          Produto ativo
        </label>
      </form>
      <ErrorBox error={save.error} />
    </Modal>
  );
}
