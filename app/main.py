import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import auth, conversations, orders, products, settings, webhooks
from app.config import get_settings
from app.db import SessionLocal
from app.services.whatsapp import WhatsAppClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = get_settings()
    async with httpx.AsyncClient(timeout=30) as http:
        app.state.messenger = WhatsAppClient(config, http)
        app.state.queue = await create_pool(RedisSettings.from_dsn(config.redis_url))
        try:
            yield
        finally:
            await app.state.queue.aclose()


def create_app(use_lifespan: bool = True) -> FastAPI:
    config = get_settings()
    app = FastAPI(
        title="Central de Pedidos Elétricos",
        version="0.1.0",
        lifespan=lifespan if use_lifespan else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (webhooks, auth, conversations, orders, products, settings):
        app.include_router(module.router)

    @app.get("/health", tags=["monitoramento"])
    async def health() -> dict[str, str]:
        async with SessionLocal() as session:
            await session.execute(text("select 1"))
        return {"status": "ok"}

    return app


app = create_app()
