import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { ErrorBox, Empty, Modal, OrderBadge } from "../components/ui";
import {
  MODALIDADE_LABEL,
  ORDER_STATUS_LABEL,
  PAGAMENTO_LABEL,
  brl,
  customerName,
  dateTime,
  phone,
  quantity,
} from "../format";
import type { Order, OrderAction, OrderStatus, Page } from "../types";

const PAGE_SIZE = 50;
type View = "andamento" | "todos";

export default function OrdersPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [view, setView] = useState<View>("andamento");
  const [status, setStatus] = useState<OrderStatus | "">("");
  const [page, setPage] = useState(0);

  const orders = useQuery({
    queryKey: ["orders", view, status, page],
    queryFn: () =>
      api<Page<Order>>("/api/v1/orders", {
        query:
          view === "andamento"
            ? { em_andamento: true, limit: 200 }
            : { status, limit: PAGE_SIZE, offset: page * PAGE_SIZE },
      }),
    refetchInterval: 10_000,
  });
  const total = orders.data?.total ?? 0;

  return (
    <div className="page">
      <header className="page-header">
        <h1>Pedidos</h1>
        <div className="tabs inline" role="tablist">
          {(
            [
              ["andamento", "Em andamento"],
              ["todos", "Todos"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={view === key}
              className={view === key ? "active" : ""}
              onClick={() => {
                setView(key);
                setPage(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {view === "todos" && (
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as OrderStatus | "");
              setPage(0);
            }}
            aria-label="Filtrar por status"
          >
            <option value="">Todos os status</option>
            {Object.entries(ORDER_STATUS_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        )}
      </header>
      <ErrorBox error={orders.error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Nº</th>
              <th>Fechado em</th>
              <th>Cliente</th>
              <th>Recebimento</th>
              <th>Pagamento</th>
              <th className="num">Total</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {orders.data?.items.map((o) => (
              <tr key={o.id} onClick={() => navigate(`/pedidos/${o.id}`)} className="clickable">
                <td>
                  <Link to={`/pedidos/${o.id}`}>{o.numero}</Link>
                </td>
                <td>{dateTime(o.confirmado_em ?? o.created_at)}</td>
                <td>{customerName(o.customer)}</td>
                <td>{o.modalidade ? MODALIDADE_LABEL[o.modalidade] : "—"}</td>
                <td>
                  {o.forma_pagamento ? PAGAMENTO_LABEL[o.forma_pagamento] : "—"}
                  {o.pago_em && <span className="badge good spaced">Pago</span>}
                </td>
                <td className="num">
                  <OrderTotal order={o} />
                </td>
                <td>
                  <OrderBadge status={o.status} modalidade={o.modalidade} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {orders.isSuccess && total === 0 && (
          <Empty title={view === "andamento" ? "Nenhum pedido em andamento" : "Nenhum pedido"}>
            {view === "andamento"
              ? "Pedidos fechados pelo bot aparecem aqui para a equipe separar e entregar."
              : null}
          </Empty>
        )}
      </div>
      {view === "todos" && total > PAGE_SIZE && (
        <div className="pager">
          <button className="btn small" disabled={page === 0} onClick={() => setPage(page - 1)}>
            Anterior
          </button>
          <span>
            {page * PAGE_SIZE + 1}–{Math.min(total, (page + 1) * PAGE_SIZE)} de {total}
          </span>
          <button
            className="btn small"
            disabled={(page + 1) * PAGE_SIZE >= total}
            onClick={() => setPage(page + 1)}
          >
            Próxima
          </button>
        </div>
      )}

      {id && <OrderModal id={id} onClose={() => navigate("/pedidos")} />}
    </div>
  );
}

function OrderTotal({ order }: { order: Order }) {
  if (order.modalidade === "entrega" && order.frete === null && order.total) {
    return (
      <span title="Frete ainda não informado">
        {brl(order.total)} <small className="muted">+ frete</small>
      </span>
    );
  }
  return <>{brl(order.total_final ?? order.total)}</>;
}

const NEXT_STEPS: Record<string, { status: OrderStatus; label: (o: Order) => string }[]> = {
  confirmado: [
    { status: "em_separacao", label: () => "Iniciar separação" },
    { status: "pronto", label: readyLabel },
  ],
  em_separacao: [{ status: "pronto", label: readyLabel }],
  pronto: [
    {
      status: "concluido",
      label: (o) => (o.modalidade === "entrega" ? "Marcar como entregue" : "Marcar como retirado"),
    },
  ],
};

function readyLabel(o: Order): string {
  return o.modalidade === "entrega" ? "Saiu para entrega" : "Pronto para retirada";
}

function OrderModal({ id, onClose }: { id: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState<{ tone: "good" | "warning"; text: string } | null>(
    null,
  );
  const order = useQuery({ queryKey: ["order", id], queryFn: () => api<Order>(`/api/v1/orders/${id}`) });

  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) =>
      api<OrderAction>(`/api/v1/orders/${id}/${path}`, { method: "POST", body }),
    onSuccess: (result) => {
      queryClient.setQueryData(["order", id], result.order);
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (result.aviso) setFeedback({ tone: "warning", text: result.aviso });
      else if (result.mensagem_enviada)
        setFeedback({ tone: "good", text: "Cliente avisado no WhatsApp." });
      else setFeedback({ tone: "good", text: "Pedido atualizado." });
    },
    onMutate: () => setFeedback(null),
  });

  const o = order.data;
  return (
    <Modal title={o ? `Pedido nº ${o.numero}` : "Pedido"} onClose={onClose}>
      <ErrorBox error={order.error} />
      {o && (
        <div className="order-detail">
          <dl className="facts">
            <div>
              <dt>Cliente</dt>
              <dd>
                {customerName(o.customer)}
                <small className="muted block">{phone(o.customer.telefone_e164)}</small>
              </dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <OrderBadge status={o.status} modalidade={o.modalidade} />
              </dd>
            </div>
            <div>
              <dt>Recebimento</dt>
              <dd>
                {o.modalidade ? MODALIDADE_LABEL[o.modalidade] : "—"}
                {o.endereco_entrega && (
                  <small className="muted block">{o.endereco_entrega}</small>
                )}
              </dd>
            </div>
            <div>
              <dt>Pagamento</dt>
              <dd>
                {o.forma_pagamento ? PAGAMENTO_LABEL[o.forma_pagamento] : "—"}{" "}
                {o.pago_em ? (
                  <span className="badge good">Pago</span>
                ) : (
                  o.forma_pagamento && <span className="badge warning">A receber</span>
                )}
                {o.troco_para && <small className="muted block">Troco para {o.troco_para}</small>}
              </dd>
            </div>
            <div>
              <dt>Fechado em</dt>
              <dd>{dateTime(o.confirmado_em)}</dd>
            </div>
          </dl>

          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Item</th>
                <th className="num">Qtd.</th>
                <th className="num">Preço</th>
                <th className="num">Subtotal</th>
              </tr>
            </thead>
            <tbody>
              {o.items.map((it, i) => (
                <tr key={it.id}>
                  <td>{i + 1}</td>
                  <td>
                    {it.item_normalizado}
                    <small className="muted block">Cliente: “{it.descricao_original}”</small>
                    {it.status === "pendente_duvida" && (
                      <small className="warning-text block">
                        Aguardando resposta: {it.pergunta}
                      </small>
                    )}
                  </td>
                  <td className="num">
                    {quantity(it.quantidade)} {it.unidade}
                  </td>
                  <td className="num">{brl(it.preco_unitario)}</td>
                  <td className="num">
                    {it.preco_unitario
                      ? brl(Number(it.preco_unitario) * Number(it.quantidade))
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
            {o.total && (
              <tfoot>
                {o.modalidade === "entrega" && (
                  <tr>
                    <td colSpan={4}>Frete</td>
                    <td className="num">{o.frete === null ? "a informar" : brl(o.frete)}</td>
                  </tr>
                )}
                <tr>
                  <td colSpan={4}>Total</td>
                  <td className="num">
                    <strong>{brl(o.total_final ?? o.total)}</strong>
                  </td>
                </tr>
              </tfoot>
            )}
          </table>

          <OrderActions order={o} busy={act.isPending} onAct={(path, body) => act.mutate({ path, body })} />
          {feedback && <div className={`notice ${feedback.tone}`}>{feedback.text}</div>}
          <ErrorBox error={act.error} />
        </div>
      )}
    </Modal>
  );
}

function OrderActions({
  order,
  busy,
  onAct,
}: {
  order: Order;
  busy: boolean;
  onAct: (path: string, body: unknown) => void;
}) {
  const [frete, setFrete] = useState(order.frete ?? "");
  const active = ["confirmado", "em_separacao", "pronto"].includes(order.status);
  const closed = !["rascunho", "aguardando_confirmacao", "fechando"].includes(order.status);
  if (!closed) {
    return (
      <p className="muted">O bot ainda está fechando este pedido com o cliente.</p>
    );
  }

  function sendFrete(e: FormEvent) {
    e.preventDefault();
    onAct("frete", { valor: frete.replace(",", ".") });
  }

  return (
    <section className="order-actions" aria-label="Ações do pedido">
      {active && order.modalidade === "entrega" && (
        <form className="frete-form" onSubmit={sendFrete}>
          <label htmlFor="frete">Frete (R$)</label>
          <input
            id="frete"
            inputMode="decimal"
            required
            value={frete}
            onChange={(e) => setFrete(e.target.value)}
            placeholder="0,00"
          />
          <button className="btn" type="submit" disabled={busy}>
            {order.frete === null ? "Enviar frete ao cliente" : "Atualizar frete"}
          </button>
        </form>
      )}
      <div className="action-row">
        {(NEXT_STEPS[order.status] ?? []).map((step) => (
          <button
            key={step.status}
            className="btn primary"
            disabled={busy}
            onClick={() => onAct("status", { status: step.status })}
          >
            {step.label(order)}
          </button>
        ))}
        <button
          className="btn"
          disabled={busy}
          onClick={() => onAct("pagamento", { pago: !order.pago_em })}
        >
          {order.pago_em ? "Desmarcar pago" : "Marcar como pago"}
        </button>
        {active && (
          <button
            className="btn danger"
            disabled={busy}
            onClick={() => {
              if (window.confirm(`Cancelar o pedido nº ${order.numero}? O cliente será avisado.`))
                onAct("status", { status: "cancelado" });
            }}
          >
            Cancelar pedido
          </button>
        )}
      </div>
    </section>
  );
}
