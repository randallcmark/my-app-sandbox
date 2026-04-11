from app.core.config import settings
from app.storage.base import StorageProvider
from app.storage.local import LocalStorageProvider


def get_storage_provider() -> StorageProvider:
    if settings.storage_backend == "local":
        return LocalStorageProvider(settings.local_storage_path)
    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")

