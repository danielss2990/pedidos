import uuid

import jwt
from fastapi import APIRouter, Cookie, HTTPException, Response, status
from sqlalchemy import func, select

from app.config import get_settings
from app.deps import AdminUser, CurrentUser, SessionDep
from app.models import AuditLog, User
from app.schemas import LoginIn, TokenOut, UserCreate, UserOut, UserUpdate
from app.security import create_token, decode_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1", tags=["auth"])

REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        create_token(str(user.id), "refresh"),
        httponly=True,
        secure=settings.app_env != "development",
        samesite="strict",
        max_age=settings.refresh_token_days * 86400,
        path="/api/v1/auth",
    )


@router.post("/auth/login", response_model=TokenOut)
async def login(data: LoginIn, response: Response, session: SessionDep) -> TokenOut:
    user = await session.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    if user is None or not user.ativo or not verify_password(data.senha, user.senha_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha inválidos")
    _set_refresh_cookie(response, user)
    return TokenOut(
        access_token=create_token(str(user.id), "access"), user=UserOut.model_validate(user)
    )


@router.post("/auth/refresh", response_model=TokenOut)
async def refresh(
    response: Response, session: SessionDep, refresh_token: str | None = Cookie(default=None)
) -> TokenOut:
    try:
        payload = decode_token(refresh_token or "", "refresh")
        user = await session.get(User, uuid.UUID(payload["sub"]))
    except (jwt.InvalidTokenError, KeyError, ValueError):
        user = None
    if user is None or not user.ativo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão expirada")
    _set_refresh_cookie(response, user)
    return TokenOut(
        access_token=create_token(str(user.id), "access"), user=UserOut.model_validate(user)
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/auth/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.get("/users", response_model=list[UserOut])
async def list_users(_: AdminUser, session: SessionDep) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.nome))).all())


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, admin: AdminUser, session: SessionDep) -> User:
    exists = await session.scalar(
        select(User.id).where(func.lower(User.email) == data.email.lower())
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado")
    user = User(
        nome=data.nome,
        email=data.email.lower(),
        senha_hash=hash_password(data.senha),
        perfil=data.perfil,
        ativo=True,
    )
    session.add(user)
    await session.flush()
    session.add(
        AuditLog(
            user_id=admin.id,
            acao="criar",
            entidade="user",
            entidade_id=str(user.id),
            diff={"email": user.email, "perfil": user.perfil.value},
        )
    )
    await session.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, data: UserUpdate, admin: AdminUser, session: SessionDep
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")
    changes = data.model_dump(exclude_unset=True)
    if "senha" in changes:
        user.senha_hash = hash_password(changes.pop("senha"))
    for key, value in changes.items():
        setattr(user, key, value)
    session.add(
        AuditLog(
            user_id=admin.id,
            acao="alterar",
            entidade="user",
            entidade_id=str(user.id),
            diff={k: str(v) for k, v in changes.items()},
        )
    )
    await session.commit()
    return user
