import io
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.routes.documents import upload_documents
from config import settings
from models.user import User


class FakeAsyncSession:
    def __init__(self) -> None:
        self.added = []
        self.commit_called = False

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.commit_called = True


class FakeUploadFile:
    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._stream = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def _build_upload_file(filename: str, size_bytes: int) -> FakeUploadFile:
    pdf_header = b"%PDF-1.4\n/Type /Page\n"
    return FakeUploadFile(filename=filename, data=pdf_header + (b"a" * (size_bytes - len(pdf_header))))


@pytest.fixture
def current_user() -> User:
    return User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="upload-limit@example.com",
        password_hash="hashed-password",
        role="user",
        is_active=True,
        email_verified=True,
    )


@pytest.fixture
def fake_encryption(monkeypatch):
    async def _encrypt_file(input_path: Path, output_path: Path) -> None:
        output_path = Path(output_path)
        output_path.write_bytes(Path(input_path).read_bytes())

    monkeypatch.setattr(
        "services.encryption.encryption_service.encrypt_file",
        _encrypt_file,
    )


@pytest.mark.asyncio
async def test_upload_accepts_file_just_below_20mb(tmp_path, monkeypatch, current_user, fake_encryption):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 20)

    db = FakeAsyncSession()
    file_size = (20 * 1024 * 1024) - 1
    upload_file = _build_upload_file("below-limit.pdf", file_size)

    response = await upload_documents(
        files=[upload_file],
        document_types=None,
        document_labels=None,
        current_user=current_user,
        db=db,
    )

    assert len(response) == 1
    assert response[0].file_size_bytes == file_size
    assert db.commit_called is True
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_upload_rejects_file_just_above_20mb(tmp_path, monkeypatch, current_user, fake_encryption):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 20)

    db = FakeAsyncSession()
    upload_file = _build_upload_file("above-limit.pdf", (20 * 1024 * 1024) + 1)

    with pytest.raises(HTTPException) as exc:
        await upload_documents(
            files=[upload_file],
            document_types=None,
            document_labels=None,
            current_user=current_user,
            db=db,
        )

    assert exc.value.status_code == 413
    assert "exceeds maximum allowed size of 20MB" in exc.value.detail
    assert db.commit_called is False
    assert len(db.added) == 0


@pytest.mark.asyncio
async def test_multi_file_upload_with_one_oversize_has_no_partial_commit(
    tmp_path, monkeypatch, current_user, fake_encryption
):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 20)

    db = FakeAsyncSession()
    files = [
        _build_upload_file("small.pdf", (1024 * 1024) + 5),
        _build_upload_file("too-large.pdf", (20 * 1024 * 1024) + 1),
    ]

    with pytest.raises(HTTPException) as exc:
        await upload_documents(
            files=files,
            document_types=None,
            document_labels=None,
            current_user=current_user,
            db=db,
        )

    assert exc.value.status_code == 413
    assert "too-large.pdf" in exc.value.detail
    assert db.commit_called is False
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_upload_rejects_excess_file_count_before_storage(tmp_path, monkeypatch, current_user, fake_encryption):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "MAX_UPLOAD_FILES", 2)
    db = FakeAsyncSession()

    with pytest.raises(HTTPException) as exc:
        await upload_documents(
            files=[_build_upload_file(f"{number}.pdf", 128) for number in range(3)],
            document_types=None,
            document_labels=None,
            current_user=current_user,
            db=db,
        )
    assert exc.value.status_code == 413
    assert not db.added
