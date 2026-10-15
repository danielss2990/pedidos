"""estrutura inicial

Revision ID: 0001
Revises:
Create Date: 2026-10-15 00:11:32.690243
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Busca por similaridade no catálogo.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "business_hours",
        sa.Column("dia_semana", sa.SmallInteger(), nullable=False),
        sa.Column("abre", sa.Time(), nullable=False),
        sa.Column("fecha", sa.Time(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dia_semana"),
    )
    op.create_table(
        "customers",
        sa.Column("telefone_e164", sa.String(length=20), nullable=True),
        sa.Column("nome_whatsapp", sa.String(length=120), nullable=True),
        sa.Column("nome", sa.String(length=120), nullable=True),
        sa.Column("consentimento_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anonimizado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telefone_e164"),
    )
    op.create_table(
        "holidays",
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("descricao", sa.String(length=120), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data"),
    )
    op.create_table(
        "products",
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("nome_tecnico", sa.String(length=255), nullable=False),
        sa.Column("categoria", sa.String(length=80), nullable=True),
        sa.Column(
            "atributos",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("unidade_venda", sa.String(length=20), nullable=False),
        sa.Column("preco", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("shopify_variant_id", sa.String(length=64), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku"),
    )
    op.create_index(
        "ix_products_search_text_trgm",
        "products",
        ["search_text"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.create_table(
        "slang_dictionary",
        sa.Column("termo", sa.String(length=120), nullable=False),
        sa.Column("significado", sa.String(length=255), nullable=False),
        sa.Column("categoria", sa.String(length=80), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("termo"),
    )
    op.create_table(
        "users",
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("senha_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "perfil",
            sa.Enum("admin", "supervisor", "atendente", name="role", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "audit_log",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("acao", sa.String(length=60), nullable=False),
        sa.Column("entidade", sa.String(length=60), nullable=False),
        sa.Column("entidade_id", sa.String(length=64), nullable=True),
        sa.Column(
            "diff",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversations",
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "estado",
            sa.Enum(
                "coletando",
                "aguardando_confirmacao",
                "atendimento_humano",
                "concluido",
                name="conversationstate",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("atendente_id", sa.Uuid(), nullable=True),
        sa.Column("ultimo_contato_cliente_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lembrete_enviado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aviso_fora_horario_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duvidas_sem_solucao", sa.SmallInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["atendente_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_table(
        "product_synonyms",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("termo", sa.String(length=120), nullable=False),
        sa.Column("origem", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("wa_message_id", sa.String(length=128), nullable=True),
        sa.Column(
            "direcao",
            sa.Enum("entrada", "saida", name="messagedirection", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "tipo",
            sa.Enum(
                "texto",
                "audio",
                "imagem",
                "botao",
                "outro",
                name="messagetype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("conteudo", sa.Text(), nullable=True),
        sa.Column("media_path", sa.String(length=255), nullable=True),
        sa.Column("media_mime", sa.String(length=80), nullable=True),
        sa.Column("transcricao", sa.Text(), nullable=True),
        sa.Column(
            "enviado_por",
            sa.Enum("cliente", "bot", "atendente", name="sentby", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wa_message_id"),
    )
    op.create_index(
        op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False
    )
    op.create_table(
        "orders",
        sa.Column("numero", sa.Integer(), sa.Identity(always=False, start=1000), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "rascunho",
                "aguardando_confirmacao",
                "confirmado",
                "carrinho_enviado",
                "pago",
                "cancelado",
                name="orderstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("cart_url", sa.Text(), nullable=True),
        sa.Column("shopify_order_id", sa.String(length=64), nullable=True),
        sa.Column("exportado_planilha_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmado_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizar_pendente", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("numero"),
    )
    op.create_index(op.f("ix_orders_conversation_id"), "orders", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_orders_customer_id"), "orders", ["customer_id"], unique=False)
    op.create_table(
        "ai_runs",
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("provedor", sa.String(length=20), nullable=False),
        sa.Column("modelo", sa.String(length=64), nullable=False),
        sa.Column("tokens_entrada", sa.Integer(), nullable=True),
        sa.Column("tokens_saida", sa.Integer(), nullable=True),
        sa.Column("latencia_ms", sa.Integer(), nullable=True),
        sa.Column(
            "saida",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("erro", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "order_items",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("posicao", sa.SmallInteger(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("descricao_original", sa.Text(), nullable=False),
        sa.Column("item_normalizado", sa.String(length=255), nullable=False),
        sa.Column("quantidade", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unidade", sa.String(length=20), nullable=False),
        sa.Column("preco_unitario", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("confianca", sa.Double(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("ok", "pendente_duvida", name="itemstatus", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("pergunta", sa.Text(), nullable=True),
        sa.Column(
            "opcoes",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("ai_runs")
    op.drop_index(op.f("ix_orders_customer_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_conversation_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_table("product_synonyms")
    op.drop_table("conversations")
    op.drop_table("audit_log")
    op.drop_table("users")
    op.drop_table("slang_dictionary")
    op.drop_index(
        "ix_products_search_text_trgm",
        table_name="products",
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    op.drop_table("products")
    op.drop_table("holidays")
    op.drop_table("customers")
    op.drop_table("business_hours")
