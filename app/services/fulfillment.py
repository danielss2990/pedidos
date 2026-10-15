"""Fechamento do pedido pelo WhatsApp (entrega e pagamento) e acompanhamento pela equipe."""

import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    ACTIVE_ORDER_STATUSES,
    Conversation,
    ConversationState,
    FormaPagamento,
    Message,
    MessageDirection,
    MessageType,
    Modalidade,
    Order,
    OrderStatus,
    SentBy,
)
from app.services.text import brl, normalize
from app.services.whatsapp import Messenger

# Fora desta janela a Meta só aceita mensagens de template aprovadas.
SERVICE_WINDOW = timedelta(hours=24)

FORMA_LABEL = {
    FormaPagamento.PIX: "Pix",
    FormaPagamento.CARTAO: "Cartão",
    FormaPagamento.DINHEIRO: "Dinheiro",
}

TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CONFIRMADO: {OrderStatus.EM_SEPARACAO, OrderStatus.PRONTO, OrderStatus.CANCELADO},
    OrderStatus.EM_SEPARACAO: {OrderStatus.PRONTO, OrderStatus.CANCELADO},
    OrderStatus.PRONTO: {OrderStatus.CONCLUIDO, OrderStatus.CANCELADO},
}


class FulfillmentError(Exception):
    pass


# ------------------------------------------------------------------ perguntas ao cliente
def next_closing_step(order: Order) -> str | None:
    """Próxima informação que falta para fechar o pedido, ou None se está completo."""
    if order.modalidade is None:
        return "modalidade"
    if order.modalidade == Modalidade.ENTREGA and not order.endereco_entrega:
        return "endereco"
    if order.forma_pagamento is None:
        return "pagamento"
    if (
        order.forma_pagamento == FormaPagamento.DINHEIRO
        and order.modalidade == Modalidade.ENTREGA
        and order.troco_para is None
    ):
        return "troco"
    return None


def parse_modalidade(button_id: str | None, text: str) -> Modalidade | None:
    if button_id in (Modalidade.RETIRADA.value, Modalidade.ENTREGA.value):
        return Modalidade(button_id)
    t = normalize(text)
    if re.search(r"retir|busc|pego|pegar|vou ai|vou na loja", t):
        return Modalidade.RETIRADA
    if re.search(r"entreg|envi|mandar? (pra|para|aqui)|delivery", t):
        return Modalidade.ENTREGA
    return None


def parse_pagamento(button_id: str | None, text: str) -> FormaPagamento | None:
    if button_id in {f.value for f in FormaPagamento}:
        return FormaPagamento(button_id)
    t = normalize(text)
    if "pix" in t:
        return FormaPagamento.PIX
    if re.search(r"cart|credito|debito|maquin", t):
        return FormaPagamento.CARTAO
    if re.search(r"dinheiro|especie|a vista em notas", t):
        return FormaPagamento.DINHEIRO
    return None


def parse_troco(text: str) -> str:
    t = normalize(text)
    if not t or re.match(r"^(nao|n|sem troco|nao precisa|nao preciso|dispenso|ok)\b", t):
        return ""
    return text.strip()[:80]


def closing_message(order: Order, settings: Settings) -> str:
    total = brl(order.total or 0)
    forma = order.forma_pagamento
    lines = [f"Pedido nº {order.numero} confirmado!", "", f"Itens: {total}"]

    if order.modalidade == Modalidade.RETIRADA:
        local = f": {settings.loja_endereco}" if settings.loja_endereco else ""
        lines.append(f"Retirada na loja{local}")
    else:
        lines.append(f"Entrega em: {order.endereco_entrega}")

    onde = "na retirada" if order.modalidade == Modalidade.RETIRADA else "na entrega"
    if forma == FormaPagamento.PIX:
        lines.append("Pagamento: Pix")
    else:
        troco = f" (troco para {order.troco_para})" if order.troco_para else ""
        lines.append(f"Pagamento: {FORMA_LABEL[forma].lower()} {onde}{troco}")
    lines.append("")

    if order.modalidade == Modalidade.ENTREGA:
        lines.append("Nossa equipe vai calcular o frete e enviar o valor final por aqui.")
        if forma == FormaPagamento.PIX:
            lines.append("A chave Pix vai junto com o valor final.")
    else:
        if forma == FormaPagamento.PIX:
            lines.append(pix_line(order, settings))
        lines.append("Avisaremos por aqui quando estiver pronto para retirar.")
    return "\n".join(lines)


def pix_line(order: Order, settings: Settings) -> str:
    if not settings.pix_chave:
        return "Nossa equipe envia os dados do Pix por aqui."
    titular = f" ({settings.pix_titular})" if settings.pix_titular else ""
    return (
        f"Pague {brl(order.total_final or 0)} pela chave Pix {settings.pix_chave}{titular} "
        "e envie o comprovante por aqui."
    )


