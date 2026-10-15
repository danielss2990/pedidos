import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    ConversationState,
    ItemStatus,
    MessageDirection,
    MessageType,
    OrderStatus,
    Role,
    SentBy,
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ auth/usuários
class LoginIn(BaseModel):
    email: EmailStr
    senha: str


class UserOut(ORM):
    id: uuid.UUID
    nome: str
    email: str
    perfil: Role
    ativo: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    email: EmailStr
    senha: str = Field(min_length=8)
    perfil: Role


class UserUpdate(BaseModel):
    nome: str | None = None
    perfil: Role | None = None
    ativo: bool | None = None
    senha: str | None = Field(default=None, min_length=8)


# ------------------------------------------------------------------ conversas
class CustomerOut(ORM):
    id: uuid.UUID
    telefone_e164: str | None
    nome_whatsapp: str | None
    nome: str | None


class ConversationOut(ORM):
    id: uuid.UUID
    estado: ConversationState
    atendente_id: uuid.UUID | None
    ultimo_contato_cliente_em: datetime | None
    updated_at: datetime
    customer: CustomerOut


class MessageOut(ORM):
    id: uuid.UUID
    direcao: MessageDirection
    tipo: MessageType
    conteudo: str | None
    transcricao: str | None
    media_path: str | None
    media_mime: str | None
    enviado_por: SentBy
    user_id: uuid.UUID | None
    created_at: datetime


class SendMessageIn(BaseModel):
    texto: str = Field(min_length=1, max_length=4096)


# ------------------------------------------------------------------ pedidos
class OrderItemOut(ORM):
    id: uuid.UUID
    posicao: int
    product_id: uuid.UUID | None
    descricao_original: str
    item_normalizado: str
    quantidade: Decimal
    unidade: str
    preco_unitario: Decimal | None
    confianca: float | None
    status: ItemStatus
    pergunta: str | None


class OrderOut(ORM):
    id: uuid.UUID
    numero: int
    status: OrderStatus
    total: Decimal | None
    cart_url: str | None
    confirmado_em: datetime | None
    exportado_planilha_em: datetime | None
    created_at: datetime
    customer: CustomerOut
    items: list[OrderItemOut]


# ------------------------------------------------------------------ catálogo
class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    nome_tecnico: str = Field(min_length=2, max_length=255)
    categoria: str | None = None
    atributos: dict[str, Any] = {}
    unidade_venda: str = "unidades"
    preco: Decimal = Field(ge=0)
    ativo: bool = True
    shopify_variant_id: str | None = None
    sinonimos: list[str] = []


class ProductUpdate(BaseModel):
    nome_tecnico: str | None = None
    categoria: str | None = None
    atributos: dict[str, Any] | None = None
    unidade_venda: str | None = None
    preco: Decimal | None = Field(default=None, ge=0)
    ativo: bool | None = None
    shopify_variant_id: str | None = None
    sinonimos: list[str] | None = None


class ProductOut(ORM):
    id: uuid.UUID
    sku: str
    nome_tecnico: str
    categoria: str | None
    atributos: dict[str, Any]
    unidade_venda: str
    preco: Decimal
    ativo: bool
    shopify_variant_id: str | None
    sinonimos: list[str] = []


class SyncOut(BaseModel):
    criados: int
    atualizados: int
    ignorados: int


# ------------------------------------------------------------------ configurações
class BusinessHoursItem(BaseModel):
    dia_semana: int = Field(ge=0, le=6)
    abre: time
    fecha: time


class Page[T](BaseModel):
    items: list[T]
    total: int
