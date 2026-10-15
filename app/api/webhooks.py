import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import QueueDep, SessionDep
from app.models import Order, OrderStatus
from app.security import verify_shopify_hmac
from app.services.whatsapp import parse_webhook, verify_signature

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
async def whatsapp_verify(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
) -> Response:
    settings = get_settings()
    if (
        mode == "subscribe"
        and settings.whatsapp_verify_token
        and token == settings.whatsapp_verify_token
    ):
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Token de verificação inválido")


@router.post("/whatsapp")
async def whatsapp_receive(request: Request, queue: QueueDep) -> dict[str, int]:
    raw = await request.body()
    settings = get_settings()
    if not verify_signature(
        settings.whatsapp_app_secret, raw, request.headers.get("X-Hub-Signature-256")
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Assinatura inválida")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "JSON inválido") from exc

    messages = parse_webhook(payload)
    for msg in messages:
        # O job_id deduplica reenvios da Meta enquanto o job ainda está na fila.
        await queue.enqueue_job("process_incoming", msg.to_job(), _job_id=f"wa:{msg.wa_message_id}")
    return {"recebidas": len(messages)}


@router.post("/shopify/orders")
async def shopify_order(request: Request, session: SessionDep) -> dict[str, str]:
    raw = await request.body()
    settings = get_settings()
    if not verify_shopify_hmac(
        settings.shopify_webhook_secret, raw, request.headers.get("X-Shopify-Hmac-Sha256")
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Assinatura inválida")
    payload = json.loads(raw)
    attributes = {a.get("name"): a.get("value") for a in payload.get("note_attributes", [])}
    numero = attributes.get("pedido_whatsapp")
    if not numero or not str(numero).isdigit():
        return {"resultado": "ignorado"}

    order = await session.scalar(select(Order).where(Order.numero == int(numero)))
    if order is None:
        log.warning(
            "pedido Shopify %s aponta para pedido inexistente %s", payload.get("id"), numero
        )
        return {"resultado": "nao_encontrado"}
    order.shopify_order_id = str(payload.get("id"))
    if payload.get("financial_status") == "paid":
        order.status = OrderStatus.PAGO
    await session.commit()
    return {"resultado": "ok"}
