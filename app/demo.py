"""Dados de demonstração para testar o painel sem WhatsApp. Não use em produção."""

import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
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
    Role,
    SentBy,
    User,
)
from app.security import hash_password
from app.services import catalog

CATALOG = Path(__file__).parent.parent / "data" / "catalogo_exemplo.csv"
DEMO_PASSWORD = "demo12345"


async def seed_demo(session: AsyncSession) -> list[str]:
    created: list[str] = []
    for nome, email, perfil in [
        ("Admin Demo", "admin@demo.com", Role.ADMIN),
        ("Sueli Supervisora", "sueli@demo.com", Role.SUPERVISOR),
        ("Ana Atendente", "ana@demo.com", Role.ATENDENTE),
    ]:
        if not await session.scalar(select(User.id).where(User.email == email)):
            session.add(
                User(
                    nome=nome,
                    email=email,
                    senha_hash=hash_password(DEMO_PASSWORD),
                    perfil=perfil,
                    ativo=True,
                )
            )
            created.append(email)

    with CATALOG.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for i, row in enumerate(rows):
        # Deixa dois produtos sem variante para mostrar o aviso no painel.
        row["shopify_variant_id"] = "" if i >= len(rows) - 2 else str(44_000_000 + i)
    await catalog.import_rows(session, rows)
    await session.flush()
    products = {p.sku: p for p in (await session.scalars(select(Product))).all()}

    now = datetime.now(UTC)

    async def conversation(
        phone: str, nome: str, estado: ConversationState, minutes_ago: int
    ) -> Conversation:
        customer = Customer(telefone_e164=phone, nome_whatsapp=nome, consentimento_em=now)
        session.add(customer)
        await session.flush()
        conv = Conversation(
            customer_id=customer.id,
            estado=estado,
            duvidas_sem_solucao=0,
            ultimo_contato_cliente_em=now - timedelta(minutes=minutes_ago),
        )
        session.add(conv)
        await session.flush()
        return conv

    def message(conv, minutes_ago, by, text, tipo=MessageType.TEXTO, transcricao=None):
        session.add(
            Message(
                conversation_id=conv.id,
                direcao=MessageDirection.ENTRADA
                if by == SentBy.CLIENTE
                else MessageDirection.SAIDA,
                tipo=tipo,
                conteudo=text,
                transcricao=transcricao,
                enviado_por=by,
                created_at=now - timedelta(minutes=minutes_ago),
            )
        )

    def order(conv, status, items, total=None, cart=None):
        o = Order(
            conversation_id=conv.id,
            customer_id=conv.customer_id,
            status=status,
            total=total,
            cart_url=cart,
            finalizar_pendente=False,
            confirmado_em=now
            if status in (OrderStatus.CARRINHO_ENVIADO, OrderStatus.PAGO)
            else None,
            items=[],
        )
        for pos, (sku, qtd, original, pendente) in enumerate(items, 1):
            p = products.get(sku) if sku else None
            o.items.append(
                OrderItem(
                    posicao=pos,
                    product=p,
                    descricao_original=original,
                    item_normalizado=p.nome_tecnico if p else original,
                    quantidade=Decimal(qtd),
                    unidade=p.unidade_venda if p else "unidades",
                    preco_unitario=p.preco if p else None,
                    status=ItemStatus.PENDENTE_DUVIDA if pendente else ItemStatus.OK,
                    pergunta=pendente,
                    opcoes=[],
                )
            )
        session.add(o)

    # 1. Cliente pediu atendente (na fila).
    c1 = await conversation(
        "5511987654321", "João Eletricista", ConversationState.ATENDIMENTO_HUMANO, 3
    )
    message(
        c1,
        9,
        SentBy.CLIENTE,
        None,
        MessageType.AUDIO,
        "Bom dia, preciso de 50 metros de fio de dois e meio azul e 10 tomadas de 20",
    )
    message(
        c1,
        8,
        SentBy.BOT,
        "Anotei:\n- 50 metros de Cabo Flexível 2,5mm² 750V Azul\n"
        "- 10 unidades de Tomada de Embutir 2P+T 20A Branca\n\nAlgo mais? Quando terminar, "
        'é só dizer "é só isso".',
    )
    message(c1, 3, SentBy.CLIENTE, "Vocês fazem entrega em Guarulhos? Quero falar com alguém")
    message(
        c1,
        2,
        SentBy.BOT,
        "Vou chamar um atendente. Já já alguém da nossa equipe responde por aqui.",
    )
    order(
        c1,
        OrderStatus.RASCUNHO,
        [
            ("CAB-FLX-25-AZ", "50", "fio de dois e meio azul", None),
            ("TOM-2PT-20-BR", "10", "tomadas de 20", None),
        ],
    )

    # 2. Bot com dúvida aberta.
    c2 = await conversation("5521976543210", "Carla Reformas", ConversationState.COLETANDO, 12)
    message(c2, 13, SentBy.CLIENTE, "Oi! Me vê 3 disjuntor e 2 rolos de conduíte 3/4")
    message(
        c2,
        12,
        SentBy.BOT,
        'Sobre "3 disjuntor": qual destes você precisa?\n'
        "1) Minidisjuntor DIN 1P 10A Curva C — R$ 14,90/unidades\n"
        "2) Minidisjuntor DIN 1P 20A Curva C — R$ 14,90/unidades\n"
        "3) Minidisjuntor DIN 2P 32A Curva C — R$ 42,00/unidades\n"
        "Responda com o número da opção ou descreva o item.",
    )
    order(
        c2,
        OrderStatus.RASCUNHO,
        [
            ("ELE-COR-20", "2", "2 rolos de conduíte 3/4", None),
            (None, "3", "3 disjuntor", 'Sobre "3 disjuntor": qual destes você precisa?'),
        ],
    )

    # 3. Pedido concluído com link de carrinho.
    c3 = await conversation("5531965432109", "Pedro Instalações", ConversationState.CONCLUIDO, 45)
    message(c3, 50, SentBy.CLIENTE, None, MessageType.IMAGEM)
    message(
        c3,
        49,
        SentBy.BOT,
        "Anotei:\n- 100 metros de Cabo Flexível 1,5mm² 750V Preto\n"
        "- 4 unidades de Interruptor Simples 10A Branco",
    )
    message(c3, 47, SentBy.CLIENTE, "é só isso")
    message(
        c3,
        46,
        SentBy.BOT,
        "*Resumo do pedido*\n1. Cabo Flexível 1,5mm² 750V Preto\n"
        "   100 metros × R$ 1,45 = R$ 145,00\n2. Interruptor Simples 10A Branco\n"
        "   4 unidades × R$ 7,50 = R$ 30,00\n\n*Total: R$ 175,00*",
    )
    message(c3, 45, SentBy.CLIENTE, "Confirmar", MessageType.BOTAO)
    message(
        c3,
        44,
        SentBy.BOT,
        "Pedido confirmado! Finalize a compra por este link:\n"
        "https://loja.example/cart/44000001:100,44000010:4",
    )
    order(
        c3,
        OrderStatus.CARRINHO_ENVIADO,
        [
            ("CAB-FLX-15-PT", "100", "100 metros de fio 1,5 preto", None),
            ("INT-SIM-10-BR", "4", "4 interruptores", None),
        ],
        Decimal("175.00"),
        "https://loja.example/cart/44000001:100,44000010:4",
    )

    # 4. Pedido pago, de ontem.
    c4 = await conversation("5541954321098", "Marcos", ConversationState.CONCLUIDO, 60 * 26)
    message(c4, 60 * 26, SentBy.CLIENTE, "2 fitas isolantes e 1 passa-fio, é só isso")
    order(
        c4,
        OrderStatus.PAGO,
        [
            ("FIT-ISO-20", "2", "2 fitas isolantes", None),
            ("FIT-PAS-20", "1", "1 passa-fio", None),
        ],
        Decimal("59.70"),
        "https://loja.example/cart/44000016:2,44000017:1",
    )

    await session.flush()
    return created
