"""Transcrição de áudios do WhatsApp com o Whisper rodando localmente (faster-whisper)."""

import asyncio
import io
import threading
from typing import Any, Protocol

from app.config import Settings

PROMPT = (
    "Pedido de materiais elétricos: cabo flexível, disjuntor, tomada, interruptor, "
    "eletroduto, mm², amperes."
)


class TranscriptionError(Exception):
    pass


class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, mime: str) -> str: ...


class LocalWhisperTranscriber:
    """Carrega o modelo na primeira transcrição e roda numa thread (é pesado em CPU)."""

    def __init__(self, settings: Settings, model: Any = None):
        self.settings = settings
        self._model = model
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.settings.whisper_model,
                    device=self.settings.whisper_device,
                    compute_type=self.settings.whisper_compute_type,
                    download_root=self.settings.whisper_download_dir,
                )
            return self._model

    def _run(self, audio: bytes) -> str:
        segments, _info = self._get_model().transcribe(
            io.BytesIO(audio),
            language="pt",
            initial_prompt=PROMPT,
            vad_filter=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    async def transcribe(self, audio: bytes, mime: str) -> str:
        try:
            text = await asyncio.to_thread(self._run, audio)
        except Exception as exc:  # áudio corrompido, modelo ausente etc.
            raise TranscriptionError(str(exc)) from exc
        if not text:
            raise TranscriptionError("áudio sem fala reconhecível")
        return text
