import uuid

from services.job_artifacts import job_output_dir, owned_output_path
from config import settings


def test_job_artifacts_are_isolated_and_legacy_paths_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", str(tmp_path))
    first_job = uuid.uuid4()
    second_job = uuid.uuid4()
    first_dir = job_output_dir(first_job)
    second_dir = job_output_dir(second_job)
    assert first_dir != second_dir

    first_dir.mkdir()
    second_dir.mkdir()
    first_file = first_dir / "HLD_same_name.docx"
    second_file = second_dir / "HLD_same_name.docx"
    first_file.write_bytes(b"first")
    second_file.write_bytes(b"second")

    assert owned_output_path(first_job, str(first_file)).read_bytes() == b"first"
    assert owned_output_path(second_job, str(second_file)).read_bytes() == b"second"
    assert owned_output_path(first_job, str(second_file)) is None
    assert owned_output_path(first_job, str(tmp_path / first_file.name)) is None
    assert owned_output_path(first_job, str(first_dir / ".." / str(second_job) / first_file.name)) is None
