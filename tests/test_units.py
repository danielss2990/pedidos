import hashlib
import hmac
import json
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.config import get_settings
from app.models import FormaPagamento, Modalidade, Order
from app.services.business_hours import DEFAULT_HOURS, Schedule
from app.services.catalog import attribute_score, parse_attributes, parse_price
from app.services.extraction import (
    Extracao,
    ExtractionError,
    ExtractionInput,
    OllamaExtractor,
    build_user_text,
    inline_refs,
)
from app.services.fulfillment import (
    frete_message,
    next_closing_step,
    parse_modalidade,
    parse_pagamento,
    parse_troco,
)
from app.services.text import brl, normalize, qty
from app.services.transcription import LocalWhisperTranscriber, TranscriptionError
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


def test_parse_respostas_do_fechamento():
    assert parse_modalidade("entrega", "") == Modalidade.ENTREGA
    assert parse_modalidade(None, "Vou buscar aí mais tarde") == Modalidade.RETIRADA
    assert parse_modalidade(None, "pode entregar") == Modalidade.ENTREGA
    assert parse_modalidade(None, "sim") is None
    assert parse_pagamento("cartao", "") == FormaPagamento.CARTAO
    assert parse_pagamento(None, "no PIX") == FormaPagamento.PIX
    assert parse_pagamento(None, "débito") == FormaPagamento.CARTAO
    assert parse_pagamento(None, "em espécie") == FormaPagamento.DINHEIRO
    assert parse_troco("Não precisa") == ""
    assert parse_troco("para 50") == "para 50"


def _closing_order(**fields: Any) -> Order:
    return Order(numero=1001, total=Decimal("100"), items=[], **fields)


def test_proximo_passo_do_fechamento():
    order = _closing_order()
    assert next_closing_step(order) == "modalidade"
    order.modalidade = Modalidade.ENTREGA
    assert next_closing_step(order) == "endereco"
    order.endereco_entrega = "Rua A, 1"
    assert next_closing_step(order) == "pagamento"
    order.forma_pagamento = FormaPagamento.DINHEIRO
    assert next_closing_step(order) == "troco"
    order.troco_para = ""
    assert next_closing_step(order) is None
    retirada = _closing_order(
        modalidade=Modalidade.RETIRADA, forma_pagamento=FormaPagamento.DINHEIRO
    )
    assert next_closing_step(retirada) is None  # troco só na entrega


def test_mensagem_de_frete_com_pix():
    settings = get_settings()
    order = _closing_order(
        modalidade=Modalidade.ENTREGA, forma_pagamento=FormaPagamento.PIX, frete=Decimal("15")
    )
    text = frete_message(order, settings)
    assert "frete de R$ 15,00" in text
    assert "Total a pagar: R$ 115,00" in text
    assert "Pague R$ 115,00 pela chave Pix pix@loja.com" in text


def test_parse_localizacao():
    payload = _webhook(
        {
            "from": "5511999998888",
            "id": "w9",
            "timestamp": "1",
            "type": "location",
            "location": {"latitude": -23.5, "longitude": -46.6, "name": "Obra", "address": "Rua A"},
        }
    )
    msg = parse_webhook(payload)[0]
    assert msg.kind == "location"
    assert (
        msg.text
        == "Obra, Rua A (https://www.openstreetmap.org/?mlat=-23.5&mlon=-46.6#map=18/-23.5/-46.6)"
    )


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


def test_texto_do_usuario_marca_foto_sem_legenda():
    text = build_user_text(
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
    assert "1. Fita Isolante" in text
    assert "(foto sem legenda)" in text


def test_schema_enviado_ao_modelo_nao_tem_referencias():
    schema = inline_refs(Extracao.model_json_schema())
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    item_schema = schema["properties"]["itens_novos"]["items"]
    assert item_schema["additionalProperties"] is False
    assert "unidade" in item_schema["required"]


def _ollama(*replies: Any) -> tuple[OllamaExtractor, list[dict[str, Any]]]:
    """Extrator ligado a um servidor Ollama simulado que devolve as respostas na ordem."""
    calls: list[dict[str, Any]] = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        reply = queue.pop(0)
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": reply},
                "prompt_eval_count": 900,
                "eval_count": 120,
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaExtractor(get_settings(), http, {"bucha": "abraçadeira"}), calls


def _input(imagem: bytes | None = None) -> ExtractionInput:
    return ExtractionInput(
        "coletando", [], None, "2 tomadas", "imagem" if imagem else "texto", imagem
    )


async def test_extrator_ollama_le_json_e_monta_a_chamada():
    esperado = extracao(itens_novos=[item("Tomada de Embutir 2P+T 10A", 2)])
    extractor, calls = _ollama(esperado.model_dump_json())
    result = await extractor.extract(_input())
    assert result.extracao == esperado
    assert result.modelo == get_settings().llm_model_texto
    assert result.tokens_entrada == 900
    body = calls[0]
    assert body["model"] == get_settings().llm_model_texto
    assert body["stream"] is False and body["options"]["temperature"] == 0
    assert body["format"]["type"] == "object"
    assert "bucha -> abraçadeira" in body["messages"][0]["content"]
    assert "images" not in body["messages"][1]


async def test_extrator_ollama_usa_modelo_de_visao_para_fotos():
    extractor, calls = _ollama(extracao(imagem_ilegivel=True).model_dump_json())
    result = await extractor.extract(_input(imagem=b"\xff\xd8"))
    assert result.modelo == get_settings().llm_model_visao
    assert calls[0]["messages"][1]["images"] == ["/9g="]


async def test_extrator_ollama_corrige_json_invalido_na_segunda_tentativa():
    extractor, calls = _ollama('{"itens_novos": "nada"}', extracao().model_dump_json())
    result = await extractor.extract(_input())
    assert result.extracao == extracao()
    assert len(calls) == 2
    assert "não segue o formato" in calls[1]["messages"][-1]["content"]


@pytest.mark.parametrize(
    "replies",
    [
        ('{"x": 1}', "não é json"),
        (httpx.Response(500, text="model not found"),),
    ],
)
async def test_extrator_ollama_erros(replies):
    extractor, _ = _ollama(*replies)
    with pytest.raises(ExtractionError):
        await extractor.extract(_input())


async def test_extrator_ollama_servidor_fora_do_ar():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexão recusada")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ExtractionError, match="indisponível"):
        await OllamaExtractor(get_settings(), http).extract(_input())


class _FakeWhisper:
    def __init__(self, texts: list[str]):
        self.texts = texts
        self.kwargs: dict[str, Any] = {}

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        return [SimpleNamespace(text=t) for t in self.texts], None


async def test_transcricao_local_junta_os_trechos():
    model = _FakeWhisper([" quero dez metros", " de fio azul "])
    text = await LocalWhisperTranscriber(get_settings(), model).transcribe(b"ogg", "audio/ogg")
    assert text == "quero dez metros de fio azul"
    assert model.kwargs["language"] == "pt"


async def test_transcricao_sem_fala_e_erro():
    with pytest.raises(TranscriptionError):
        await LocalWhisperTranscriber(get_settings(), _FakeWhisper([])).transcribe(b"", "audio/ogg")


def test_json_do_documento_de_arquitetura_cabe_no_schema():
    raw = json.loads(
        extracao(
            itens_novos=[item("Cabo Flexível 2,5mm² 750V", 10, "metros", cor="Azul")]
        ).model_dump_json()
    )
    assert raw["itens_novos"][0]["atributos"] == [{"nome": "cor", "valor": "Azul"}]
    assert time(8) < time(18)
