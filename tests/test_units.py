import hashlib
import hmac
import json
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import get_settings
from app.models import Order, OrderItem, Product
from app.services.business_hours import DEFAULT_HOURS, Schedule
from app.services.cart import CartError, ShopifyCartBuilder
from app.services.catalog import attribute_score, parse_attributes, parse_price
from app.services.extraction import (
    ClaudeExtractor,
    Extracao,
    ExtractionError,
    ExtractionInput,
    build_user_content,
)
from app.services.text import brl, normalize, qty
from app.services.whatsapp import parse_webhook, verify_signature
from tests.conftest import extracao, item


def _webhook(*messages: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "contacts": [{"wa_id": "5511999998888", "profile": {"name": "Maria"}}],
                            "messages": list(messages),
                        },
                    }
                ]
            }
        ],
    }


def test_assinatura_do_webhook():
    body = b'{"a":1}'
    good = "sha256=" + hmac.new(b"segredo", body, hashlib.sha256).hexdigest()
    assert verify_signature("segredo", body, good)
    assert not verify_signature("segredo", body + b" ", good)
    assert not verify_signature("segredo", body, None)
    assert not verify_signature("", body, good)


def test_parse_webhook_tipos():
    base = {"from": "5511999998888", "timestamp": "1700000000"}
    payload = _webhook(
        {**base, "id": "w1", "type": "text", "text": {"body": "oi"}},
        {**base, "id": "w2", "type": "audio", "audio": {"id": "m2", "mime_type": "audio/ogg"}},
        {
            **base,
            "id": "w3",
            "type": "image",
            "image": {"id": "m3", "mime_type": "image/jpeg", "caption": "lista"},
        },
        {
            **base,
            "id": "w4",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "confirmar", "title": "Confirmar"},
            },
        },
        {**base, "id": "w5", "type": "sticker", "sticker": {"id": "s"}},
    )
    msgs = parse_webhook(payload)
    assert [m.kind for m in msgs] == ["text", "audio", "image", "button", "other"]
    assert msgs[0].text == "oi" and msgs[0].profile_name == "Maria"
    assert msgs[1].media_id == "m2"
    assert msgs[2].text == "lista"
    assert msgs[3].button_id == "confirmar"


def test_parse_webhook_ignora_status():
    payload = {
        "entry": [{"changes": [{"field": "messages", "value": {"statuses": [{"id": "x"}]}}]}]
    }
    assert parse_webhook(payload) == []


def test_horario_comercial():
    tz = get_settings().tz
    schedule = Schedule(dict(DEFAULT_HOURS), {date(2026, 11, 2)})
    assert schedule.is_open(datetime(2026, 10, 14, 9, 0, tzinfo=tz))  # quarta
    assert not schedule.is_open(datetime(2026, 10, 14, 18, 0, tzinfo=tz))
    assert schedule.is_open(datetime(2026, 10, 17, 11, 59, tzinfo=tz))  # sábado
    assert not schedule.is_open(datetime(2026, 10, 17, 12, 0, tzinfo=tz))
    assert not schedule.is_open(datetime(2026, 10, 18, 10, 0, tzinfo=tz))  # domingo
    assert not schedule.is_open(datetime(2026, 11, 2, 10, 0, tzinfo=tz))  # feriado
    assert "segunda das 08:00 às 18:00" in schedule.describe()


def _order(*items: tuple[str | None, str]) -> Order:
    order = Order(numero=1001, items=[])
    for i, (variant, quantidade) in enumerate(items, 1):
        product = Product(
            sku=f"S{i}", nome_tecnico=f"P{i}", preco=Decimal(1), shopify_variant_id=variant
        )
        order.items.append(
            OrderItem(
                posicao=i,
                product=product,
                item_normalizado=f"P{i}",
                descricao_original="",
                quantidade=Decimal(quantidade),
                unidade="unidades",
            )
        )
    return order


def test_link_do_carrinho():
    url = ShopifyCartBuilder("https://loja.test/").build_url(
        _order(("111", "2"), ("222", "2.5")), "5511"
    )
    assert url.startswith("https://loja.test/cart/111:2,222:3?")
    assert "attributes%5Bpedido_whatsapp%5D=1001" in url
    assert "%2B5511" in url


