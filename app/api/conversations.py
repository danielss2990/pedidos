import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.deps import CurrentUser, MessengerDep, SessionDep
from app.models import (
    Conversation,
    ConversationState,
    Message,
    MessageDirection,
    MessageType,
    Role,
    SentBy,
)
from app.schemas import ConversationOut, MessageOut, Page, SendMessageIn
from app.services.media import LocalMediaStore

router = APIRouter(prefix="/api/v1/conversations", tags=["conversas"])

# Fora desta janela a Meta só aceita mensagens de template aprovadas.
SERVICE_WINDOW = timedelta(hours=24)


async def _get(session: SessionDep, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.customer))
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada")
    return conversation


@router.get("", response_model=Page[ConversationOut])
async def list_conversations(
    user: CurrentUser,
    session: SessionDep,
    estado: ConversationState | None = None,
    minhas: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> Page[ConversationOut]:
    query = select(Conversation)
    if estado is not None:
        query = query.where(Conversation.estado == estado)
    if minhas:
        query = query.where(Conversation.atendente_id == user.id)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(
        query.options(selectinload(Conversation.customer))
        .order_by(Conversation.ultimo_contato_cliente_em.desc().nulls_last())
        .limit(limit)
        .offset(offset)
    )
    return Page(items=[ConversationOut.model_validate(c) for c in rows], total=total)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    _: CurrentUser,
    session: SessionDep,
    limit: int = Query(100, le=500),
) -> list[Message]:
    await _get(session, conversation_id)
    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return list(reversed(rows.all()))


@router.get("/{conversation_id}/messages/{message_id}/media")
async def get_media(
    conversation_id: uuid.UUID, message_id: uuid.UUID, _: CurrentUser, session: SessionDep
) -> FileResponse:
    message = await session.get(Message, message_id)
    if message is None or message.conversation_id != conversation_id or not message.media_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mídia não encontrada")
    path = LocalMediaStore(get_settings().media_dir).path(message.media_path)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "Mídia removida pela política de retenção")
    return FileResponse(path, media_type=message.media_mime or "application/octet-stream")


@router.post("/{conversation_id}/assume", response_model=ConversationOut)
async def assume(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Conversation:
    conversation = await _get(session, conversation_id)
    if conversation.atendente_id not in (None, user.id) and user.perfil == Role.ATENDENTE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Conversa já assumida por outra pessoa")
    conversation.estado = ConversationState.ATENDIMENTO_HUMANO
    conversation.atendente_id = user.id
    await session.commit()
    return conversation


@router.post("/{conversation_id}/release", response_model=ConversationOut)
async def release(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Conversation:
    conversation = await _get(session, conversation_id)
    if conversation.atendente_id not in (None, user.id) and user.perfil == Role.ATENDENTE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Conversa de outro atendente")
    conversation.estado = ConversationState.COLETANDO
    conversation.atendente_id = None
    conversation.duvidas_sem_solucao = 0
    await session.commit()
    return conversation


@router.post(
    "/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED
)
async def send_message(
    conversation_id: uuid.UUID,
    data: SendMessageIn,
    user: CurrentUser,
    session: SessionDep,
    messenger: MessengerDep,
) -> Message:
    conversation = await _get(session, conversation_id)
    if (
        conversation.estado != ConversationState.ATENDIMENTO_HUMANO
        or conversation.atendente_id != user.id
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Assuma a conversa antes de responder")
    last = conversation.ultimo_contato_cliente_em
    if last is None or datetime.now(UTC) - last > SERVICE_WINDOW:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Passaram mais de 24 h desde a última mensagem do cliente; "
            "a Meta só permite mensagens de template.",
        )
    phone = conversation.customer.telefone_e164
    if phone is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cliente anonimizado")
    wa_id = await messenger.send_text(phone, data.texto)
    message = Message(
        conversation_id=conversation.id,
        wa_message_id=wa_id,
        direcao=MessageDirection.SAIDA,
        tipo=MessageType.TEXTO,
        conteudo=data.texto,
        enviado_por=SentBy.ATENDENTE,
        user_id=user.id,
    )
    session.add(message)
    await session.commit()
    return message
