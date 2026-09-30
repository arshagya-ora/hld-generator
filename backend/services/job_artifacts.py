"""Resolve generated artifacts within the directory owned by a job."""

from pathlib import Path
from uuid import UUID

from config import settings


def job_output_dir(job_id: UUID) -> Path:
    """Return the dedicated output directory for a job."""
    return Path(settings.OUTPUT_DIR).resolve() / str(job_id)


def owned_output_path(job_id: UUID, recorded_path: str) -> Path | None:
    """Return a recorded artifact only when it stays inside this job's output directory."""
    job_dir = job_output_dir(job_id)
    candidate = Path(recorded_path).resolve()
    if candidate.parent != job_dir or candidate.suffix.lower() not in {".docx", ".md", ".pdf"}:
        return None
    return candidate
