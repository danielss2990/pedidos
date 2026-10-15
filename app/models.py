import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    # Traz created_at/updated_at gerados pelo banco via RETURNING, evitando
    # carregamento implícito (que falha em código assíncrono) depois do commit.
    __mapper_args__ = {"eager_defaults": True}


def _enum(cls: type[enum.Enum]) -> Enum:
    return Enum(cls, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e])


class TimestampMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Role(enum.StrEnum):
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    ATENDENTE = "atendente"


class ConversationState(enum.StrEnum):
    COLETANDO = "coletando"
    AGUARDANDO_CONFIRMACAO = "aguardando_confirmacao"
    ATENDIMENTO_HUMANO = "atendimento_humano"
    CONCLUIDO = "concluido"


class MessageDirection(enum.StrEnum):
    ENTRADA = "entrada"
    SAIDA = "saida"


class MessageType(enum.StrEnum):
    TEXTO = "texto"
    AUDIO = "audio"
    IMAGEM = "imagem"
    BOTAO = "botao"
    OUTRO = "outro"


class SentBy(enum.StrEnum):
    CLIENTE = "cliente"
    BOT = "bot"
    ATENDENTE = "atendente"


class OrderStatus(enum.StrEnum):
    RASCUNHO = "rascunho"
    AGUARDANDO_CONFIRMACAO = "aguardando_confirmacao"
    CONFIRMADO = "confirmado"
    CARRINHO_ENVIADO = "carrinho_enviado"
    PAGO = "pago"
    CANCELADO = "cancelado"


OPEN_ORDER_STATUSES = (OrderStatus.RASCUNHO, OrderStatus.AGUARDANDO_CONFIRMACAO)


class ItemStatus(enum.StrEnum):
    OK = "ok"
    PENDENTE_DUVIDA = "pendente_duvida"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    perfil: Mapped[Role] = mapped_column(_enum(Role))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    telefone_e164: Mapped[str | None] = mapped_column(String(20), unique=True)
    nome_whatsapp: Mapped[str | None] = mapped_column(String(120))
    nome: Mapped[str | None] = mapped_column(String(120))
    consentimento_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anonimizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(64), unique=True)
    nome_tecnico: Mapped[str] = mapped_column(String(255))
    categoria: Mapped[str | None] = mapped_column(String(80))
    atributos: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    unidade_venda: Mapped[str] = mapped_column(String(20), default="unidades")
    preco: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    shopify_variant_id: Mapped[str | None] = mapped_column(String(64))
    # Texto normalizado (minúsculo, sem acento) com nome, categoria e sinônimos,
    # usado na busca por similaridade (pg_trgm).
    search_text: Mapped[str] = mapped_column(Text, default="")

    synonyms: Mapped[list["ProductSynonym"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "ix_products_search_text_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )


class ProductSynonym(TimestampMixin, Base):
    __tablename__ = "product_synonyms"

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    termo: Mapped[str] = mapped_column(String(120))
    origem: Mapped[str] = mapped_column(String(20), default="planilha")

    product: Mapped[Product] = relationship(back_populates="synonyms")


class SlangTerm(TimestampMixin, Base):
    __tablename__ = "slang_dictionary"

    termo: Mapped[str] = mapped_column(String(120), unique=True)
    significado: Mapped[str] = mapped_column(String(255))
    categoria: Mapped[str | None] = mapped_column(String(80))


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), unique=True)
    estado: Mapped[ConversationState] = mapped_column(
        _enum(ConversationState), default=ConversationState.COLETANDO
    )
    atendente_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    ultimo_contato_cliente_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lembrete_enviado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aviso_fora_horario_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duvidas_sem_solucao: Mapped[int] = mapped_column(SmallInteger, default=0)

    customer: Mapped[Customer] = relationship()
    atendente: Mapped[User | None] = relationship()


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    wa_message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    direcao: Mapped[MessageDirection] = mapped_column(_enum(MessageDirection))
    tipo: Mapped[MessageType] = mapped_column(_enum(MessageType))
    conteudo: Mapped[str | None] = mapped_column(Text)
    media_path: Mapped[str | None] = mapped_column(String(255))
    media_mime: Mapped[str | None] = mapped_column(String(80))
    transcricao: Mapped[str | None] = mapped_column(Text)
    enviado_por: Mapped[SentBy] = mapped_column(_enum(SentBy))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    numero: Mapped[int] = mapped_column(Integer, Identity(start=1000), unique=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus), default=OrderStatus.RASCUNHO)
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    cart_url: Mapped[str | None] = mapped_column(Text)
    shopify_order_id: Mapped[str | None] = mapped_column(String(64))
    exportado_planilha_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Cliente pediu para fechar enquanto havia dúvida aberta: mostrar o resumo ao resolvê-la.
    finalizar_pendente: Mapped[bool] = mapped_column(Boolean, default=False)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.posicao",
    )
    customer: Mapped[Customer] = relationship()


class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    posicao: Mapped[int] = mapped_column(SmallInteger)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    descricao_original: Mapped[str] = mapped_column(Text)
    item_normalizado: Mapped[str] = mapped_column(String(255))
    quantidade: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unidade: Mapped[str] = mapped_column(String(20))
    preco_unitario: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    confianca: Mapped[float | None]
    status: Mapped[ItemStatus] = mapped_column(_enum(ItemStatus), default=ItemStatus.OK)
    # Para itens com dúvida: pergunta feita e ids dos produtos oferecidos como opção.
    pergunta: Mapped[str | None] = mapped_column(Text)
    opcoes: Mapped[list[str]] = mapped_column(JsonType, default=list)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()


class AiRun(TimestampMixin, Base):
    __tablename__ = "ai_runs"

    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    provedor: Mapped[str] = mapped_column(String(20))
    modelo: Mapped[str] = mapped_column(String(64))
    tokens_entrada: Mapped[int | None]
    tokens_saida: Mapped[int | None]
    latencia_ms: Mapped[int | None]
    saida: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    erro: Mapped[str | None] = mapped_column(Text)


class BusinessHours(TimestampMixin, Base):
    __tablename__ = "business_hours"

    # 0 = segunda ... 6 = domingo (datetime.weekday())
    dia_semana: Mapped[int] = mapped_column(SmallInteger, unique=True)
    abre: Mapped[time] = mapped_column(Time)
    fecha: Mapped[time] = mapped_column(Time)


class Holiday(TimestampMixin, Base):
    __tablename__ = "holidays"

    data: Mapped[date] = mapped_column(Date, unique=True)
    descricao: Mapped[str | None] = mapped_column(String(120))


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    acao: Mapped[str] = mapped_column(String(60))
    entidade: Mapped[str] = mapped_column(String(60))
    entidade_id: Mapped[str | None] = mapped_column(String(64))
    diff: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
