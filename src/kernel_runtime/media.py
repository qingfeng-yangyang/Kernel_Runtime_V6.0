from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import ValidationFailure


MAX_MEDIA_BYTES = 25 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {"image", "video", "file"}


@dataclass(frozen=True)
class MediaReference:
    media_id: str
    media_type: str
    uri: str
    mime_type: str
    size_bytes: int
    sha256: str
    alt_text: str = ""

    def validate(self) -> None:
        if not self.media_id or self.media_type not in ALLOWED_MEDIA_TYPES:
            raise ValidationFailure("INVALID_MEDIA", "Invalid media identity or type")
        if not self.uri.startswith(("https://", "storage://")):
            raise ValidationFailure("INVALID_MEDIA_URI", "Media URI must use an approved scheme")
        if self.size_bytes < 0 or self.size_bytes > MAX_MEDIA_BYTES:
            raise ValidationFailure("MEDIA_TOO_LARGE", "Media exceeds the configured size limit")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256.lower()):
            raise ValidationFailure("INVALID_MEDIA_DIGEST", "Media digest must be SHA-256")


class MediaStorageProvider(Protocol):
    def issue_upload(self, media_type: str, mime_type: str, size_bytes: int) -> dict[str, str]: ...

    def resolve(self, media_id: str) -> MediaReference: ...


class MockMediaStorage:
    """In-memory test provider. It never uploads data to the internet."""

    def __init__(self) -> None:
        self._items: dict[str, MediaReference] = {}

    def add(self, item: MediaReference) -> None:
        item.validate()
        self._items[item.media_id] = item

    def issue_upload(self, media_type: str, mime_type: str, size_bytes: int) -> dict[str, str]:
        if media_type not in ALLOWED_MEDIA_TYPES or size_bytes > MAX_MEDIA_BYTES:
            raise ValidationFailure("INVALID_MEDIA", "Upload request is not allowed")
        media_id = f"mock-media-{len(self._items) + 1}"
        return {"media_id": media_id, "upload_uri": f"storage://pending/{media_id}"}

    def resolve(self, media_id: str) -> MediaReference:
        try:
            return self._items[media_id]
        except KeyError as exc:
            raise ValidationFailure("MEDIA_NOT_FOUND", "Media does not exist") from exc
