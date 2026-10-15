"""Link de carrinho pré-montado da Shopify (cart permalink)."""

import math
from decimal import Decimal
from typing import Protocol
from urllib.parse import urlencode

from app.models import Order


class CartError(Exception):
    pass


class CartBuilder(Protocol):
    def build_url(self, order: Order, phone: str | None) -> str: ...


def variant_quantity(quantidade: Decimal) -> int:
    """A Shopify só aceita quantidades inteiras; frações sobem (2,5 m vira 3)."""
    return max(1, math.ceil(quantidade))


class ShopifyCartBuilder:
    def __init__(self, store_domain: str):
        self.store_domain = store_domain.removeprefix("https://").rstrip("/")

    def build_url(self, order: Order, phone: str | None) -> str:
        if not self.store_domain:
            raise CartError("SHOPIFY_STORE_DOMAIN não configurado")
        parts = []
        sem_variante = []
        for item in order.items:
            variant = item.product.shopify_variant_id if item.product else None
            if not variant:
                sem_variante.append(item.item_normalizado)
                continue
            parts.append(f"{variant}:{variant_quantity(item.quantidade)}")
        if sem_variante:
            raise CartError("Itens sem variante Shopify: " + ", ".join(sem_variante))
        if not parts:
            raise CartError("Pedido sem itens")
        params = {"attributes[pedido_whatsapp]": str(order.numero), "ref": "whatsapp"}
        if phone:
            params["checkout[shipping_address][phone]"] = f"+{phone}"
        return f"https://{self.store_domain}/cart/{','.join(parts)}?{urlencode(params)}"