def test_link_do_carrinho_sem_variante():
    with pytest.raises(CartError, match="P2"):
        ShopifyCartBuilder("loja.test").build_url(_order(("111", "1"), (None, "1")), None)


def test_formatacao():
    assert brl(Decimal("1234.5")) == "R$ 1.234,50"
    assert qty(Decimal("2.500")) == "2,5"
    assert qty(Decimal("10.000")) == "10"
    assert normalize("Cabo Flexível  2,5mm²") == "cabo flexivel 2,5mm2"


def test_planilha_preco_e_atributos():
    assert parse_price("R$ 1.234,56") == Decimal("1234.56")
    assert parse_price("2.10") == Decimal("2.10")
    assert parse_attributes("bitola_mm2=2.5; cor=Azul; inventado=x") == {
        "bitola_mm2": "2.5",
        "cor": "Azul",
    }


def test_atributos_conflitantes_descartam_produto():
    assert attribute_score({"bitola_mm2": "2,5"}, {"bitola_mm2": "2.5"}) == 1.0
    assert attribute_score({"corrente_a": "10A"}, {"corrente_a": "10"}) == 1.0
    assert attribute_score({"cor": "Azul"}, {"cor": "Preto"}) is None
    assert attribute_score({"cor": "Azul", "polos": "1"}, {"cor": "azul"}) == 0.5


def _walk(schema: dict[str, Any], defs: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    if "$ref" in schema:
        schema = defs[schema["$ref"].split("/")[-1]]
    if schema.get("type") == "object":
        found.append(schema)
        for prop in schema.get("properties", {}).values():
            found += _walk(prop, defs)
    for key in ("items",):
        if isinstance(schema.get(key), dict):
            found += _walk(schema[key], defs)
    for option in schema.get("anyOf", []):
        found += _walk(option, defs)
    return found


def test_schema_da_extracao_e_estrito():
    schema = Extracao.model_json_schema()
    for obj in _walk(schema, schema.get("$defs", {})):
        assert obj.get("additionalProperties") is False
        assert set(obj["required"]) == set(obj["properties"])


def test_conteudo_com_imagem_vem_antes_do_texto():
    content = build_user_content(
        ExtractionInput(
            estado="coletando",
            pedido_atual=["1. Fita Isolante — 1 unidades"],
            duvida_pendente=None,
            texto=None,
            tipo="imagem",
            imagem=b"abc",
            imagem_mime="image/png",
        )
    )
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert "1. Fita Isolante" in content[1]["text"]
    assert "(foto sem legenda)" in content[1]["text"]


class _FakeMessages:
    def __init__(self, response: SimpleNamespace):
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        return self.response


def _claude(stop_reason: str, text: str | None) -> tuple[ClaudeExtractor, _FakeMessages]:
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    response = SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
    )
    messages = _FakeMessages(response)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return ClaudeExtractor(get_settings(), client, {"bucha": "abraçadeira"}), messages


def _input() -> ExtractionInput:
    return ExtractionInput("coletando", [], None, "2 tomadas", "texto")


async def test_extrator_claude_le_json_e_configura_chamada():
    esperado = extracao(itens_novos=[item("Tomada de Embutir 2P+T 10A", 2)])
    extractor, messages = _claude("end_turn", esperado.model_dump_json())
    result = await extractor.extract(_input())
    assert result.extracao == esperado
    assert result.tokens_entrada == 1200
    kwargs = messages.kwargs
    assert kwargs["model"] == get_settings().claude_model
    assert kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "bucha -> abraçadeira" in kwargs["system"][0]["text"]


@pytest.mark.parametrize(
    ("stop_reason", "text"),
    [("refusal", None), ("max_tokens", '{"itens'), ("end_turn", '{"outro": 1}')],
)
async def test_extrator_claude_erros(stop_reason, text):
    extractor, _ = _claude(stop_reason, text)
    with pytest.raises(ExtractionError):
        await extractor.extract(_input())


def test_json_do_documento_de_arquitetura_cabe_no_schema():
    raw = json.loads(
        extracao(
            itens_novos=[item("Cabo Flexível 2,5mm² 750V", 10, "metros", cor="Azul")]
        ).model_dump_json()
    )
    assert raw["itens_novos"][0]["atributos"] == [{"nome": "cor", "valor": "Azul"}]
    assert time(8) < time(18)
