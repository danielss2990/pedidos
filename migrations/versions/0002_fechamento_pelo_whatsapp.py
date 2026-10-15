"""fechamento pelo whatsapp

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 01:27:54.424691
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("aviso_pedido_em_andamento_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "modalidade",
            sa.Enum("retirada", "entrega", name="modalidade", native_enum=False, length=32),
            nullable=True,
        ),
    )
    op.add_column("orders", sa.Column("endereco_entrega", sa.Text(), nullable=True))
    op.add_column(
        "orders",
        sa.Column(
            "forma_pagamento",
            sa.Enum(
                "pix", "cartao", "dinheiro", name="formapagamento", native_enum=False, length=32
            ),
            nullable=True,
        ),
    )
    op.add_column("orders", sa.Column("troco_para", sa.String(length=80), nullable=True))
    op.add_column("orders", sa.Column("frete", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("orders", sa.Column("pago_em", sa.DateTime(timezone=True), nullable=True))
    # Status da era Shopify: o carrinho enviado vira pedido novo para a equipe; o pago, concluído.
    op.execute("UPDATE orders SET status = 'confirmado' WHERE status = 'carrinho_enviado'")
    op.execute("UPDATE orders SET status = 'concluido', pago_em = updated_at WHERE status = 'pago'")
    op.execute("UPDATE conversations SET estado = 'coletando' WHERE estado = 'concluido'")
    op.drop_column("orders", "cart_url")
    op.drop_column("orders", "shopify_order_id")
    op.drop_column("products", "shopify_variant_id")


def downgrade() -> None:
    op.add_column(
        "products",
        sa.Column("shopify_variant_id", sa.VARCHAR(length=64), autoincrement=False, nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("shopify_order_id", sa.VARCHAR(length=64), autoincrement=False, nullable=True),
    )
    op.add_column("orders", sa.Column("cart_url", sa.TEXT(), autoincrement=False, nullable=True))
    op.drop_column("orders", "pago_em")
    op.drop_column("orders", "frete")
    op.drop_column("orders", "troco_para")
    op.drop_column("orders", "forma_pagamento")
    op.drop_column("orders", "endereco_entrega")
    op.drop_column("orders", "modalidade")
    op.drop_column("conversations", "aviso_pedido_em_andamento_em")
    op.execute(
        "UPDATE orders SET status = 'confirmado' "
        "WHERE status IN ('fechando', 'em_separacao', 'pronto', 'concluido')"
    )
    op.execute(
        "UPDATE conversations SET estado = 'coletando' "
        "WHERE estado IN ('fechando', 'pedido_em_andamento')"
    )
