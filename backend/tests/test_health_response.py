import pytest
from fastapi.testclient import TestClient

import main
import database
import redis.asyncio
from celery_app import celery_app
from config import settings


@pytest.mark.asyncio
async def test_public_health_response_omits_dependency_errors(monkeypatch):
    sentinel = "sensitive-host-or-credential"

    class BrokenSession:
        async def __aenter__(self):
            raise RuntimeError(sentinel)

        async def __aexit__(self, *args):
            pass

    def broken_dependency(*args, **kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(database, "AsyncSessionLocal", BrokenSession)
    monkeypatch.setattr(redis.asyncio, "from_url", broken_dependency)
    monkeypatch.setattr(celery_app.control, "inspect", broken_dependency)

    response = await main.detailed_health_check()
    assert response["status"] != "healthy"
    assert set(response["dependencies"]) == {"database", "redis", "celery"}
    assert sentinel not in str(response)


@pytest.mark.asyncio
async def test_upload_body_limit_counts_streamed_bytes_without_content_length(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(settings, "MAX_UPLOAD_FILES", 1)

    async def consuming_app(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = main.UploadBodyLimitMiddleware(consuming_app)
    chunks = [
        {"type": "http.request", "body": b"a" * (1024 * 1024), "more_body": True},
        {"type": "http.request", "body": b"b" * (1024 * 1024 + 1), "more_body": False},
    ]
    sent = []

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    await middleware(
        {"type": "http", "path": "/api/v1/documents/upload", "headers": []},
        receive,
        send,
    )
    assert sent[0]["status"] == 413

    allowed_chunks = [{"type": "http.request", "body": b"a" * 1024, "more_body": False}]
    allowed_sent = []

    async def receive_allowed():
        return allowed_chunks.pop(0)

    async def send_allowed(message):
        allowed_sent.append(message)

    await middleware(
        {"type": "http", "path": "/api/v1/documents/upload", "headers": []},
        receive_allowed,
        send_allowed,
    )
    assert allowed_sent[0]["status"] == 200


def test_upload_body_limit_rejects_large_multipart_before_auth(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr(settings, "MAX_UPLOAD_FILES", 1)
    client = TestClient(main.app)
    response = client.post(
        "/api/v1/documents/upload",
        files={"files": ("large.pdf", b"a" * (2 * 1024 * 1024 + 1), "application/pdf")},
    )
    assert response.status_code == 413
