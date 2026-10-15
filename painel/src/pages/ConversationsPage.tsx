import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Empty, Icon, OrderBadge, StateBadge } from "../components/ui";
import MessageBubble from "../components/MessageBubble";
import {
  MODALIDADE_LABEL,
  PAGAMENTO_LABEL,
  brl,
  customerName,
  phone,
  quantity,
  relative,
} from "../format";
import type { Conversation, Message, Order, Page } from "../types";

type FilterKey = "fila" | "minhas" | "andamento" | "bot" | "todas";

const FILTERS: {
  key: FilterKey;
  label: string;
  query: Record<string, string | boolean>;
  keep?: (c: Conversation) => boolean;
}[] = [
  {
    key: "fila",
    label: "Na fila",
    query: { estado: "atendimento_humano" },
    keep: (c) => c.atendente_id === null,
  },
  { key: "minhas", label: "Minhas", query: { minhas: true } },
  {
    key: "andamento",
    label: "Pedidos em andamento",
    query: { estado: "pedido_em_andamento" },
  },
  {
    key: "bot",
    label: "Com o bot",
    query: {},
    keep: (c) => ["coletando", "aguardando_confirmacao", "fechando"].includes(c.estado),
  },
  { key: "todas", label: "Todas", query: {} },
];

const SERVICE_WINDOW_MS = 24 * 3600 * 1000;

function preview(c: Conversation): string {
  const m = c.ultima_mensagem;
  if (!m) return "Sem mensagens";
  const prefix = m.enviado_por === "cliente" ? "" : m.enviado_por === "bot" ? "Bot: " : "Você: ";
  if (m.conteudo) return prefix + m.conteudo;
  return prefix + (m.tipo === "audio" ? "Áudio" : m.tipo === "imagem" ? "Foto" : "Mensagem");
}

export default function ConversationsPage() {
  const { id } = useParams();
  const [filter, setFilter] = useState<FilterKey>("fila");
  const current = FILTERS.find((f) => f.key === filter)!;

  const list = useQuery({
    queryKey: ["conversations", filter],
    queryFn: () =>
      api<Page<Conversation>>("/api/v1/conversations", { query: { ...current.query, limit: 100 } }),
    refetchInterval: 5_000,
  });
  const items = (list.data?.items ?? []).filter(current.keep ?? (() => true));

  return (
    <div className={`inbox ${id ? "has-selection" : ""}`}>
      <section className="inbox-list" aria-label="Conversas">
        <header className="page-header compact">
          <h1>Conversas</h1>
        </header>
        <div className="tabs" role="tablist">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              className={filter === f.key ? "active" : ""}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <ErrorBox error={list.error} />
        <ul className="conversation-list">
          {items.map((c) => (
            <li key={c.id}>
              <Link to={`/conversas/${c.id}`} className={c.id === id ? "selected" : ""}>
                <div className="row-top">
                  <strong>{customerName(c.customer)}</strong>
                  <small>{relative(c.ultimo_contato_cliente_em)}</small>
                </div>
                <p className="preview">{preview(c)}</p>
                <div className="row-bottom">
                  <StateBadge state={c.estado} />
                  {c.atendente && <small className="muted">{c.atendente.nome}</small>}
                </div>
              </Link>
            </li>
          ))}
        </ul>
        {list.isSuccess && items.length === 0 && (
          <Empty title="Nenhuma conversa aqui">
            {filter === "fila" ? "Ninguém está esperando atendente agora." : null}
          </Empty>
        )}
      </section>
      <section className="inbox-detail">
        {id ? (
          <ConversationDetail key={id} id={id} />
        ) : (
          <Empty title="Selecione uma conversa">
            As conversas que pedem atendente aparecem em “Na fila”.
          </Empty>
        )}
      </section>
    </div>
  );
}

