import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.config import get_settings
from app.deps import QueueDep
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
