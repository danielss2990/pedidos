import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

import { ORDER_STATUS_LABEL, STATE_LABEL } from "../format";
import type { ConversationState, OrderStatus } from "../types";

const ICONS: Record<string, string> = {
  bolt: "M13 2 4 14h7l-1 8 9-12h-7z",
  chat: "M4 5h16v11H8l-4 4z",
  cart: "M3 4h2l2.5 11h10.5l2-8H6.2 M9 20h.01 M17 20h.01",
  box: "M3 7l9-4 9 4-9 4-9-4z M3 7v10l9 4 9-4V7 M12 11v10",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
  users: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M2 21c0-4 3-6 7-6s7 2 7 6 M17 11a3 3 0 1 0 0-6 M22 21c0-3-2-5-5-5.5",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M21 21l-5-5",
  send: "M4 12 20 4l-6 16-3-7z",
  refresh: "M20 11a8 8 0 0 0-14-5L4 8 M4 4v4h4 M4 13a8 8 0 0 0 14 5l2-2 M20 20v-4h-4",
  plus: "M12 5v14 M5 12h14",
  link: "M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1 M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z M5 11a7 7 0 0 0 14 0 M12 18v3",
  image: "M4 5h16v14H4z M4 16l5-5 4 4 3-3 4 4 M15 9h.01",
  back: "M15 5l-7 7 7 7",
  close: "M6 6l12 12 M18 6 6 18",
};

export function Icon({ name, size = 18 }: { name: keyof typeof ICONS | string; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={ICONS[name]} />
    </svg>
  );
}

const STATE_TONE: Record<ConversationState, string> = {
  coletando: "info",
  aguardando_confirmacao: "warning",
  atendimento_humano: "critical",
  concluido: "neutral",
};

const ORDER_TONE: Record<OrderStatus, string> = {
  rascunho: "neutral",
  aguardando_confirmacao: "warning",
  confirmado: "info",
  carrinho_enviado: "info",
  pago: "good",
  cancelado: "neutral",
};

export function StateBadge({ state }: { state: ConversationState }) {
  return <span className={`badge ${STATE_TONE[state]}`}>{STATE_LABEL[state]}</span>;
}

export function OrderBadge({ status }: { status: OrderStatus }) {
  return <span className={`badge ${ORDER_TONE[status]}`}>{ORDER_STATUS_LABEL[status]}</span>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Algo deu errado.";
  return (
    <div className="error-box" role="alert">
      {message}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = dialog.current;
    if (el && !el.open) el.showModal?.();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="modal"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      aria-label={title}
    >
      <header>
        <h2>{title}</h2>
        <button className="btn icon-only ghost" onClick={onClose} aria-label="Fechar">
          <Icon name="close" />
        </button>
      </header>
      <div className="modal-body">{children}</div>
      {footer && <footer>{footer}</footer>}
    </dialog>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
