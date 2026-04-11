from pathlib import Path

import pytest

from app.storage.local import LocalStorageProvider
from app.storage.paths import UnsafeStorageKey, normalize_storage_key, sanitize_filename


@pytest.mark.parametrize(
    ("raw_key", "expected"),
    [
        ("jobs/123/resume.pdf", "jobs/123/resume.pdf"),
        ("./jobs//123/./resume.pdf", "jobs/123/resume.pdf"),
        ("jobs\\123\\resume.pdf", "jobs/123/resume.pdf"),
    ],
)
def test_normalize_storage_key_accepts_safe_relative_keys(raw_key: str, expected: str) -> None:
    assert normalize_storage_key(raw_key) == expected


@pytest.mark.parametrize(
    "raw_key",
    [
        "",
        "/etc/passwd",
        "../secret.txt",
        "jobs/../../secret.txt",
    ],
)
def test_normalize_storage_key_rejects_unsafe_keys(raw_key: str) -> None:
    with pytest.raises(UnsafeStorageKey):
        normalize_storage_key(raw_key)


def test_sanitize_filename_keeps_safe_name() -> None:
    assert sanitize_filename("../Mark Resume (final).pdf") == "Mark Resume _final_.pdf"


def test_local_storage_roundtrip_uses_relative_key(tmp_path: Path) -> None:
    storage = LocalStorageProvider(tmp_path)

    stored = storage.save("jobs/abc/resume.pdf", b"resume-bytes")

    assert stored.key == "jobs/abc/resume.pdf"
    assert stored.size_bytes == len(b"resume-bytes")
    assert storage.exists(stored.key)
    assert storage.load(stored.key) == b"resume-bytes"
    assert (tmp_path / "jobs" / "abc" / "resume.pdf").read_bytes() == b"resume-bytes"

    storage.delete(stored.key)

    assert not storage.exists(stored.key)


def test_local_storage_blocks_traversal(tmp_path: Path) -> None:
    storage = LocalStorageProvider(tmp_path)

    with pytest.raises(UnsafeStorageKey):
        storage.save("../outside.txt", b"nope")

