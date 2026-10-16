"""Worker ARQ: processa as mensagens do WhatsApp e roda as rotinas agendadas.

Execute com: arq app.worker.WorkerSettings
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import SlangTerm
from app.services.conversation import ConversationEngine, Services, expire_drafts, send_reminders
from app.services.extraction import OllamaExtractor
from app.services.media import LocalMediaStore
from app.services.privacy import apply_retention
from app.services.transcription import LocalWhisperTranscriber
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
    ctx["services"] = Services(
        settings=settings,
        messenger=build_messenger(settings, http),
        extractor=OllamaExtractor(settings, http, slang),
        transcriber=LocalWhisperTranscriber(settings),
        media=LocalMediaStore(settings.media_dir),
        now=_now,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["http"].aclose()


async def process_incoming(ctx: dict[str, Any], data: dict[str, Any]) -> None:
    msg = IncomingMessage.from_job(data)
    redis = ctx["redis"]
    # Uma mensagem por vez por cliente, para áudio + texto em sequência não se atropelarem.
    settings = ctx["services"].settings
    async with redis.lock(
        f"lock:conversa:{msg.phone}",
        timeout=settings.llm_timeout_segundos + 120,
        blocking_timeout=settings.llm_timeout_segundos + 60,
    ):
        async with SessionLocal() as session:
            outcome = await ConversationEngine(session, ctx["services"]).handle(msg)
            await session.commit()
    if outcome.notify_panel:
        await redis.publish(PANEL_CHANNEL, json.dumps({"tipo": "mensagem", "telefone": msg.phone}))


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
    functions = [process_incoming]
    cron_jobs = [
        cron(reminders, second=0),
        cron(retention, hour=6, minute=0, second=0),  # 03:00 em Brasília (UTC-3)
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    # Em CPU, ler uma foto com o modelo de visão pode levar alguns minutos.
    job_timeout = get_settings().llm_timeout_segundos + 180
