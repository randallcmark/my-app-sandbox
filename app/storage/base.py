from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int


class StorageProvider(Protocol):
    def save(self, key: str, content: bytes) -> StoredObject:
        """Store bytes at a provider-relative key."""

    def load(self, key: str) -> bytes:
        """Load bytes from a provider-relative key."""

    def delete(self, key: str) -> None:
        """Delete bytes at a provider-relative key if they exist."""

    def exists(self, key: str) -> bool:
        """Return whether a provider-relative key exists."""

