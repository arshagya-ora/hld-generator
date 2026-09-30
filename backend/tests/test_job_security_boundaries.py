import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routes.jobs import (
    download_available,
    download_job,
    public_error_message,
    public_job_metadata,
    recover_stale_jobs,
)
from config import settings
from models.base import Base
from models.job import Job
from models.user import User
from services.job_artifacts import job_output_dir


@pytest.mark.asyncio
async def test_download_stays_in_the_job_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", str(tmp_path / "outputs"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection, tables=[User.__table__, Job.__table__]
            )
        )

    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    user_a = User(id=uuid.uuid4(), tenant_id=tenant_a, email="a@example.com", password_hash="hash", role="admin")
    user_b = User(id=uuid.uuid4(), tenant_id=tenant_b, email="b@example.com", password_hash="hash", role="admin")
    first = Job(tenant_id=tenant_a, user_id=user_a.id, product_id="same", status="completed")
    second = Job(tenant_id=tenant_b, user_id=user_b.id, product_id="same", status="completed")
    first.id, second.id = uuid.uuid4(), uuid.uuid4()

    first_dir, second_dir = job_output_dir(first.id), job_output_dir(second.id)
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    first_file, second_file = first_dir / "HLD_same.docx", second_dir / "HLD_same.docx"
    first_file.write_bytes(b"tenant A")
    second_file.write_bytes(b"tenant B")
    first.output_path, second.output_path = str(first_file), str(second_file)

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([user_a, user_b, first, second])
        await db.commit()
        response = await download_job(first.id, current_user=user_a, db=db)
        assert Path(response.path).read_bytes() == b"tenant A"
        assert download_available(first)
        assert not download_available(Job(id=first.id, status="completed", output_path=str(second_file)))
        with pytest.raises(HTTPException) as denied:
            await download_job(second.id, current_user=user_a, db=db)
        assert denied.value.status_code == 404

        first.output_path = str(second_file)
        await db.commit()
        with pytest.raises(HTTPException) as wrong_path:
            await download_job(first.id, current_user=user_a, db=db)
        assert wrong_path.value.status_code == 404
    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_recovery_only_mutates_admins_tenant(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection, tables=[User.__table__, Job.__table__]
            )
        )
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    admin = User(id=uuid.uuid4(), tenant_id=tenant_a, email="admin@example.com", password_hash="hash", role="admin")
    colleague = User(id=uuid.uuid4(), tenant_id=tenant_a, email="colleague@example.com", password_hash="hash", role="user")
    super_admin = User(id=uuid.uuid4(), tenant_id=tenant_a, email="super@example.com", password_hash="hash", role="super_admin")
    foreign_user = User(id=uuid.uuid4(), tenant_id=tenant_b, email="foreign@example.com", password_hash="hash", role="admin")
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    own_job = Job(id=uuid.uuid4(), tenant_id=tenant_a, user_id=admin.id, product_id="same", status="running", created_at=old)
    colleague_job = Job(id=uuid.uuid4(), tenant_id=tenant_a, user_id=colleague.id, product_id="same", status="running", created_at=old)
    foreign_job = Job(id=uuid.uuid4(), tenant_id=tenant_b, user_id=foreign_user.id, product_id="same", status="running", created_at=old)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([admin, colleague, super_admin, foreign_user, own_job, colleague_job, foreign_job])
        await db.commit()
        result = await recover_stale_jobs(current_user=admin, db=db)
        assert set(result["recovered_job_ids"]) == {str(own_job.id), str(colleague_job.id)}
        jobs = (await db.execute(select(Job))).scalars().all()
        assert {job.id: job.status for job in jobs} == {
            own_job.id: "failed",
            colleague_job.id: "failed",
            foreign_job.id: "running",
        }
        assert "running" in own_job.error_message
        global_result = await recover_stale_jobs(current_user=super_admin, db=db)
        assert global_result["recovered_job_ids"] == [str(foreign_job.id)]
    await engine.dispose()


def test_job_response_fields_omit_internal_error_details():
    internal_path = "C:/private/output/secret.docx"
    assert internal_path not in public_error_message("failed", internal_path)
    metadata = {
        "cognee_dataset": "internal-index",
        "duration_seconds": 10,
        "pipeline_log": [
            {"stage": "failed", "message": internal_path, "timestamp": "now"},
        ],
    }
    public = public_job_metadata(metadata)
    assert "cognee_dataset" not in public
    assert internal_path not in str(public)
    assert public["duration_seconds"] == 10
