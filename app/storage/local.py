from pathlib import Path

from app.storage.base import StoredObject
from app.storage.paths import normalize_storage_key, resolve_storage_path


class LocalStorageProvider:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, key: str, content: bytes) -> StoredObject:
        normalized_key = normalize_storage_key(key)
        path = resolve_storage_path(self.root, normalized_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredObject(key=normalized_key, size_bytes=len(content))

    def load(self, key: str) -> bytes:
        return resolve_storage_path(self.root, key).read_bytes()

    def delete(self, key: str) -> None:
        resolve_storage_path(self.root, key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return resolve_storage_path(self.root, key).exists()

