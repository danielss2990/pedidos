"""Comandos de administração.

python -m app.cli create-admin --nome "Fulano" --email fulano@loja.com
python -m app.cli import-catalog data/catalogo_exemplo.csv
python -m app.cli seed-hours
"""

import argparse
import asyncio
import csv
import getpass

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import BusinessHours, Role, User
from app.security import hash_password
from app.services import catalog
from app.services.business_hours import DEFAULT_HOURS


async def create_admin(nome: str, email: str, senha: str) -> None:
    async with SessionLocal() as session:
        if await session.scalar(select(User.id).where(func.lower(User.email) == email.lower())):
            print("Já existe um usuário com este e-mail.")
            return
        session.add(
            User(
                nome=nome,
                email=email.lower(),
                senha_hash=hash_password(senha),
                perfil=Role.ADMIN,
                ativo=True,
            )
        )
        await session.commit()
    print(f"Administrador {email} criado.")


async def import_catalog(path: str) -> None:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    async with SessionLocal() as session:
        stats = await catalog.import_rows(session, rows)
        await session.commit()
    print(f"Catálogo importado: {stats}")


async def seed_hours() -> None:
    async with SessionLocal() as session:
        if await session.scalar(select(func.count()).select_from(BusinessHours)):
            print("Horário comercial já configurado.")
            return
        for dia, (abre, fecha) in DEFAULT_HOURS.items():
            session.add(BusinessHours(dia_semana=dia, abre=abre, fecha=fecha))
        await session.commit()
    print("Horário padrão gravado (seg–sex 8h–18h, sáb 8h–12h).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin")
    admin.add_argument("--nome", required=True)
    admin.add_argument("--email", required=True)
    imp = sub.add_parser("import-catalog")
    imp.add_argument("arquivo")
    sub.add_parser("seed-hours")
    args = parser.parse_args()

    if args.command == "create-admin":
        senha = getpass.getpass("Senha (mín. 8 caracteres): ")
        if len(senha) < 8:
            parser.error("senha curta demais")
        asyncio.run(create_admin(args.nome, args.email, senha))
    elif args.command == "import-catalog":
        asyncio.run(import_catalog(args.arquivo))
    elif args.command == "seed-hours":
        asyncio.run(seed_hours())


if __name__ == "__main__":
    main()
