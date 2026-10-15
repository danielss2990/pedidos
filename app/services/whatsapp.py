"""Cliente da WhatsApp Cloud API (Meta) e leitura dos webhooks."""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import Settings

GRAPH_URL = "https://graph.facebook.com"

# Limite do corpo de mensagens interativas na Cloud API.
INTERACTIVE_BODY_LIMIT = 1024
TEXT_LIMIT = 4096


@dataclass(frozen=True)
class IncomingMessage:
    wa_message_id: str
    phone: str  # wa_id, só dígitos (ex.: 5511999998888)
    profile_name: str | None
    timestamp: int
    kind: str  # text | audio | image | button | other
    text: str | None = None
    media_id: str | None = None
    media_mime: str | None = None
    button_id: str | None = None

    def to_job(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_job(cls, data: dict[str, Any]) -> "IncomingMessage":
        return cls(**data)


@dataclass(frozen=True)
class Button:
    id: str
    title: str  # até 20 caracteres


class Messenger(Protocol):
    async def send_text(self, phone: str, body: str) -> str | None: ...

    async def send_buttons(self, phone: str, body: str, buttons: list[Button]) -> str | None: ...

    async def download_media(self, media_id: str) -> tuple[bytes, str]: ...


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """Valida o cabeçalho X-Hub-Signature-256 enviado pela Meta."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_webhook(payload: dict[str, Any]) -> list[IncomingMessage]:
    """Extrai as mensagens recebidas de um webhook. Eventos de status são ignorados."""
    messages: list[IncomingMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            names = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in value.get("contacts", [])
            }
            for raw in value.get("messages", []):
                messages.append(_parse_message(raw, names))
    return messages


def _parse_message(raw: dict[str, Any], names: dict[str, str | None]) -> IncomingMessage:
    phone = raw["from"]
    base = {
        "wa_message_id": raw["id"],
        "phone": phone,
        "profile_name": names.get(phone),
        "timestamp": int(raw.get("timestamp", 0)),
    }
    kind = raw.get("type")
    if kind == "text":
        return IncomingMessage(**base, kind="text", text=raw["text"]["body"])
    if kind in ("audio", "voice"):
        media = raw.get(kind, {})
        return IncomingMessage(
            **base, kind="audio", media_id=media.get("id"), media_mime=media.get("mime_type")
        )
    if kind == "image":
        media = raw["image"]
        return IncomingMessage(
            **base,
            kind="image",
            media_id=media.get("id"),
            media_mime=media.get("mime_type"),
            text=media.get("caption"),
        )
    if kind == "interactive":
        interactive = raw["interactive"]
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return IncomingMessage(
            **base, kind="button", button_id=reply.get("id"), text=reply.get("title")
        )
    if kind == "button":
        button = raw["button"]
        return IncomingMessage(
            **base, kind="button", button_id=button.get("payload"), text=button.get("text")
        )
    return IncomingMessage(**base, kind="other")


class WhatsAppClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.whatsapp_access_token}"}

    @property
    def _base(self) -> str:
        return f"{GRAPH_URL}/{self.settings.whatsapp_api_version}"

    async def _send(self, payload: dict[str, Any]) -> str | None:
        url = f"{self._base}/{self.settings.whatsapp_phone_number_id}/messages"
        response = await self.http.post(
            url, json={"messaging_product": "whatsapp", **payload}, headers=self._headers
        )
        response.raise_for_status()
        ids = response.json().get("messages") or [{}]
        return ids[0].get("id")

    async def send_text(self, phone: str, body: str) -> str | None:
        return await self._send(
            {"to": phone, "type": "text", "text": {"body": body[:TEXT_LIMIT], "preview_url": True}}
        )

    async def send_buttons(self, phone: str, body: str, buttons: list[Button]) -> str | None:
        return await self._send(
            {
                "to": phone,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body[:INTERACTIVE_BODY_LIMIT]},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": b.id, "title": b.title[:20]}}
                            for b in buttons[:3]
                        ]
                    },
                },
            }
        )

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        meta = await self.http.get(f"{self._base}/{media_id}", headers=self._headers)
        meta.raise_for_status()
        info = meta.json()
        content = await self.http.get(info["url"], headers=self._headers)
        content.raise_for_status()
        return content.content, info.get("mime_type", "application/octet-stream")
