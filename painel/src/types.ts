// Espelha os schemas da API (app/schemas.py).

export type Role = "admin" | "supervisor" | "atendente";

export type ConversationState =
  | "coletando"
  | "aguardando_confirmacao"
  | "fechando"
  | "pedido_em_andamento"
  | "atendimento_humano";

export type OrderStatus =
  | "rascunho"
  | "aguardando_confirmacao"
  | "fechando"
  | "confirmado"
  | "em_separacao"
  | "pronto"
  | "concluido"
  | "cancelado";

export type Modalidade = "retirada" | "entrega";
export type FormaPagamento = "pix" | "cartao" | "dinheiro";

export type MessageType = "texto" | "audio" | "imagem" | "botao" | "localizacao" | "outro";
export type SentBy = "cliente" | "bot" | "atendente";

export interface User {
  id: string;
  nome: string;
  email: string;
  perfil: Role;
  ativo: boolean;
}

export interface Customer {
  id: string;
  telefone_e164: string | null;
  nome_whatsapp: string | null;
  nome: string | null;
}

export interface MessagePreview {
  conteudo: string | null;
  tipo: MessageType;
  enviado_por: SentBy;
  created_at: string;
}

export interface Conversation {
  id: string;
  estado: ConversationState;
  atendente_id: string | null;
  atendente: { id: string; nome: string } | null;
  ultimo_contato_cliente_em: string | null;
  updated_at: string;
  customer: Customer;
  ultima_mensagem: MessagePreview | null;
}

export interface Message {
  id: string;
  direcao: "entrada" | "saida";
  tipo: MessageType;
  conteudo: string | null;
  transcricao: string | null;
  media_path: string | null;
  media_mime: string | null;
  enviado_por: SentBy;
  user_id: string | null;
  created_at: string;
}

export interface OrderItem {
  id: string;
  posicao: number;
  product_id: string | null;
  descricao_original: string;
  item_normalizado: string;
  quantidade: string;
  unidade: string;
  preco_unitario: string | null;
  confianca: number | null;
  status: "ok" | "pendente_duvida";
  pergunta: string | null;
}

export interface Order {
  id: string;
  numero: number;
  status: OrderStatus;
  total: string | null;
  modalidade: Modalidade | null;
  endereco_entrega: string | null;
  forma_pagamento: FormaPagamento | null;
  troco_para: string | null;
  frete: string | null;
  total_final: string | null;
  pago_em: string | null;
  confirmado_em: string | null;
  exportado_planilha_em: string | null;
  created_at: string;
  customer: Customer;
  items: OrderItem[];
}

export interface Product {
  id: string;
  sku: string;
  nome_tecnico: string;
  categoria: string | null;
  atributos: Record<string, string>;
  unidade_venda: string;
  preco: string;
  ativo: boolean;
  sinonimos: string[];
}

export interface BusinessHours {
  dia_semana: number;
  abre: string;
  fecha: string;
}

export interface OrderAction {
  order: Order;
  mensagem_enviada: boolean;
  aviso: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
}
