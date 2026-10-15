"""Worker ARQ: processa mensagens, exporta pedidos e roda as rotinas agendadas.

Execute com: arq app.worker.WorkerSettings
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import anthropic
import httpx
import openai
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal
from app.models import Order, OrderItem, SlangTerm
from app.services import catalog
from app.services.conversation import ConversationEngine, Services, expire_drafts, send_reminders
from app.services.extraction import ClaudeExtractor
from app.services.media import LocalMediaStore
from app.services.privacy import apply_retention
from app.services.sheets import GoogleSheets, SheetsError
from app.services.transcription import WhisperTranscriber
from app.services.whatsapp import IncomingMessage, build_messenger

log = logging.getLogger(__name__)
PANEL_CHANNEL = "painel:eventos"


def _now() -> datetime:
    return datetime.now(UTC)


async def startup(ctx: dict[str, Any]) -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    http = httpx.AsyncClient(timeout=60)
    async with SessionLocal() as session:
        slang = {t.termo: t.significado for t in (await session.scalars(select(SlangTerm))).all()}
    ctx["http"] = http
    ctx["sheets"] = GoogleSheets(settings)
    ctx["services"] = Services(
        settings=settings,
        messenger=build_messenger(settings, http),
        extractor=ClaudeExtractor(settings, anthropic.AsyncAnthropic(), slang),
        transcriber=WhisperTranscriber(settings, openai.AsyncOpenAI()),
        media=LocalMediaStore(settings.media_dir),
        now=_now,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["http"].aclose()


async def process_incoming(ctx: dict[str, Any], data: dict[str, Any]) -> None:
    msg = IncomingMessage.from_job(data)
    redis = ctx["redis"]
    # Uma mensagem por vez por cliente, para áudio + texto em sequência não se atropelarem.
    async with redis.lock(f"lock:conversa:{msg.phone}", timeout=180, blocking_timeout=170):
        async with SessionLocal() as session:
            outcome = await ConversationEngine(session, ctx["services"]).handle(msg)
            await session.commit()
    for order_id in outcome.export_order_ids:
        await redis.enqueue_job("export_order", order_id, _job_id=f"export:{order_id}")
    if outcome.notify_panel:
        await redis.publish(PANEL_CHANNEL, json.dumps({"tipo": "mensagem", "telefone": msg.phone}))


async def export_order(ctx: dict[str, Any], order_id: str) -> None:
    settings = ctx["services"].settings
    async with SessionLocal() as session:
        order = await session.scalar(
            select(Order)
            .where(Order.id == uuid.UUID(order_id))
            .options(
                selectinload(Order.items).selectinload(OrderItem.product),
                selectinload(Order.customer),
            )
        )
        if order is None or order.exportado_planilha_em is not None:
            return
        try:
            await ctx["sheets"].export_order(order, settings)
        except SheetsError as exc:
            log.warning("pedido %s não exportado: %s", order.numero, exc)
            return
        order.exportado_planilha_em = _now()
        await session.commit()


async def sync_catalog(ctx: dict[str, Any]) -> dict[str, int]:
    try:
        rows = await ctx["sheets"].read_catalog()
    except SheetsError as exc:
        log.info("sincronização do catálogo ignorada: %s", exc)
        return {}
    async with SessionLocal() as session:
        stats = await catalog.import_rows(session, rows)
        await session.commit()
    log.info("catálogo sincronizado: %s", stats)
    return stats


async def reminders(ctx: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        await send_reminders(session, ctx["services"])
        await expire_drafts(session, ctx["services"])
        await session.commit()


async def retention(ctx: dict[str, Any]) -> None:
    services: Services = ctx["services"]
    async with SessionLocal() as session:
        stats = await apply_retention(
            session, services.media, _now(), services.settings.data_retention_days
        )
        await session.commit()
    log.info("retenção LGPD aplicada: %s", stats)


class WorkerSettings:
    functions = [process_incoming, export_order, sync_catalog]
    cron_jobs = [
        cron(reminders, second=0),
        cron(sync_catalog, minute={0, 15, 30, 45}, second=30),
        cron(retention, hour=6, minute=0, second=0),  # 03:00 em Brasília (UTC-3)
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    job_timeout = 300
