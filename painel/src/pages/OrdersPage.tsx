import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { ErrorBox, Empty, Icon, Modal, OrderBadge } from "../components/ui";
import { ORDER_STATUS_LABEL, brl, customerName, dateTime, phone, quantity } from "../format";
import type { Order, OrderStatus, Page } from "../types";

const PAGE_SIZE = 50;

export default function OrdersPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<OrderStatus | "">("");
  const [page, setPage] = useState(0);

  const orders = useQuery({
    queryKey: ["orders", status, page],
    queryFn: () =>
      api<Page<Order>>("/api/v1/orders", {
        query: { status, limit: PAGE_SIZE, offset: page * PAGE_SIZE },
      }),
    refetchInterval: 15_000,
  });
  const selected = useQuery({
    queryKey: ["order", id],
    queryFn: () => api<Order>(`/api/v1/orders/${id}`),
    enabled: !!id,
  });
  const total = orders.data?.total ?? 0;

  return (
    <div className="page">
      <header className="page-header">
        <h1>Pedidos</h1>
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
      </header>
      <ErrorBox error={orders.error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Nº</th>
              <th>Data</th>
              <th>Cliente</th>
              <th className="num">Itens</th>
              <th className="num">Total</th>
              <th>Status</th>
              <th>Planilha</th>
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
                <td className="num">{o.items.length}</td>
                <td className="num">{brl(o.total)}</td>
                <td>
                  <OrderBadge status={o.status} />
                </td>
                <td>{o.exportado_planilha_em ? "Exportado" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {orders.isSuccess && total === 0 && <Empty title="Nenhum pedido encontrado" />}
      </div>
      {total > PAGE_SIZE && (
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

      {id && (
        <Modal
          title={selected.data ? `Pedido nº ${selected.data.numero}` : "Pedido"}
          onClose={() => navigate("/pedidos")}
        >
          <ErrorBox error={selected.error} />
          {selected.data && <OrderDetail order={selected.data} />}
        </Modal>
      )}
    </div>
  );
}

function OrderDetail({ order }: { order: Order }) {
  return (
    <div className="order-detail">
      <dl className="facts">
        <div>
          <dt>Cliente</dt>
          <dd>
            {customerName(order.customer)} · {phone(order.customer.telefone_e164)}
          </dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <OrderBadge status={order.status} />
          </dd>
        </div>
        <div>
          <dt>Criado</dt>
          <dd>{dateTime(order.created_at)}</dd>
        </div>
        <div>
          <dt>Confirmado</dt>
          <dd>{dateTime(order.confirmado_em)}</dd>
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
          {order.items.map((it, i) => (
            <tr key={it.id}>
              <td>{i + 1}</td>
              <td>
                {it.item_normalizado}
                <small className="muted block">Cliente: “{it.descricao_original}”</small>
                {it.status === "pendente_duvida" && (
                  <small className="warning-text block">Aguardando resposta: {it.pergunta}</small>
                )}
              </td>
              <td className="num">
                {quantity(it.quantidade)} {it.unidade}
              </td>
              <td className="num">{brl(it.preco_unitario)}</td>
              <td className="num">
                {it.preco_unitario ? brl(Number(it.preco_unitario) * Number(it.quantidade)) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
        {order.total && (
          <tfoot>
            <tr>
              <td colSpan={4}>Total</td>
              <td className="num">
                <strong>{brl(order.total)}</strong>
              </td>
            </tr>
          </tfoot>
        )}
      </table>
      {order.cart_url && (
        <a className="btn" href={order.cart_url} target="_blank" rel="noreferrer">
          <Icon name="link" /> Abrir link do carrinho
        </a>
      )}
    </div>
  );
}
