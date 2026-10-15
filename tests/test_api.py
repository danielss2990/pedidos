import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models import Conversation, ConversationState, Customer, Order, Role, User
from app.security import hash_password
from tests.conftest import FakeMessenger


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((name, args, kwargs))


@pytest.fixture
async def api():
    app = create_app(use_lifespan=False)
    app.state.messenger = FakeMessenger()
    app.state.queue = FakeQueue()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.app = app
        yield client


async def _user(session, perfil: Role, email: str) -> User:
    user = User(
        nome=email,
        email=email,
        senha_hash=hash_password("senha-forte-1"),
        perfil=perfil,
        ativo=True,
    )
    session.add(user)
    await session.commit()
    return user


async def _login(api, email: str) -> dict[str, str]:
    r = await api.post("/api/v1/auth/login", json={"email": email, "senha": "senha-forte-1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(b"segredo-meta", body, hashlib.sha256).hexdigest()


async def test_verificacao_do_webhook(api):
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "token-verificacao",
        "hub.challenge": "42",
    }
    r = await api.get("/webhooks/whatsapp", params=params)
    assert r.status_code == 200 and r.text == "42"
    params["hub.verify_token"] = "errado"
    assert (await api.get("/webhooks/whatsapp", params=params)).status_code == 403


async def test_webhook_enfileira_mensagens(api):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "from": "5511",
                                    "id": "wamid.X",
                                    "timestamp": "1",
                                    "type": "text",
                                    "text": {"body": "oi"},
                                }
                            ]
                        },
                    }
                ]
            }
        ]
    }
    body = json.dumps(payload).encode()
    r = await api.post(
        "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body)}
    )
    assert r.status_code == 200 and r.json() == {"recebidas": 1}
    name, args, kwargs = api.app.state.queue.jobs[0]
    assert name == "process_incoming"
    assert args[0]["text"] == "oi"
    assert kwargs["_job_id"] == "wa:wamid.X"


async def test_webhook_rejeita_assinatura_invalida(api):
    r = await api.post(
        "/webhooks/whatsapp", content=b"{}", headers={"X-Hub-Signature-256": "sha256=00"}
    )
    assert r.status_code == 401
    assert api.app.state.queue.jobs == []


async def test_login_e_perfis(api, session):
    await _user(session, Role.ADMIN, "admin@loja.com")
    await _user(session, Role.ATENDENTE, "ana@loja.com")
    admin = await _login(api, "admin@loja.com")
    atendente = await _login(api, "ana@loja.com")

    assert (await api.get("/api/v1/auth/me", headers=atendente)).json()["perfil"] == "atendente"
    assert (await api.get("/api/v1/users", headers=atendente)).status_code == 403
    assert (await api.get("/api/v1/users", headers=admin)).status_code == 200
    assert (await api.get("/api/v1/users")).status_code == 401

    bad = await api.post("/api/v1/auth/login", json={"email": "ana@loja.com", "senha": "errada!!"})
    assert bad.status_code == 401

    r = await api.post(
        "/api/v1/users",
        headers=admin,
        json={
            "nome": "Sueli",
            "email": "sueli@loja.com",
            "senha": "outra-senha-1",
            "perfil": "supervisor",
        },
    )
    assert r.status_code == 201


async def test_refresh_por_cookie(api, session):
    await _user(session, Role.ATENDENTE, "ana@loja.com")
    await _login(api, "ana@loja.com")
    r = await api.post("/api/v1/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]


async def test_atendente_assume_responde_e_devolve(api, session):
    await _user(session, Role.ATENDENTE, "ana@loja.com")
    headers = await _login(api, "ana@loja.com")
    customer = Customer(telefone_e164="5511999998888")
    session.add(customer)
    await session.flush()
    conversation = Conversation(
        customer_id=customer.id,
        estado=ConversationState.ATENDIMENTO_HUMANO,
        duvidas_sem_solucao=0,
        ultimo_contato_cliente_em=datetime.now(UTC),
    )
    session.add(conversation)
    await session.commit()
    base = f"/api/v1/conversations/{conversation.id}"

    lista = await api.get("/api/v1/conversations?estado=atendimento_humano", headers=headers)
    assert lista.json()["total"] == 1

    assert (
        await api.post(f"{base}/messages", headers=headers, json={"texto": "Oi!"})
    ).status_code == 409
    assert (await api.post(f"{base}/assume", headers=headers)).status_code == 200
    r = await api.post(f"{base}/messages", headers=headers, json={"texto": "Oi, sou a Ana."})
    assert r.status_code == 201 and r.json()["enviado_por"] == "atendente"
    assert api.app.state.messenger.last == "Oi, sou a Ana."

    r = await api.post(f"{base}/release", headers=headers)
    assert r.json()["estado"] == "coletando"
    msgs = await api.get(f"{base}/messages", headers=headers)
    assert [m["conteudo"] for m in msgs.json()] == ["Oi, sou a Ana."]


async def test_catalogo_crud_e_busca(api, session):
    await _user(session, Role.ADMIN, "admin@loja.com")
    admin = await _login(api, "admin@loja.com")
    r = await api.post(
        "/api/v1/products",
        headers=admin,
        json={
            "sku": "ABR-NY-10",
            "nome_tecnico": "Abraçadeira de Nylon 10cm",
            "preco": "12.50",
            "sinonimos": ["enforca gato", "bucha"],
        },
    )
    assert r.status_code == 201
    busca = await api.get("/api/v1/products?q=enforca", headers=admin)
    assert busca.json()["items"][0]["sinonimos"] == ["enforca gato", "bucha"]

    pid = r.json()["id"]
    r = await api.patch(f"/api/v1/products/{pid}", headers=admin, json={"preco": "13.00"})
    assert r.json()["preco"] == "13.00"

    assert (await api.post("/api/v1/products/sync", headers=admin)).status_code == 202
    assert api.app.state.queue.jobs[-1][0] == "sync_catalog"


async def test_horario_comercial_api(api, session):
    await _user(session, Role.ADMIN, "admin@loja.com")
    admin = await _login(api, "admin@loja.com")
    padrao = await api.get("/api/v1/settings/business-hours", headers=admin)
    assert len(padrao.json()) == 6
    novo = [{"dia_semana": 0, "abre": "07:30", "fecha": "17:00"}]
    r = await api.put("/api/v1/settings/business-hours", headers=admin, json=novo)
    assert r.status_code == 200
    assert (await api.get("/api/v1/settings/business-hours", headers=admin)).json()[0][
        "abre"
    ] == "07:30:00"


async def test_webhook_shopify_marca_pago(api, session):
    customer = Customer(telefone_e164="5511")
    session.add(customer)
    await session.flush()
    conversation = Conversation(customer_id=customer.id, duvidas_sem_solucao=0)
    session.add(conversation)
    await session.flush()
    order = Order(
        conversation_id=conversation.id, customer_id=customer.id, finalizar_pendente=False
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)

    payload = {
        "id": 555,
        "financial_status": "paid",
        "note_attributes": [{"name": "pedido_whatsapp", "value": str(order.numero)}],
    }
    body = json.dumps(payload).encode()
    sig = base64.b64encode(hmac.new(b"segredo-shopify", body, hashlib.sha256).digest()).decode()
    r = await api.post(
        "/webhooks/shopify/orders", content=body, headers={"X-Shopify-Hmac-Sha256": sig}
    )
    assert r.json() == {"resultado": "ok"}
    await session.refresh(order)
    assert order.status.value == "pago" and order.shopify_order_id == "555"
