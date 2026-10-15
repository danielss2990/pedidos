from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import (
    Conversation,
    ConversationState,
    ItemStatus,
    Message,
    Order,
    OrderStatus,
)
from app.services.conversation import (
    MSG_HANDOFF,
    MSG_REMINDER,
    ConversationEngine,
    send_reminders,
)
from app.services.extraction import Alteracao
from tests.conftest import PHONE, extracao, incoming, item


async def handle(session, services, msg, *extractions):
    services.extractor.queue.extend(extractions)
    outcome = await ConversationEngine(session, services).handle(msg)
    await session.commit()
    return outcome


async def current_order(session) -> Order:
    session.expire_all()
    return await session.scalar(
        select(Order).options(selectinload(Order.items)).order_by(Order.created_at.desc())
    )


async def conversation_state(session) -> ConversationState:
    session.expire_all()
    return (await session.scalar(select(Conversation))).estado


async def test_fluxo_completo_ate_link_do_carrinho(session, services, seeded):
    wa = services.messenger

    await handle(
        session,
        services,
        incoming(text="10 metros de fio azul de duas metade e duas tomada de dez amperes"),
        extracao(
            itens_novos=[
                item("Cabo Flexível 2,5mm² 750V", 10, "metros", bitola_mm2="2.5", cor="Azul"),
                item("Tomada de Embutir 2P+T 10A", 2, corrente_a="10", cor="Branca"),
            ]
        ),
    )
    assert wa.bodies()[0].startswith("Olá! Sou o assistente")
    assert "10 metros de Cabo Flexível 2,5mm² 750V Azul" in wa.last
    assert "2 unidades de Tomada de Embutir 2P+T 10A Branca" in wa.last

    await handle(session, services, incoming(text="é só isso"), extracao(finalizar_pedido=True))
    resumo, pergunta = wa.sent[-2], wa.sent[-1]
    assert "Total: R$ 38,80" in resumo["body"]  # 10 × 2,10 + 2 × 8,90
    assert pergunta["buttons"] == ["confirmar", "corrigir"]
    assert await conversation_state(session) == ConversationState.AGUARDANDO_CONFIRMACAO

    outcome = await handle(session, services, incoming("button", button_id="confirmar"))
    order = await current_order(session)
    assert order.status == OrderStatus.CARRINHO_ENVIADO
    assert order.total == Decimal("38.80")
    assert order.cart_url.startswith("https://loja.test/cart/40003:10,40009:2?")
    assert f"Pedido nº {order.numero} confirmado" in wa.last
    assert order.cart_url in wa.last
    assert outcome.export_order_ids == [str(order.id)]
    assert await conversation_state(session) == ConversationState.CONCLUIDO


async def test_item_ambiguo_pergunta_e_resolve_pelo_numero(session, services, seeded):
    wa = services.messenger
    await handle(
        session,
        services,
        incoming(text="um disjuntor"),
        extracao(itens_novos=[item("Minidisjuntor DIN")]),
    )
    assert "qual destes" in wa.last
    assert "1) Minidisjuntor DIN 1P 10A Curva C" in wa.last

    # A resposta numérica é resolvida sem chamar o Claude.
    await handle(session, services, incoming(text="2"))
    order = await current_order(session)
    assert order.items[0].status == ItemStatus.OK
    assert order.items[0].item_normalizado == "Minidisjuntor DIN 1P 20A Curva C"
    assert len(services.extractor.inputs) == 1


async def test_finalizar_com_duvida_aberta_mostra_resumo_depois(session, services, seeded):
    wa = services.messenger
    await handle(
        session,
        services,
        incoming(text="um disjuntor e é só isso"),
        extracao(itens_novos=[item("Minidisjuntor DIN")], finalizar_pedido=True),
    )
    assert "qual destes" in wa.last

    await handle(session, services, incoming(text="1"))
    assert wa.sent[-1]["buttons"] == ["confirmar", "corrigir"]
    assert "Total: R$ 14,90" in wa.sent[-2]["body"]


async def test_duvida_do_modelo_vira_pergunta(session, services, seeded):
    await handle(
        session,
        services,
        incoming(text="20 metros de fio"),
        extracao(
            itens_novos=[
                item("Cabo Flexível", 20, "metros", duvida="Qual a bitola e a cor do fio?")
            ]
        ),
    )
    assert services.messenger.last.startswith("Qual a bitola e a cor do fio?")
    order = await current_order(session)
    assert order.items[0].status == ItemStatus.PENDENTE_DUVIDA


async def test_item_inexistente_pede_descricao(session, services, seeded):
    await handle(
        session,
        services,
        incoming(text="cabo pp"),
        extracao(itens_novos=[item("Cabo PP 3x2,5mm²")]),
    )
    assert "Não encontrei" in services.messenger.last
    assert "1)" not in services.messenger.last