def frete_message(order: Order, settings: Settings) -> str:
    lines = [
        f"Pedido nº {order.numero}: frete de {brl(order.frete or 0)}.",
        f"Total a pagar: {brl(order.total_final or 0)}.",
    ]
    if order.forma_pagamento == FormaPagamento.PIX:
        lines.append(pix_line(order, settings))
    elif order.forma_pagamento is not None:
        lines.append(f"Pagamento em {FORMA_LABEL[order.forma_pagamento].lower()} na entrega.")
    return "\n".join(lines)


def status_message(order: Order, settings: Settings) -> str | None:
    n = order.numero
    if order.status == OrderStatus.EM_SEPARACAO:
        return f"Seu pedido nº {n} está sendo separado."
    if order.status == OrderStatus.PRONTO:
        if order.modalidade == Modalidade.ENTREGA:
            return f"Seu pedido nº {n} saiu para entrega."
        local = f" em {settings.loja_endereco}" if settings.loja_endereco else ""
        return f"Seu pedido nº {n} está pronto para retirada{local}."
    if order.status == OrderStatus.CONCLUIDO:
        return (
            f"Pedido nº {n} concluído. Obrigado pela preferência! "
            "Quando precisar, é só mandar a lista por aqui."
        )
    if order.status == OrderStatus.CANCELADO:
        return f"Seu pedido nº {n} foi cancelado. Se precisar, é só mandar uma nova lista por aqui."
    return None


# ------------------------------------------------------------------ ações da equipe
class TeamActions:
    """Ações do painel sobre um pedido fechado; avisam o cliente quando possível."""

    def __init__(
        self,
        session: AsyncSession,
        messenger: Messenger,
        settings: Settings,
        user_id: uuid.UUID,
        now: datetime,
    ):
        self.session = session
        self.messenger = messenger
        self.settings = settings
        self.user_id = user_id
        self.now = now
        self.aviso: str | None = None

    async def set_frete(self, order: Order, conversation: Conversation, valor) -> bool:
        if order.modalidade != Modalidade.ENTREGA:
            raise FulfillmentError("Só pedidos com entrega têm frete")
        if order.status not in ACTIVE_ORDER_STATUSES:
            raise FulfillmentError("O pedido não está em andamento")
        order.frete = valor
        return await self._notify(conversation, frete_message(order, self.settings))

    def set_paid(self, order: Order, pago: bool) -> None:
        if order.status in (OrderStatus.RASCUNHO, OrderStatus.AGUARDANDO_CONFIRMACAO):
            raise FulfillmentError("O pedido ainda não foi fechado")
        order.pago_em = self.now if pago else None

    async def change_status(
        self, order: Order, conversation: Conversation, new: OrderStatus
    ) -> bool:
        allowed = TRANSITIONS.get(order.status, set())
        if new not in allowed:
            raise FulfillmentError(
                f"Não é possível passar de {order.status.value} para {new.value}"
            )
        if (
            new == OrderStatus.PRONTO
            and order.modalidade == Modalidade.ENTREGA
            and order.frete is None
        ):
            raise FulfillmentError("Informe o frete antes de enviar o pedido para entrega")
        order.status = new
        if new in (OrderStatus.CONCLUIDO, OrderStatus.CANCELADO):
            await self._release_conversation(order, conversation)
        message = status_message(order, self.settings)
        return await self._notify(conversation, message) if message else False

    async def _release_conversation(self, order: Order, conversation: Conversation) -> None:
        """Sem outros pedidos em andamento, o bot volta a atender o cliente."""
        others = await self.session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.conversation_id == conversation.id,
                Order.id != order.id,
                Order.status.in_(ACTIVE_ORDER_STATUSES),
            )
        )
        if not others and conversation.estado == ConversationState.PEDIDO_EM_ANDAMENTO:
            conversation.estado = ConversationState.COLETANDO
            conversation.aviso_pedido_em_andamento_em = None

    async def _notify(self, conversation: Conversation, text: str) -> bool:
        phone = conversation.customer.telefone_e164
        if phone is None:
            self.aviso = "Cliente anonimizado: mensagem não enviada."
            return False
        last = conversation.ultimo_contato_cliente_em
        if last is None or self.now - last > SERVICE_WINDOW:
            self.aviso = (
                "O cliente não escreve há mais de 24 h; a Meta só permite mensagens de template. "
                "Avise o cliente quando ele voltar a escrever."
            )
            return False
        wa_id = await self.messenger.send_text(phone, text)
        self.session.add(
            Message(
                conversation_id=conversation.id,
                wa_message_id=wa_id,
                direcao=MessageDirection.SAIDA,
                tipo=MessageType.TEXTO,
                conteudo=text,
                enviado_por=SentBy.ATENDENTE,
                user_id=self.user_id,
            )
        )
        return True
