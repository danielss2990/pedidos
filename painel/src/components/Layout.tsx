import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { api } from "../api";
import { useAuth } from "../auth";
import { ROLE_LABEL } from "../format";
import type { Conversation, Order, Page } from "../types";
import { Icon } from "./ui";

export default function Layout() {
  const { user, can, signOut } = useAuth();

  // Conversas que pediram atendente e ainda não foram assumidas.
  const queue = useQuery({
    queryKey: ["conversations", "fila"],
    queryFn: () =>
      api<Page<Conversation>>("/api/v1/conversations", {
        query: { estado: "atendimento_humano", limit: 200 },
      }),
    refetchInterval: 10_000,
    select: (page) => page.items.filter((c) => c.atendente_id === null).length,
  });
  // Pedidos fechados pelo bot que ninguém da equipe começou a separar.
  const novos = useQuery({
    queryKey: ["orders", "novos"],
    queryFn: () => api<Page<Order>>("/api/v1/orders", { query: { status: "confirmado", limit: 1 } }),
    refetchInterval: 10_000,
    select: (page) => page.total,
  });

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            <Icon name="bolt" />
          </span>
          <span>Central de Pedidos</span>
        </div>
        <nav>
          <NavLink to="/conversas">
            <Icon name="chat" />
            <span>Conversas</span>
            {!!queue.data && (
              <span className="nav-badge" title="Aguardando atendente">
                {queue.data}
              </span>
            )}
          </NavLink>
          <NavLink to="/pedidos">
            <Icon name="cart" />
            <span>Pedidos</span>
            {!!novos.data && (
              <span className="nav-badge" title="Pedidos novos">
                {novos.data}
              </span>
            )}
          </NavLink>
          <NavLink to="/catalogo">
            <Icon name="box" />
            <span>Catálogo</span>
          </NavLink>
          {can("admin") && (
            <>
              <NavLink to="/configuracoes">
                <Icon name="clock" />
                <span>Horário</span>
              </NavLink>
              <NavLink to="/usuarios">
                <Icon name="users" />
                <span>Usuários</span>
              </NavLink>
            </>
          )}
        </nav>
        <div className="sidebar-user">
          <div>
            <strong>{user?.nome}</strong>
            <small>{user && ROLE_LABEL[user.perfil]}</small>
          </div>
          <button className="btn ghost small" onClick={() => void signOut()}>
            Sair
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
