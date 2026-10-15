"""Retenção de dados (LGPD): apaga mídias e anonimiza clientes inativos."""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Customer, Message
from app.services.media import MediaStore


async def apply_retention(
    session: AsyncSession, media: MediaStore, now: datetime, days: int
) -> dict[str, int]:
    limit = now - timedelta(days=days)
    removed_files = media.delete_older_than(days)

    await session.execute(update(Message).where(Message.created_at < limit).values(media_path=None))
    stale = (
        await session.scalars(
            select(Customer)
            .join(Conversation, Conversation.customer_id == Customer.id)
            .where(
                Customer.anonimizado_em.is_(None),
                Conversation.ultimo_contato_cliente_em < limit,
            )
        )
    ).all()
    for customer in stale:
        await anonymize_customer(session, customer, now)
    return {"arquivos_removidos": removed_files, "clientes_anonimizados": len(stale)}


async def anonymize_customer(session: AsyncSession, customer: Customer, now: datetime) -> None:
    """Remove dados pessoais; pedidos ficam para métricas, sem identificar a pessoa."""
    customer.telefone_e164 = None
    customer.nome = None
    customer.nome_whatsapp = None
    customer.anonimizado_em = now
    conversation_ids = select(Conversation.id).where(Conversation.customer_id == customer.id)
    await session.execute(
        update(Message)
        .where(Message.conversation_id.in_(conversation_ids))
        .values(conteudo=None, transcricao=None, media_path=None)
    )
