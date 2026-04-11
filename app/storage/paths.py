from pathlib import Path, PurePosixPath
from re import sub
from unicodedata import normalize


class UnsafeStorageKey(ValueError):
    pass


def normalize_storage_key(key: str) -> str:
    cleaned = key.replace("\\", "/").strip()
    path = PurePosixPath(cleaned)

    if not cleaned or path.is_absolute():
        raise UnsafeStorageKey("storage key must be a non-empty relative path")

    parts = [part for part in path.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise UnsafeStorageKey("storage key cannot contain parent directory traversal")

    if not parts:
        raise UnsafeStorageKey("storage key must contain at least one path segment")

    return str(PurePosixPath(*parts))


def resolve_storage_path(root: Path, key: str) -> Path:
    normalized_key = normalize_storage_key(key)
    root_path = root.resolve()
    candidate = (root_path / normalized_key).resolve()

    if candidate != root_path and root_path not in candidate.parents:
        raise UnsafeStorageKey("storage key escapes storage root")

    return candidate


def sanitize_filename(filename: str, default: str = "upload") -> str:
    normalized = normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.replace("\\", "/").split("/")[-1]
    normalized = sub(r"[^A-Za-z0-9._ -]+", "_", normalized).strip(" .")
    normalized = sub(r"\s+", " ", normalized)

    return normalized or default

