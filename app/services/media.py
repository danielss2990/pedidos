"""Armazenamento das mídias recebidas (áudios e fotos).

No MVP grava em disco no volume do servidor; trocar por um armazenamento S3 compatível
(ex.: MinIO) exige só outra implementação com os mesmos métodos.
"""

import time
import uuid
from pathlib import Path
from typing import Protocol

EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/amr": "amr",
}


class MediaStore(Protocol):
    def save(self, conversation_id: uuid.UUID, data: bytes, mime: str) -> str: ...

    def delete_older_than(self, days: int) -> int: ...


class LocalMediaStore:
    def __init__(self, root: str):
        self.root = Path(root)

    def save(self, conversation_id: uuid.UUID, data: bytes, mime: str) -> str:
        ext = EXTENSIONS.get(mime.split(";")[0].strip(), "bin")
        relative = Path(str(conversation_id)) / f"{uuid.uuid4().hex}.{ext}"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(relative)

    def path(self, relative: str) -> Path:
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError("caminho de mídia inválido")
        return resolved

    def delete_older_than(self, days: int) -> int:
        if not self.root.exists():
            return 0
        limit = time.time() - days * 86400
        removed = 0
        for file in self.root.rglob("*"):
            if file.is_file() and file.stat().st_mtime < limit:
                file.unlink()
                removed += 1
        return removed
