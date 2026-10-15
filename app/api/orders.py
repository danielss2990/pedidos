import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.deps import CurrentUser, MessengerDep, SessionDep
from app.models import ACTIVE_ORDER_STATUSES, AuditLog, Conversation, Order, OrderStatus, User
from app.schemas import FreteIn, OrderActionOut, OrderOut, PagamentoIn, Page, StatusIn
from app.services.fulfillment import FulfillmentError, TeamActions

router = APIRouter(prefix="/api/v1/orders", tags=["pedidos"])


def _with_details(query):
    return query.options(selectinload(Order.items), selectinload(Order.customer))


@router.get("", response_model=Page[OrderOut])
async def list_orders(
    _: CurrentUser,
    session: SessionDep,
    status_: Annotated[OrderStatus | None, Query(alias="status")] = None,
    em_andamento: bool = False,
    conversation_id: uuid.UUID | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> Page[OrderOut]:
    query = select(Order)
    if status_ is not None:
        query = query.where(Order.status == status_)
    if em_andamento:
        query = query.where(Order.status.in_(ACTIVE_ORDER_STATUSES))
    if conversation_id is not None:
        query = query.where(Order.conversation_id == conversation_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    ordering = Order.confirmado_em.asc().nulls_last() if em_andamento else Order.created_at.desc()
    rows = await session.scalars(
        _with_details(query).order_by(ordering).limit(limit).offset(offset)
    )
    return Page(items=[OrderOut.model_validate(o) for o in rows], total=total)


async def _load(session: SessionDep, order_id: uuid.UUID) -> Order:
    order = await session.scalar(_with_details(select(Order).where(Order.id == order_id)))
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido não encontrado")
    return order


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, _: CurrentUser, session: SessionDep) -> Order:
    return await _load(session, order_id)


async def _act(session, messenger, user: User, order_id: uuid.UUID, acao: str, diff, action):
    order = await _load(session, order_id)
    conversation = await session.scalar(
        select(Conversation)
        .where(Conversation.id == order.conversation_id)
        .options(selectinload(Conversation.customer))
    )
    team = TeamActions(session, messenger, get_settings(), user.id, datetime.now(UTC))
    try:
        sent = await action(team, order, conversation)
    except FulfillmentError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    session.add(
        AuditLog(user_id=user.id, acao=acao, entidade="order", entidade_id=str(order.id), diff=diff)
    )
    await session.commit()
    return OrderActionOut(
        order=OrderOut.model_validate(await _load(session, order_id)),
        mensagem_enviada=sent,
        aviso=team.aviso,
    )


@router.post("/{order_id}/frete", response_model=OrderActionOut)
async def set_frete(
    order_id: uuid.UUID,
    data: FreteIn,
    user: CurrentUser,
    session: SessionDep,
    messenger: MessengerDep,
) -> OrderActionOut:
    """Registra o frete e envia ao cliente o total com frete (e a chave Pix, se for o caso)."""
    return await _act(
        session,
        messenger,
        user,
        order_id,
        "frete",
        {"valor": str(data.valor)},
        lambda team, order, conv: team.set_frete(order, conv, data.valor),
    )


@router.post("/{order_id}/pagamento", response_model=OrderActionOut)
async def set_pagamento(
    order_id: uuid.UUID,
    data: PagamentoIn,
    user: CurrentUser,
    session: SessionDep,
    messenger: MessengerDep,
) -> OrderActionOut:
    """Marca ou desmarca o pedido como pago (não envia mensagem ao cliente)."""

    async def action(team, order, conv):
        team.set_paid(order, data.pago)
        return False

    return await _act(session, messenger, user, order_id, "pagamento", {"pago": data.pago}, action)


@router.post("/{order_id}/status", response_model=OrderActionOut)
async def set_status(
    order_id: uuid.UUID,
    data: StatusIn,
    user: CurrentUser,
    session: SessionDep,
    messenger: MessengerDep,
) -> OrderActionOut:
    """Avança o pedido (em separação, pronto, concluído ou cancelado) e avisa o cliente."""
    return await _act(
        session,
        messenger,
        user,
        order_id,
        "status",
        {"status": data.status.value},
        lambda team, order, conv: team.change_status(order, conv, data.status),
    )
