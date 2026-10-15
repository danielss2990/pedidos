import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";

import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field, Icon, Modal } from "../components/ui";
import { ROLE_LABEL } from "../format";
import type { Role, User } from "../types";

const ROLES: Role[] = ["admin", "supervisor", "atendente"];

export default function UsersPage() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);

  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/api/v1/users") });
  const update = useMutation({
    mutationFn: ({ id, ...body }: Partial<User> & { id: string }) =>
      api(`/api/v1/users/${id}`, { method: "PATCH", body }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <div className="page">
      <header className="page-header">
        <h1>Usuários</h1>
        <div className="actions">
          <button className="btn primary" onClick={() => setCreating(true)}>
            <Icon name="plus" /> Novo usuário
          </button>
        </div>
      </header>
      <ErrorBox error={users.error || update.error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>E-mail</th>
              <th>Perfil</th>
              <th>Situação</th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id} className={u.ativo ? "" : "inactive"}>
                <td>{u.nome}</td>
                <td>{u.email}</td>
                <td>
                  <select
                    value={u.perfil}
                    disabled={u.id === me?.id}
                    onChange={(e) => update.mutate({ id: u.id, perfil: e.target.value as Role })}
                    aria-label={`Perfil de ${u.nome}`}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABEL[r]}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <button
                    className="btn small ghost"
                    disabled={u.id === me?.id}
                    onClick={() => update.mutate({ id: u.id, ativo: !u.ativo })}
                  >
                    {u.ativo ? "Desativar" : "Reativar"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {creating && (
        <CreateUser
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false);
            void queryClient.invalidateQueries({ queryKey: ["users"] });
          }}
        />
      )}
    </div>
  );
}

function CreateUser({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ nome: "", email: "", senha: "", perfil: "atendente" as Role });
  const save = useMutation({
    mutationFn: () => api("/api/v1/users", { method: "POST", body: form }),
    onSuccess: onSaved,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <Modal
      title="Novo usuário"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn primary" type="submit" form="user-form" disabled={save.isPending}>
            Criar usuário
          </button>
        </>
      }
    >
      <form id="user-form" className="form-grid" onSubmit={submit}>
        <Field label="Nome">
          <input
            required
            minLength={2}
            value={form.nome}
            onChange={(e) => setForm({ ...form, nome: e.target.value })}
          />
        </Field>
        <Field label="E-mail">
          <input
            required
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </Field>
        <Field label="Senha inicial" hint="Mínimo de 8 caracteres.">
          <input
            required
            type="password"
            minLength={8}
            autoComplete="new-password"
            value={form.senha}
            onChange={(e) => setForm({ ...form, senha: e.target.value })}
          />
        </Field>
        <Field label="Perfil">
          <select
            value={form.perfil}
            onChange={(e) => setForm({ ...form, perfil: e.target.value as Role })}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
        </Field>
      </form>
      <ErrorBox error={save.error} />
    </Modal>
  );
}
