import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5432/pedidos_test")
os.environ.setdefault("WHATSAPP_APP_SECRET", "segredo-meta")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "token-verificacao")
os.environ.setdefault("SHOPIFY_WEBHOOK_SECRET", "segredo-shopify")
os.environ.setdefault("SHOPIFY_STORE_DOMAIN", "loja.test")
os.environ.setdefault("SECRET_KEY", "chave-de-teste-com-tamanho-suficiente-para-hs256")

import csv  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import catalog  # noqa: E402
from app.services.cart import ShopifyCartBuilder  # noqa: E402
from app.services.conversation import Services  # noqa: E402
from app.services.extraction import (  # noqa: E402
    Atributo,
    Extracao,
    ExtractionInput,
    ExtractionResult,
    ItemExtraido,
)
from app.services.whatsapp import Button, IncomingMessage  # noqa: E402

CATALOG_CSV = Path(__file__).parent.parent / "data" / "catalogo_exemplo.csv"
# Quarta-feira, 14h em Brasília: dentro do horário comercial padrão.
OPEN_NOW = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
PHONE = "5511999998888"


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_tables() -> None:
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


@pytest.fixture
async def seeded(session: AsyncSession) -> None:
    with CATALOG_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for i, row in enumerate(rows, 1):
        row["shopify_variant_id"] = str(40000 + i)
    await catalog.import_rows(session, rows)
    await session.commit()


@dataclass
class FakeMessenger:
    sent: list[dict[str, Any]] = field(default_factory=list)
    media: dict[str, tuple[bytes, str]] = field(default_factory=dict)

    async def send_text(self, phone: str, body: str) -> str:
        self.sent.append({"phone": phone, "body": body, "buttons": None})
        return f"wamid.out.{len(self.sent)}"

    async def send_buttons(self, phone: str, body: str, buttons: list[Button]) -> str:
        self.sent.append({"phone": phone, "body": body, "buttons": [b.id for b in buttons]})
        return f"wamid.out.{len(self.sent)}"

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        return self.media.get(media_id, (b"bytes", "image/jpeg"))

    def bodies(self) -> list[str]:
        return [m["body"] for m in self.sent]

    @property
    def last(self) -> str:
        return self.sent[-1]["body"]


@dataclass
class FakeExtractor:
    """Devolve as extrações enfileiradas, na ordem, e guarda as entradas recebidas."""

    queue: list[Extracao] = field(default_factory=list)
    inputs: list[ExtractionInput] = field(default_factory=list)

    async def extract(self, data: ExtractionInput) -> ExtractionResult:
        self.inputs.append(data)
        extracao = self.queue.pop(0)
        return ExtractionResult(extracao=extracao, modelo="fake", raw=extracao.model_dump())


@dataclass
class FakeTranscriber:
    text: str = ""

    async def transcribe(self, audio: bytes, mime: str) -> str:
        return self.text


class FakeMedia:
    def save(self, conversation_id, data: bytes, mime: str) -> str:
        return f"{conversation_id}/arquivo"

    def delete_older_than(self, days: int) -> int:
        return 0


@dataclass
class Clock:
    now: datetime = OPEN_NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def services(clock: Clock) -> Services:
    return Services(
        settings=get_settings(),
        messenger=FakeMessenger(),
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        cart=ShopifyCartBuilder("loja.test"),
        media=FakeMedia(),
        now=clock,
    )


def item(
    nome: str,
    quantidade: float = 1,
    unidade: str = "unidades",
    duvida: str | None = None,
    responde: bool = False,
    original: str | None = None,
    **attrs: str,
) -> ItemExtraido:
    return ItemExtraido(
        descricao_original=original or nome,
        item_normalizado=nome,
        categoria=None,
        atributos=[Atributo(nome=k, valor=v) for k, v in attrs.items()],
        quantidade=quantidade,
        unidade=unidade,
        duvida=duvida,
        responde_duvida_pendente=responde,
    )


def extracao(**overrides: Any) -> Extracao:
    data: dict[str, Any] = {
        "itens_novos": [],
        "alteracoes": [],
        "opcao_escolhida": None,
        "finalizar_pedido": False,
        "confirmar_pedido": False,
        "corrigir_pedido": False,
        "falar_com_atendente": False,
        "imagem_ilegivel": False,
        "resposta_livre": None,
    }
    data.update(overrides)
    return Extracao(**data)


_counter = {"n": 0}


def incoming(kind: str = "text", **fields: Any) -> IncomingMessage:
    _counter["n"] += 1
    return IncomingMessage(
        wa_message_id=f"wamid.in.{_counter['n']}",
        phone=fields.pop("phone", PHONE),
        profile_name=fields.pop("profile_name", "Maria"),
        timestamp=0,
        kind=kind,
        **fields,
    )
