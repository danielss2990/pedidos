"""Google Sheets: exportação de pedidos e leitura do catálogo mantido pelo cliente."""

import asyncio
from typing import Any, Protocol

from app.config import Settings
from app.models import Order
from app.services.text import normalize

ORDER_HEADER = [
    "data",
    "pedido",
    "cliente",
    "telefone",
    "sku",
    "item",
    "quantidade",
    "unidade",
    "preco_unitario",
    "subtotal",
    "total_pedido",
    "status",
    "link_carrinho",
]


class SheetsError(Exception):
    pass


class OrderSink(Protocol):
    async def export_order(self, order: Order, settings: Settings) -> None: ...


class CatalogSource(Protocol):
    async def read_catalog(self) -> list[dict[str, Any]]: ...


def order_rows(order: Order, settings: Settings) -> list[list[str]]:
    quando = (order.confirmado_em or order.created_at).astimezone(settings.tz)
    customer = order.customer
    rows = []
    for item in order.items:
        preco = item.preco_unitario or 0
        rows.append(
            [
                quando.strftime("%d/%m/%Y %H:%M"),
                str(order.numero),
                (customer.nome or customer.nome_whatsapp or "") if customer else "",
                (customer.telefone_e164 or "") if customer else "",
                item.product.sku if item.product else "",
                item.item_normalizado,
                str(item.quantidade.normalize()),
                item.unidade,
                f"{preco:.2f}",
                f"{preco * item.quantidade:.2f}",
                f"{order.total or 0:.2f}",
                order.status.value,
                order.cart_url or "",
            ]
        )
    return rows


class GoogleSheets:
    """Implementa OrderSink e CatalogSource sobre uma única planilha."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._spreadsheet = None

    def _open(self):
        if self._spreadsheet is None:
            import gspread

            if not self.settings.google_service_account_file or not self.settings.google_sheets_id:
                raise SheetsError("Google Sheets não configurado")
            client = gspread.service_account(filename=self.settings.google_service_account_file)
            self._spreadsheet = client.open_by_key(self.settings.google_sheets_id)
        return self._spreadsheet

    def _orders_worksheet(self):
        import gspread

        spreadsheet = self._open()
        try:
            return spreadsheet.worksheet(self.settings.sheets_orders_tab)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(self.settings.sheets_orders_tab, rows=1000, cols=20)
            ws.append_row(ORDER_HEADER)
            return ws

    async def export_order(self, order: Order, settings: Settings) -> None:
        rows = order_rows(order, settings)

        def _append() -> None:
            self._orders_worksheet().append_rows(rows, value_input_option="USER_ENTERED")

        await asyncio.to_thread(_append)

    async def read_catalog(self) -> list[dict[str, Any]]:
        def _read() -> list[dict[str, Any]]:
            ws = self._open().worksheet(self.settings.sheets_catalog_tab)
            records = ws.get_all_records()
            return [{normalize(str(k)).replace(" ", "_"): v for k, v in r.items()} for r in records]

        return await asyncio.to_thread(_read)