function ConversationDetail({ id }: { id: string }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [texto, setTexto] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  const conversation = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api<Conversation>(`/api/v1/conversations/${id}`),
    refetchInterval: 5_000,
  });
  const messages = useQuery({
    queryKey: ["messages", id],
    queryFn: () => api<Message[]>(`/api/v1/conversations/${id}/messages`),
    refetchInterval: 4_000,
  });
  const orders = useQuery({
    queryKey: ["orders", "conversation", id],
    queryFn: () =>
      api<Page<Order>>("/api/v1/orders", { query: { conversation_id: id, limit: 5 } }),
    refetchInterval: 10_000,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["conversation", id] });
    void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    void queryClient.invalidateQueries({ queryKey: ["messages", id] });
  };
  const assume = useMutation({
    mutationFn: () => api(`/api/v1/conversations/${id}/assume`, { method: "POST" }),
    onSuccess: refresh,
  });
  const release = useMutation({
    mutationFn: () => api(`/api/v1/conversations/${id}/release`, { method: "POST" }),
    onSuccess: refresh,
  });
  const send = useMutation({
    mutationFn: (body: string) =>
      api(`/api/v1/conversations/${id}/messages`, { method: "POST", body: { texto: body } }),
    onSuccess: () => {
      setTexto("");
      refresh();
    },
  });

  const count = messages.data?.length ?? 0;
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [count]);

  if (conversation.error) return <ErrorBox error={conversation.error} />;
  const c = conversation.data;
  if (!c) return <div className="splash">Carregando…</div>;

  const mine = c.estado === "atendimento_humano" && c.atendente_id === user?.id;
  const last = c.ultimo_contato_cliente_em ? new Date(c.ultimo_contato_cliente_em).getTime() : 0;
  const windowOpen = Date.now() - last < SERVICE_WINDOW_MS;

  function submit() {
    const body = texto.trim();
    if (body && !send.isPending) send.mutate(body);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="conversation">
      <header className="conversation-header">
        <button
          className="btn icon-only ghost only-mobile"
          onClick={() => navigate("/conversas")}
          aria-label="Voltar"
        >
          <Icon name="back" />
        </button>
        <div className="who">
          <strong>{customerName(c.customer)}</strong>
          <small className="muted">{phone(c.customer.telefone_e164)}</small>
        </div>
        <StateBadge state={c.estado} />
        <div className="spacer" />
        {mine ? (
          <button className="btn" onClick={() => release.mutate()} disabled={release.isPending}>
            Devolver ao bot
          </button>
        ) : (
          <button
            className="btn primary"
            onClick={() => assume.mutate()}
            disabled={assume.isPending}
          >
            Assumir conversa
          </button>
        )}
      </header>
      <ErrorBox error={assume.error || release.error} />

      <div className="conversation-body">
        <div className="thread" aria-live="polite">
          {messages.data?.map((m) => <MessageBubble key={m.id} message={m} conversationId={id} />)}
          {messages.isSuccess && count === 0 && <Empty title="Sem mensagens" />}
          <div ref={bottom} />
        </div>
        <OrderPanel orders={orders.data?.items ?? []} />
      </div>

      <footer className="composer">
        {mine && windowOpen ? (
          <>
            <textarea
              rows={2}
              placeholder="Escreva uma resposta… (Enter envia, Shift+Enter quebra linha)"
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={onKey}
              maxLength={4096}
              aria-label="Mensagem"
            />
            <button
              className="btn primary"
              onClick={submit}
              disabled={!texto.trim() || send.isPending}
            >
              <Icon name="send" /> Enviar
            </button>
          </>
        ) : (
          <p className="composer-note">
            {mine
              ? "Já passaram 24 h desde a última mensagem do cliente. A Meta só permite mensagens de template; aguarde o cliente escrever."
              : c.estado === "atendimento_humano" && c.atendente
                ? `Em atendimento por ${c.atendente.nome}. Assuma a conversa para responder.`
                : c.estado === "atendimento_humano"
                  ? "O cliente pediu um atendente. Assuma a conversa para responder."
                  : "O bot está atendendo. Ao assumir, o bot fica em silêncio até você devolver a conversa."}
          </p>
        )}
      </footer>
      <ErrorBox error={send.error} />
    </div>
  );
}

function OrderPanel({ orders }: { orders: Order[] }) {
  const order = orders[0];
  return (
    <aside className="order-panel" aria-label="Pedido atual">
      <h2>Pedido</h2>
      {!order ? (
        <p className="muted">Nenhum pedido nesta conversa.</p>
      ) : (
        <>
          <div className="order-panel-head">
            <Link to={`/pedidos/${order.id}`}>Nº {order.numero}</Link>
            <OrderBadge status={order.status} modalidade={order.modalidade} />
          </div>
          <ul className="order-items">
            {order.items.map((it) => (
              <li key={it.id} className={it.status === "pendente_duvida" ? "pending" : ""}>
                <span>
                  {quantity(it.quantidade)} {it.unidade} · {it.item_normalizado}
                </span>
                {it.status === "pendente_duvida" ? (
                  <small>Aguardando resposta: {it.pergunta}</small>
                ) : (
                  <small>{brl(Number(it.preco_unitario) * Number(it.quantidade))}</small>
                )}
              </li>
            ))}
          </ul>
          {order.total && (
            <p className="order-total">
              Total <strong>{brl(order.total_final ?? order.total)}</strong>
            </p>
          )}
          {order.modalidade && (
            <dl className="order-closing">
              <dt>{MODALIDADE_LABEL[order.modalidade]}</dt>
              <dd>
                {order.endereco_entrega ??
                  (order.modalidade === "retirada" ? "Na loja" : "Endereço a confirmar")}
              </dd>
              {order.modalidade === "entrega" && (
                <>
                  <dt>Frete</dt>
                  <dd>{order.frete === null ? "A informar" : brl(order.frete)}</dd>
                </>
              )}
              {order.forma_pagamento && (
                <>
                  <dt>Pagamento</dt>
                  <dd>
                    {PAGAMENTO_LABEL[order.forma_pagamento]}
                    {order.troco_para ? ` (troco para ${order.troco_para})` : ""}
                    {order.pago_em ? " · pago" : ""}
                  </dd>
                </>
              )}
            </dl>
          )}
          {["confirmado", "em_separacao", "pronto"].includes(order.status) && (
            <Link className="btn small" to={`/pedidos/${order.id}`}>
              Acompanhar pedido
            </Link>
          )}
          {orders.length > 1 && (
            <p className="muted small-text">{orders.length - 1} pedido(s) anterior(es)</p>
          )}
        </>
      )}
    </aside>
  );
}
