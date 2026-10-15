import type { ConversationState, FormaPagamento, Modalidade, OrderStatus, Role } from "./types";

const brlFormat = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export function brl(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return brlFormat.format(Number(value));
}

export function quantity(value: string): string {
  return Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 3 });
}

/** 5511999998888 -> +55 (11) 99999-8888 */
export function phone(e164: string | null): string {
  if (!e164) return "Cliente anonimizado";
  const m = /^55(\d{2})(\d{4,5})(\d{4})$/.exec(e164);
  return m ? `+55 (${m[1]}) ${m[2]}-${m[3]}` : `+${e164}`;
}

export function dateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function time(iso: string): string {
  return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

/** "agora", "há 5 min", "há 2 h", "ontem", ou a data. */
export function relative(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const diff = (now.getTime() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "agora";
  if (diff < 3600) return `há ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `há ${Math.floor(diff / 3600)} h`;
  if (diff < 172800) return "ontem";
  return new Date(iso).toLocaleDateString("pt-BR");
}

export const STATE_LABEL: Record<ConversationState, string> = {
  coletando: "Com o bot",
  aguardando_confirmacao: "Aguardando confirmação",
  fechando: "Fechando pedido",
  pedido_em_andamento: "Pedido em andamento",
  atendimento_humano: "Atendimento humano",
};

export const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  rascunho: "Rascunho",
  aguardando_confirmacao: "Aguardando confirmação",
  fechando: "Fechando com o cliente",
  confirmado: "Novo",
  em_separacao: "Em separação",
  pronto: "Pronto",
  concluido: "Concluído",
  cancelado: "Cancelado",
};

export const MODALIDADE_LABEL: Record<Modalidade, string> = {
  retirada: "Retirada",
  entrega: "Entrega",
};

export const PAGAMENTO_LABEL: Record<FormaPagamento, string> = {
  pix: "Pix",
  cartao: "Cartão",
  dinheiro: "Dinheiro",
};

/** "Pronto" significa coisas diferentes para retirada e entrega. */
export function orderStatusLabel(status: OrderStatus, modalidade: Modalidade | null): string {
  if (status === "pronto") {
    return modalidade === "entrega" ? "Saiu para entrega" : "Pronto para retirada";
  }
  return ORDER_STATUS_LABEL[status];
}

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Administrador",
  supervisor: "Supervisor",
  atendente: "Atendente",
};

export const WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];

export function customerName(c: { nome: string | null; nome_whatsapp: string | null; telefone_e164: string | null }): string {
  return c.nome || c.nome_whatsapp || phone(c.telefone_e164);
}
