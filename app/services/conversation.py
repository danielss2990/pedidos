"""Motor da conversa no WhatsApp: estados, dúvidas, resumo, confirmação e carrinho."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import (
    OPEN_ORDER_STATUSES,
    AiRun,
    Conversation,
    ConversationState,
    Customer,
    ItemStatus,
    Message,
    MessageDirection,
    MessageType,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    SentBy,
)
from app.services.business_hours import load_schedule
from app.services.cart import CartBuilder, CartError, variant_quantity
from app.services.catalog import Catalog
from app.services.extraction import (
    Extracao,
    ExtractionError,
    ExtractionInput,
    Extractor,
    ItemExtraido,
)
from app.services.media import MediaStore
from app.services.text import brl, qty
from app.services.transcription import Transcriber, TranscriptionError
from app.services.whatsapp import Button, IncomingMessage, Messenger

log = logging.getLogger(__name__)

BTN_CONFIRMAR = "confirmar"
BTN_CORRIGIR = "corrigir"
MAX_OPTIONS = 3
OFF_HOURS_NOTICE_INTERVAL = timedelta(hours=12)

# Unidades que podem ser tratadas como a mesma coisa ao casar pedido e catálogo.
UNIT_GROUPS = [{"unidades", "pecas", "pacotes"}, {"metros"}, {"rolos"}, {"caixas"}, {"barras"}]

MSG_WELCOME = (
    "Olá! Sou o assistente de pedidos. Pode mandar sua lista por texto, áudio ou foto "
    'e eu monto o orçamento. Quando terminar, é só dizer "é só isso".'
)
MSG_PRIVACY = "Usamos seu telefone e mensagens só para atender seus pedidos. Política: {url}"
MSG_OFF_HOURS = (
    "Olá! No momento estamos fora do horário de atendimento ({horario}). "
    "Mande sua mensagem nesse horário que respondemos. Obrigado!"
)
MSG_HELP = (
    "Pode me mandar os materiais que precisa (por texto, áudio ou foto da lista). "
    'Quando terminar, diga "é só isso" que eu mostro o resumo com os preços.'
)
MSG_ADDED_FOOTER = 'Algo mais? Quando terminar, é só dizer "é só isso".'
MSG_HANDOFF = "Vou chamar um atendente. Já já alguém da nossa equipe responde por aqui."
MSG_AUDIO_FAIL = "Não consegui entender o áudio. Pode mandar de novo ou escrever?"
MSG_NOT_UNDERSTOOD = "Desculpe, não entendi bem. Pode escrever de outro jeito?"
MSG_UNSUPPORTED = "Por enquanto consigo ler texto, áudio e foto. Pode mandar em um desses formatos?"
MSG_ILLEGIBLE = "Não consegui ler a foto com segurança. Pode mandar outra mais nítida ou digitar?"
MSG_EMPTY_ORDER = "Ainda não anotei nenhum item. Quais materiais você precisa?"
MSG_CORRECTION = (
    'O que deseja mudar? Pode dizer, por exemplo, "tira o item 2" ou '
    '"o item 1 são 20 metros".\n\n{itens}'
)
MSG_NOTHING_TO_CONFIRM = "Não há pedido aguardando confirmação. Quais materiais você precisa?"
MSG_REMINDER = "Ainda está por aí? Posso fechar o pedido? Se faltar algo, é só mandar."


@dataclass
class Services:
    settings: Settings
    messenger: Messenger
    extractor: Extractor
    transcriber: Transcriber
    cart: CartBuilder
    media: MediaStore
    now: Callable[[], datetime]


@dataclass
class Outcome:
    """Efeitos a executar depois do commit (ex.: exportar pedido para a planilha)."""

    export_order_ids: list[str] = field(default_factory=list)
    notify_panel: bool = False


def _same_unit(a: str, b: str) -> bool:
    return a == b or any(a in g and b in g for g in UNIT_GROUPS)


def item_line(numero: int, item: OrderItem) -> str:
    line = f"{numero}. {item.item_normalizado} — {qty(item.quantidade)} {item.unidade}"
    if item.status == ItemStatus.PENDENTE_DUVIDA:
        line += " (aguardando resposta)"
    return line


def subtotal(item: OrderItem) -> Decimal:
    return (item.preco_unitario or Decimal(0)) * item.quantidade


class ConversationEngine:
    def __init__(self, session: AsyncSession, services: Services):
        self.session = session
        self.s = services
        self.settings = services.settings
        self.catalog = Catalog(session, services.settings)
        self.outcome = Outcome()

    # ----------------------------------------------------------------- entrada
    async def handle(self, msg: IncomingMessage) -> Outcome:
        duplicate = await self.session.scalar(
            select(Message.id).where(Message.wa_message_id == msg.wa_message_id)
        )
        if duplicate:
            return self.outcome

        now = self.s.now()
        customer, conversation, is_new = await self._get_or_create(msg, now)
        self.customer, self.conversation = customer, conversation
        conversation.ultimo_contato_cliente_em = now
        conversation.lembrete_enviado_em = None

        stored = Message(
            conversation_id=conversation.id,
            wa_message_id=msg.wa_message_id,
            direcao=MessageDirection.ENTRADA,
            tipo=_message_type(msg.kind),
            conteudo=msg.text,
            media_mime=msg.media_mime,
            enviado_por=SentBy.CLIENTE,
        )
        self.session.add(stored)
        await self.session.flush()
        self.outcome.notify_panel = True

        media: bytes | None = None
        if msg.media_id:
            media, mime = await self.s.messenger.download_media(msg.media_id)
            stored.media_mime = msg.media_mime or mime
            stored.media_path = self.s.media.save(conversation.id, media, stored.media_mime)

        if is_new:
            await self._send(MSG_WELCOME)
            if self.settings.privacy_policy_url:
                await self._send(MSG_PRIVACY.format(url=self.settings.privacy_policy_url))
            customer.consentimento_em = now

        if conversation.estado == ConversationState.ATENDIMENTO_HUMANO:
            return self.outcome

        schedule = await load_schedule(self.session)
        if not schedule.is_open(now.astimezone(self.settings.tz)):
            last = conversation.aviso_fora_horario_em
            if last is None or now - last > OFF_HOURS_NOTICE_INTERVAL:
                await self._send(MSG_OFF_HOURS.format(horario=schedule.describe()))
                conversation.aviso_fora_horario_em = now
            return self.outcome

        if conversation.estado == ConversationState.CONCLUIDO:
            conversation.estado = ConversationState.COLETANDO

        if msg.kind == "other":
            await self._send(MSG_UNSUPPORTED)
            return self.outcome

        order = await self._open_order()

        if msg.kind == "button" and msg.button_id in (BTN_CONFIRMAR, BTN_CORRIGIR):
            if msg.button_id == BTN_CONFIRMAR:
                await self._confirm(order)
            else:
                await self._ask_correction(order)
            return self.outcome

        pending = self._first_pending(order)
        texto = (msg.text or "").strip()
        if pending and pending.opcoes and texto.isdigit():
            if await self._resolve_option(pending, int(texto)):
                await self._after_change(order, changed=True, finalizar=False)
                return self.outcome

        if msg.kind == "audio":
            try:
                texto = await self.s.transcriber.transcribe(media or b"", stored.media_mime or "")
            except TranscriptionError as exc:
                log.warning("transcrição falhou: %s", exc)
                await self._send(MSG_AUDIO_FAIL)
                return self.outcome
            stored.transcricao = texto
            self.session.add(
                AiRun(message_id=stored.id, provedor="openai", modelo=self.settings.whisper_model)
            )

        data = ExtractionInput(
            estado=conversation.estado.value,
            pedido_atual=[item_line(i, it) for i, it in enumerate(order.items, 1)],
            duvida_pendente=await self._pending_context(pending) if pending else None,
            texto=texto or None,
            tipo={"audio": "audio", "image": "imagem"}.get(msg.kind, "texto"),
            imagem=media if msg.kind == "image" else None,
            imagem_mime=stored.media_mime if msg.kind == "image" else None,
        )
        try:
            result = await self.s.extractor.extract(data)
        except ExtractionError as exc:
            log.warning("extração falhou: %s", exc)
            self.session.add(
                AiRun(
                    message_id=stored.id,
                    provedor="anthropic",
                    modelo=self.settings.claude_model,
                    erro=str(exc),
                )
            )
            await self._count_failure_or_handoff()
            if conversation.estado != ConversationState.ATENDIMENTO_HUMANO:
                await self._send(MSG_NOT_UNDERSTOOD)
            return self.outcome

        self.session.add(
            AiRun(
                message_id=stored.id,
                provedor="anthropic",
                modelo=result.modelo,
                tokens_entrada=result.tokens_entrada,
                tokens_saida=result.tokens_saida,
                latencia_ms=result.latencia_ms,
                saida=result.raw,
            )
        )
        await self._apply(order, result.extracao, pending)
        return self.outcome

    # ------------------------------------------------------------- aplicação
    async def _apply(self, order: Order, ex: Extracao, pending: OrderItem | None) -> None:
        if ex.falar_com_atendente:
            await self._handoff()
            return

        changed = False
        added: list[OrderItem] = []

        if pending and ex.opcao_escolhida is not None:
            changed |= await self._resolve_option(pending, ex.opcao_escolhida)

        visible = list(order.items)
        for alt in ex.alteracoes:
            if not 1 <= alt.numero_item <= len(visible):
                continue
            item = visible[alt.numero_item - 1]
            if alt.remover:
                order.items.remove(item)
                changed = True
            elif alt.nova_quantidade and alt.nova_quantidade > 0:
                item.quantidade = Decimal(variant_quantity(Decimal(str(alt.nova_quantidade))))
                changed = True

        for novo in ex.itens_novos:
            current_pending = self._first_pending(order)
            if novo.responde_duvida_pendente and current_pending is not None:
                order.items.remove(current_pending)
            added.append(await self._add_item(order, novo))
            changed = True

        if changed and pending is not None and self._first_pending(order) is pending:
            # O cliente respondeu, mas a mesma dúvida continua aberta.
            if await self._count_failure_or_handoff():
                return
        elif pending is not None and self._first_pending(order) is not pending:
            self.conversation.duvidas_sem_solucao = 0

        if ex.confirmar_pedido and not changed:
            await self._confirm(order)
            return
        if ex.corrigir_pedido and not changed:
            await self._ask_correction(order)
            return
        if changed or ex.finalizar_pedido:
            await self._after_change(order, changed, ex.finalizar_pedido, added)
            return
        if ex.imagem_ilegivel:
            await self._send(MSG_ILLEGIBLE)
        elif ex.resposta_livre:
            await self._send(ex.resposta_livre)
        elif pending is not None:
            await self._ask_pending(pending)
        else:
            await self._send(MSG_HELP)

    async def _after_change(
        self,
        order: Order,
        changed: bool,
        finalizar: bool,
        added: list[OrderItem] | None = None,
    ) -> None:
        if changed and self.conversation.estado == ConversationState.AGUARDANDO_CONFIRMACAO:
            self.conversation.estado = ConversationState.COLETANDO
            order.status = OrderStatus.RASCUNHO

        if finalizar:
            order.finalizar_pendente = True

        pending = self._first_pending(order)
        if pending is not None:
            ok_added = [i for i in (added or []) if i.status == ItemStatus.OK]
            if ok_added:
                await self._send(_added_text(ok_added, footer=False))
            await self._ask_pending(pending)
            return

        if order.finalizar_pendente:
            if not order.items:
                order.finalizar_pendente = False
                await self._send(MSG_EMPTY_ORDER)
            else:
                await self._send_summary(order)
            return

        if added:
            await self._send(_added_text(added, footer=True))
        else:
            itens = "\n".join(item_line(i, it) for i, it in enumerate(order.items, 1))
            await self._send(f"Pedido atualizado:\n{itens or '(vazio)'}\n\n{MSG_ADDED_FOOTER}")

    async def _add_item(self, order: Order, novo: ItemExtraido) -> OrderItem:
        match = await self.catalog.match(novo)
        quantidade = Decimal(variant_quantity(Decimal(str(novo.quantidade))))
        item = OrderItem(
            posicao=max((i.posicao for i in order.items), default=0) + 1,
            descricao_original=novo.descricao_original,
            item_normalizado=novo.item_normalizado,
            quantidade=quantidade,
            unidade=novo.unidade,
            confianca=match.confidence,
            opcoes=[],
        )
        product = match.product
        if product is not None and not novo.duvida:
            if _same_unit(novo.unidade, product.unidade_venda):
                self._set_product(item, product)
            else:
                item.status = ItemStatus.PENDENTE_DUVIDA
                item.product = None
                item.opcoes = [str(product.id)]
                item.pergunta = (
                    f'Vendemos "{product.nome_tecnico}" por {product.unidade_venda}. '
                    f"Quantos {product.unidade_venda} você precisa?"
                )
        else:
            item.status = ItemStatus.PENDENTE_DUVIDA
            item.product = None
            options = [
                c.product
                for c in match.candidates[:MAX_OPTIONS]
                if c.score >= self.settings.match_min_option_score
            ]
            item.opcoes = [str(p.id) for p in options]
            if novo.duvida:
                item.pergunta = novo.duvida
            elif options:
                item.pergunta = f'Sobre "{novo.descricao_original}": qual destes você precisa?'
            else:
                item.pergunta = (
                    f'Não encontrei "{novo.descricao_original}" no nosso catálogo. '
                    "Pode descrever de outro jeito (medida, modelo ou marca)?"
                )
        order.items.append(item)
        return item

    def _set_product(self, item: OrderItem, product: Product) -> None:
        item.product = product
        item.product_id = product.id
        item.item_normalizado = product.nome_tecnico
        item.unidade = product.unidade_venda
        item.preco_unitario = product.preco
        item.status = ItemStatus.OK
        item.pergunta = None
        item.opcoes = []

    async def _resolve_option(self, item: OrderItem, numero: int) -> bool:
        options = await self.catalog.get_many(item.opcoes)
        if not 1 <= numero <= len(options):
            return False
        self._set_product(item, options[numero - 1])
        self.conversation.duvidas_sem_solucao = 0
        return True

    # ------------------------------------------------------------- respostas
    async def _ask_pending(self, item: OrderItem) -> None:
        options = await self.catalog.get_many(item.opcoes)
        lines = [item.pergunta or f'Sobre "{item.descricao_original}", pode detalhar?']
        if len(options) > 1:
            for i, product in enumerate(options, 1):
                lines.append(
                    f"{i}) {product.nome_tecnico} — {brl(product.preco)}/{product.unidade_venda}"
                )
            lines.append("Responda com o número da opção ou descreva o item.")
        await self._send("\n".join(lines))

    async def _pending_context(self, item: OrderItem) -> str:
        options = await self.catalog.get_many(item.opcoes)
        lines = [f"Item: {item.descricao_original}", f"Pergunta feita: {item.pergunta}"]
        lines += [f"Opção {i}: {p.nome_tecnico}" for i, p in enumerate(options, 1)]
        return "\n".join(lines)

    async def _send_summary(self, order: Order) -> None:
        lines = ["*Resumo do pedido*"]
        total = Decimal(0)
        for i, item in enumerate(order.items, 1):
            sub = subtotal(item)
            total += sub
            unit_price = brl(item.preco_unitario or Decimal(0))
            lines.append(
                f"{i}. {item.item_normalizado}\n"
                f"   {qty(item.quantidade)} {item.unidade} × {unit_price} = {brl(sub)}"
            )
        lines.append(f"\n*Total: {brl(total)}*")
        lines.append("Frete e pagamento são calculados no checkout.")
        order.total = total
        order.status = OrderStatus.AGUARDANDO_CONFIRMACAO
        order.finalizar_pendente = False
        self.conversation.estado = ConversationState.AGUARDANDO_CONFIRMACAO
        await self._send("\n".join(lines))
        await self._send(
            "Está tudo certo?",
            buttons=[Button(BTN_CONFIRMAR, "Confirmar"), Button(BTN_CORRIGIR, "Corrigir")],
        )

    async def _confirm(self, order: Order) -> None:
        if (
            order.status != OrderStatus.AGUARDANDO_CONFIRMACAO
            or self.conversation.estado != ConversationState.AGUARDANDO_CONFIRMACAO
        ):
            await self._send(MSG_NOTHING_TO_CONFIRM)
            return
        order.status = OrderStatus.CONFIRMADO
        order.confirmado_em = self.s.now()
        try:
            order.cart_url = self.s.cart.build_url(order, self.customer.telefone_e164)
        except CartError as exc:
            log.error("pedido %s sem link de carrinho: %s", order.numero, exc)
            self.outcome.export_order_ids.append(str(order.id))
            await self._handoff()
            return
        order.status = OrderStatus.CARRINHO_ENVIADO
        self.conversation.estado = ConversationState.CONCLUIDO
        self.outcome.export_order_ids.append(str(order.id))
        await self._send(
            f"Pedido nº {order.numero} confirmado! Finalize a compra por este link:\n"
            f"{order.cart_url}\n\nObrigado pela preferência!"
        )

    async def _ask_correction(self, order: Order) -> None:
        self.conversation.estado = ConversationState.COLETANDO
        if order.status == OrderStatus.AGUARDANDO_CONFIRMACAO:
            order.status = OrderStatus.RASCUNHO
        itens = "\n".join(item_line(i, it) for i, it in enumerate(order.items, 1))
        await self._send(MSG_CORRECTION.format(itens=itens or "(pedido vazio)"))

    async def _handoff(self) -> None:
        self.conversation.estado = ConversationState.ATENDIMENTO_HUMANO
        self.conversation.atendente_id = None
        self.conversation.duvidas_sem_solucao = 0
        await self._send(MSG_HANDOFF)

    async def _count_failure_or_handoff(self) -> bool:
        self.conversation.duvidas_sem_solucao += 1
        if self.conversation.duvidas_sem_solucao >= self.settings.max_failed_questions:
            await self._handoff()
            return True
        return False

    async def _send(self, body: str, buttons: list[Button] | None = None) -> None:
        phone = self.customer.telefone_e164
        if phone is None:
            return
        if buttons:
            wa_id = await self.s.messenger.send_buttons(phone, body, buttons)
            kind = MessageType.BOTAO
        else:
            wa_id = await self.s.messenger.send_text(phone, body)
            kind = MessageType.TEXTO
        self.session.add(
            Message(
                conversation_id=self.conversation.id,
                wa_message_id=wa_id,
                direcao=MessageDirection.SAIDA,
                tipo=kind,
                conteudo=body,
                enviado_por=SentBy.BOT,
            )
        )

    # ------------------------------------------------------------- consultas
    async def _get_or_create(
        self, msg: IncomingMessage, now: datetime
    ) -> tuple[Customer, Conversation, bool]:
        customer = await self.session.scalar(
            select(Customer).where(Customer.telefone_e164 == msg.phone)
        )
        is_new = customer is None
        if customer is None:
            customer = Customer(telefone_e164=msg.phone, nome_whatsapp=msg.profile_name)
            self.session.add(customer)
            await self.session.flush()
        elif msg.profile_name:
            customer.nome_whatsapp = msg.profile_name

        conversation = await self.session.scalar(
            select(Conversation).where(Conversation.customer_id == customer.id).with_for_update()
        )
        if conversation is None:
            conversation = Conversation(
                customer_id=customer.id,
                estado=ConversationState.COLETANDO,
                duvidas_sem_solucao=0,
            )
            self.session.add(conversation)
            await self.session.flush()
        return customer, conversation, is_new

    async def _open_order(self) -> Order:
        order = await self.session.scalar(
            select(Order)
            .where(
                Order.conversation_id == self.conversation.id,
                Order.status.in_(OPEN_ORDER_STATUSES),
            )
            .options(selectinload(Order.items).selectinload(OrderItem.product))
            .order_by(Order.created_at.desc())
        )
        if order is None:
            order = Order(
                conversation_id=self.conversation.id,
                customer_id=self.customer.id,
                status=OrderStatus.RASCUNHO,
                finalizar_pendente=False,
                items=[],
            )
            self.session.add(order)
            await self.session.flush()
            await self.session.refresh(order, ["numero"])
        return order

    @staticmethod
    def _first_pending(order: Order) -> OrderItem | None:
        return next((i for i in order.items if i.status == ItemStatus.PENDENTE_DUVIDA), None)


def _message_type(kind: str) -> MessageType:
    return {
        "text": MessageType.TEXTO,
        "audio": MessageType.AUDIO,
        "image": MessageType.IMAGEM,
        "button": MessageType.BOTAO,
    }.get(kind, MessageType.OUTRO)


def _added_text(items: list[OrderItem], footer: bool) -> str:
    lines = ["Anotei:"]
    for item in items:
        if item.status == ItemStatus.OK:
            lines.append(f"- {qty(item.quantidade)} {item.unidade} de {item.item_normalizado}")
    text = "\n".join(lines)
    return f"{text}\n\n{MSG_ADDED_FOOTER}" if footer else text


async def send_reminders(session: AsyncSession, services: Services) -> int:
    """Lembra clientes com pedido em aberto e sem resposta há alguns minutos."""
    now = services.now()
    schedule = await load_schedule(session)
    if not schedule.is_open(now.astimezone(services.settings.tz)):
        return 0
    limit = now - timedelta(minutes=services.settings.reminder_after_minutes)
    conversations = (
        await session.scalars(
            select(Conversation)
            .where(
                Conversation.estado == ConversationState.COLETANDO,
                Conversation.lembrete_enviado_em.is_(None),
                Conversation.ultimo_contato_cliente_em < limit,
            )
            .options(selectinload(Conversation.customer))
        )
    ).all()
    sent = 0
    for conversation in conversations:
        order = await session.scalar(
            select(Order)
            .where(Order.conversation_id == conversation.id, Order.status == OrderStatus.RASCUNHO)
            .options(selectinload(Order.items))
        )
        if order is None or not order.items:
            continue
        if any(i.status == ItemStatus.PENDENTE_DUVIDA for i in order.items):
            continue
        phone = conversation.customer.telefone_e164
        if phone is None:
            continue
        wa_id = await services.messenger.send_text(phone, MSG_REMINDER)
        session.add(
            Message(
                conversation_id=conversation.id,
                wa_message_id=wa_id,
                direcao=MessageDirection.SAIDA,
                tipo=MessageType.TEXTO,
                conteudo=MSG_REMINDER,
                enviado_por=SentBy.BOT,
            )
        )
        conversation.lembrete_enviado_em = now
        sent += 1
    return sent


async def expire_drafts(session: AsyncSession, services: Services) -> int:
    """Cancela rascunhos parados há mais tempo que o limite configurado."""
    limit = services.now() - timedelta(hours=services.settings.draft_expiry_hours)
    orders = (
        await session.scalars(
            select(Order).where(Order.status.in_(OPEN_ORDER_STATUSES), Order.updated_at < limit)
        )
    ).all()
    for order in orders:
        order.status = OrderStatus.CANCELADO
    return len(orders)
