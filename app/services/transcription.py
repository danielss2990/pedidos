"""Transcrição de áudios do WhatsApp com o Whisper (OpenAI)."""

from typing import Protocol

import openai

from app.config import Settings

EXTENSIONS = {
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "m4a",
    "audio/amr": "amr",
    "audio/wav": "wav",
    "audio/webm": "webm",
}


class TranscriptionError(Exception):
    pass


class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, mime: str) -> str: ...


class WhisperTranscriber:
    def __init__(self, settings: Settings, client: openai.AsyncOpenAI):
        self.settings = settings
        self.client = client

    async def transcribe(self, audio: bytes, mime: str) -> str:
        base_mime = mime.split(";")[0].strip()
        ext = EXTENSIONS.get(base_mime, "ogg")
        try:
            result = await self.client.audio.transcriptions.create(
                model=self.settings.whisper_model,
                file=(f"audio.{ext}", audio, base_mime),
                language="pt",
                prompt="Pedido de materiais elétricos: cabo flexível, disjuntor, tomada, "
                "interruptor, eletroduto, mm², amperes.",
            )
        except openai.OpenAIError as exc:
            raise TranscriptionError(str(exc)) from exc
        return result.text.strip()