async def test_corrigir_e_alterar_quantidade(session, services, seeded):
    wa = services.messenger
    await handle(
        session,
        services,
        incoming(text="2 tomadas de 10 e é só"),
        extracao(
            itens_novos=[item("Tomada de Embutir 2P+T 10A", 2, corrente_a="10")],
            finalizar_pedido=True,
        ),
    )
    await handle(session, services, incoming("button", button_id="corrigir"))
    assert "O que deseja mudar?" in wa.last
    assert await conversation_state(session) == ConversationState.COLETANDO

    await handle(
        session,
        services,
        incoming(text="são 5 tomadas, pode fechar"),
        extracao(
            alteracoes=[Alteracao(numero_item=1, nova_quantidade=5, remover=False)],
            finalizar_pedido=True,
        ),
    )
    assert "Total: R$ 44,50" in wa.sent[-2]["body"]


async def test_metragem_fracionada_arredonda_para_cima(session, services, seeded):
    await handle(
        session,
        services,
        incoming(text="2,5 metros de fio 2,5 preto"),
        extracao(
            itens_novos=[
                item("Cabo Flexível 2,5mm² 750V", 2.5, "metros", bitola_mm2="2.5", cor="Preto")
            ]
        ),
    )
    order = await current_order(session)
    assert order.items[0].quantidade == Decimal("3")


async def test_unidade_diferente_do_catalogo_pergunta(session, services, seeded):
    await handle(
        session,
        services,
        incoming(text="um rolo de fio 6"),
        extracao(itens_novos=[item("Cabo Flexível 6mm² 750V", 1, "rolos", bitola_mm2="6")]),
    )
    assert "por metros" in services.messenger.last


async def test_audio_e_transcrito_antes_da_extracao(session, services, seeded):
    services.transcriber.text = "quero uma fita isolante"
    await handle(
        session,
        services,
        incoming("audio", media_id="m1", media_mime="audio/ogg; codecs=opus"),
        extracao(itens_novos=[item("Fita Isolante")]),
    )
    sent = services.extractor.inputs[0]
    assert sent.tipo == "audio" and sent.texto == "quero uma fita isolante"
    msg = await session.scalar(select(Message).where(Message.wa_message_id.like("wamid.in.%")))
    assert msg.transcricao == "quero uma fita isolante"


async def test_foto_vai_como_imagem_para_o_claude(session, services, seeded):
    services.messenger.media["img1"] = (b"\xff\xd8jpeg", "image/jpeg")
    await handle(
        session,
        services,
        incoming("image", media_id="img1", media_mime="image/jpeg"),
        extracao(imagem_ilegivel=True),
    )
    sent = services.extractor.inputs[0]
    assert sent.tipo == "imagem" and sent.imagem == b"\xff\xd8jpeg"
    assert "foto" in services.messenger.last


async def test_fora_do_horario_avisa_uma_vez(session, services, seeded, clock):
    clock.now = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)  # domingo
    await handle(session, services, incoming(text="oi"))
    await handle(session, services, incoming(text="alguém?"))
    avisos = [b for b in services.messenger.bodies() if "fora do horário" in b]
    assert len(avisos) == 1
    assert services.extractor.inputs == []


async def test_pedido_de_atendente_silencia_o_bot(session, services, seeded):
    await handle(
        session,
        services,
        incoming(text="quero falar com alguém"),
        extracao(falar_com_atendente=True),
    )
    assert services.messenger.last == MSG_HANDOFF
    assert await conversation_state(session) == ConversationState.ATENDIMENTO_HUMANO

    count = len(services.messenger.sent)
    await handle(session, services, incoming(text="oi?"))
    assert len(services.messenger.sent) == count
    assert services.extractor.inputs[-1].texto == "quero falar com alguém"


async def test_mensagem_duplicada_e_ignorada(session, services, seeded):
    msg = incoming(text="1 fita isolante")
    await handle(session, services, msg, extracao(itens_novos=[item("Fita Isolante")]))
    count = len(services.messenger.sent)
    await handle(session, services, msg)
    assert len(services.messenger.sent) == count


async def test_lembrete_apos_inatividade(session, services, seeded, clock):
    await handle(
        session,
        services,
        incoming(text="1 fita isolante"),
        extracao(itens_novos=[item("Fita Isolante")]),
    )
    clock.now = clock.now + timedelta(minutes=11)
    assert await send_reminders(session, services) == 1
    await session.commit()
    assert services.messenger.last == MSG_REMINDER
    assert await send_reminders(session, services) == 0


async def test_confirmar_sem_resumo_nao_gera_link(session, services, seeded):
    await handle(session, services, incoming("button", button_id="confirmar"))
    assert "Não há pedido aguardando confirmação" in services.messenger.last
    assert services.messenger.sent[-1]["phone"] == PHONE
    order = await current_order(session)
    assert order.cart_url is None


async def test_mensagens_do_mesmo_turno_ficam_em_ordem(session, services, seeded):
    await handle(
        session,
        services,
        incoming(text="1 fita isolante"),
        extracao(itens_novos=[item("Fita Isolante")]),
    )
    session.expire_all()
    rows = (await session.scalars(select(Message).order_by(Message.created_at))).all()
    autores = [m.enviado_por.value for m in rows]
    assert autores == ["cliente", "bot", "bot"]  # mensagem, boas-vindas, "Anotei"
    assert len({m.created_at for m in rows}) == len(rows)
