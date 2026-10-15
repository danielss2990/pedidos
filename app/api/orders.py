import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, SessionDep
from app.models import Order, OrderStatus
from app.schemas import OrderOut, Page

router = APIRouter(prefix="/api/v1/orders", tags=["pedidos"])


def _with_details(query):
    return query.options(selectinload(Order.items), selectinload(Order.customer))


@router.get("", response_model=Page[OrderOut])
async def list_orders(
    _: CurrentUser,
    session: SessionDep,
    status_: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> Page[OrderOut]:
    query = select(Order)
    if status_ is not None:
        query = query.where(Order.status == status_)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(
        _with_details(query).order_by(Order.created_at.desc()).limit(limit).offset(offset)
    )
    return Page(items=[OrderOut.model_validate(o) for o in rows], total=total)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, _: CurrentUser, session: SessionDep) -> Order:
    order = await session.scalar(_with_details(select(Order).where(Order.id == order_id)))
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido não encontrado")
    return order
