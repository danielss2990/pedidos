"""remove google sheets

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16 04:01:26.051675
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A planilha do Google deu lugar à exportação CSV/XLSX pelo painel.
    op.drop_column("orders", "exportado_planilha_em")


def downgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "exportado_planilha_em",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
