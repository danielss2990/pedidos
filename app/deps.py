import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Role, User
from app.security import decode_token
from app.services.whatsapp import Messenger

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    try:
        payload = decode_token(credentials.credentials, "access")
        user = await session.get(User, uuid.UUID(payload["sub"]))
    except (jwt.InvalidTokenError, KeyError, ValueError):
        user = None
    if user is None or not user.ativo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[..., Coroutine[Any, Any, User]]:
    async def checker(user: CurrentUser) -> User:
        if user.perfil not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Sem permissão")
        return user

    return checker


AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
ManagerUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.SUPERVISOR))]


def get_messenger(request: Request) -> Messenger:
    return request.app.state.messenger


def get_queue(request: Request) -> Any:
    return request.app.state.queue


MessengerDep = Annotated[Messenger, Depends(get_messenger)]
QueueDep = Annotated[Any, Depends(get_queue)]
