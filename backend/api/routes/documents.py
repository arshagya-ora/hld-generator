"""
Documents API Routes
Upload, list, and manage documents
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from pathlib import Path
import uuid
import aiofiles
import mimetypes
import re
import zipfile
from datetime import datetime, timezone
import logging

from database import get_db
from schemas.document import (
    DocumentUploadResponse,
    DocumentResponse,
    DocumentListResponse,
    DocumentTypeUpdateRequest
)
from models.document import Document
from models.user import User
from auth.dependencies import get_current_active_user
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])

MAX_UPLOAD_PAGES = 50


def get_file_size_mb(size_bytes: int) -> float:
    """Convert bytes to MB"""
    return round(size_bytes / (1024 * 1024), 2)


def get_document_page_count(file_path: Path, file_ext: str) -> int:
    """Read page count for supported upload types."""
    if file_ext == ".pdf":
        content = file_path.read_bytes()
        page_count = len(re.findall(rb"/Type\s*/Page(?!s)\b", content))
        if page_count < 1:
            raise ValueError("Could not read PDF page count")
        return page_count

    if file_ext in {".png", ".jpg", ".jpeg"}:
        return 1

    if file_ext == ".pptx":
        with zipfile.ZipFile(file_path) as archive:
            return len([
                name for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ])

    if file_ext == ".docx":
        with zipfile.ZipFile(file_path) as archive:
            try:
                app_metadata = archive.read("docProps/app.xml").decode("utf-8", errors="ignore")
            except KeyError as exc:
                raise ValueError("Could not read document page count") from exc

        match = re.search(r"<Pages>(\d+)</Pages>", app_metadata)
        if not match:
            raise ValueError("Could not read document page count")
        return int(match.group(1))

    raise ValueError("Page count validation is not supported for this file type")


@router.post("/upload", response_model=List[DocumentUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_documents(
    files: List[UploadFile] = File(..., description="Documents to upload"),
    document_types: Optional[List[str]] = Form(None, description="Document types (PID, RD, DIAGRAM, OTHER)"),
    document_labels: Optional[List[str]] = Form(None, description="Document labels"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload multiple documents

    - Supports multi-file upload
    - Validates file type and page count
    - Stores files with encryption (TODO)
    - Returns document metadata

    Accepted file types: .docx, .pptx, .pdf, .png, .jpg, .jpeg
    Max document length: 50 pages per file
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided"
        )

    if len(files) > settings.MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Too many files; maximum is {settings.MAX_UPLOAD_FILES}",
        )

    # Validate file count matches types/labels if provided
    if document_types and len(document_types) != len(files):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Number of document types must match number of files"
        )

    if document_labels and len(document_labels) != len(files):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Number of document labels must match number of files"
        )

    # Create storage directory if it doesn't exist
    storage_path = Path(settings.STORAGE_PATH) / "documents" / str(current_user.tenant_id)
    storage_path.mkdir(parents=True, exist_ok=True)

    uploaded_documents = []

    from services.encryption import encryption_service

    for idx, file in enumerate(files):
        # Validate file type FIRST (cheap check, before reading content)
        allowed_extensions = {".docx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg"}
        file_ext = Path(file.filename).suffix.lower()

        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type '{file_ext}' not allowed. Allowed types: {', '.join(allowed_extensions)}"
            )

        # Stream file to disk in chunks to avoid holding entire file in memory.
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        file_path = storage_path / unique_filename
        file_size = 0
        chunk_size = 256 * 1024  # 256KB chunks

        # Write to a temp file first, then encrypt the whole thing
        import tempfile, os
        temp_fd, temp_path = tempfile.mkstemp(suffix=file_ext, dir=str(storage_path))
        os.close(temp_fd)
        temp_path = Path(temp_path)

        try:
            async with aiofiles.open(temp_path, 'wb') as f:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    file_size += len(chunk)
                    if file_size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File '{file.filename}' exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB",
                        )
                    await f.write(chunk)

            try:
                page_count = get_document_page_count(temp_path, file_ext)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Could not validate page count for '{file.filename}'. {exc}"
                ) from exc

            if page_count > MAX_UPLOAD_PAGES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File '{file.filename}' has {page_count} pages and exceeds the maximum allowed {MAX_UPLOAD_PAGES} pages"
                )

            # Encrypt the temp file and write to final path
            await encryption_service.encrypt_file(temp_path, file_path)
        finally:
            # Always clean up temp file
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

        # Get MIME type
        mime_type, _ = mimetypes.guess_type(file.filename)

        # Get document type and label
        doc_type = document_types[idx] if document_types else "OTHER"
        doc_label = document_labels[idx] if document_labels else file.filename

        # Create document record
        document = Document(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            filename=unique_filename,
            original_filename=file.filename,
            file_size_bytes=file_size,
            mime_type=mime_type,
            storage_path=str(file_path),
            document_type=doc_type,
            document_label=doc_label,
            uploaded_at=datetime.now(timezone.utc)
        )

        db.add(document)
        await db.flush()

        uploaded_documents.append(DocumentUploadResponse(
            id=document.id,
            filename=document.filename,
            original_filename=document.original_filename,
            file_size_bytes=document.file_size_bytes,
            mime_type=document.mime_type,
            document_type=document.document_type,
            document_label=document.document_label,
            uploaded_at=document.uploaded_at
        ))

    await db.commit()

    return uploaded_documents


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = 1,
    page_size: int = 20,
    document_type: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List user's documents

    - Paginated results
    - Filter by document type
    - Returns document metadata
    """
    # Validate pagination
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    # Build query
    query = select(Document).where(
        Document.tenant_id == current_user.tenant_id,
        Document.user_id == current_user.id
    )

    if document_type:
        query = query.where(Document.document_type == document_type)

    # Get total count
    count_query = select(func.count()).select_from(Document).where(
        Document.tenant_id == current_user.tenant_id,
        Document.user_id == current_user.id
    )
    if document_type:
        count_query = count_query.where(Document.document_type == document_type)

    result = await db.execute(count_query)
    total_count = result.scalar()

    # Get paginated results
    query = query.order_by(Document.uploaded_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    documents = result.scalars().all()

    # Convert to response models
    document_responses = []
    for doc in documents:
        document_responses.append(DocumentResponse(
            id=doc.id,
            filename=doc.filename,
            original_filename=doc.original_filename,
            file_size_bytes=doc.file_size_bytes,
            file_size_mb=get_file_size_mb(doc.file_size_bytes),
            mime_type=doc.mime_type,
            document_type=doc.document_type,
            document_label=doc.document_label,
            cognee_dataset_name=doc.cognee_dataset_name,
            uploaded_at=doc.uploaded_at,
            created_at=doc.created_at
        ))

    total_pages = (total_count + page_size - 1) // page_size

    return DocumentListResponse(
        documents=document_responses,
        count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get document details by ID"""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == current_user.tenant_id,
            Document.user_id == current_user.id
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        original_filename=document.original_filename,
        file_size_bytes=document.file_size_bytes,
        file_size_mb=get_file_size_mb(document.file_size_bytes),
        mime_type=document.mime_type,
        document_type=document.document_type,
        document_label=document.document_label,
        cognee_dataset_name=document.cognee_dataset_name,
        uploaded_at=document.uploaded_at,
        created_at=document.created_at
    )


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document_type(
    document_id: uuid.UUID,
    update: DocumentTypeUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update document type and label"""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == current_user.tenant_id,
            Document.user_id == current_user.id
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    document.document_type = update.document_type
    if update.document_label:
        document.document_label = update.document_label

    await db.commit()
    await db.refresh(document)

    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        original_filename=document.original_filename,
        file_size_bytes=document.file_size_bytes,
        file_size_mb=get_file_size_mb(document.file_size_bytes),
        mime_type=document.mime_type,
        document_type=document.document_type,
        document_label=document.document_label,
        cognee_dataset_name=document.cognee_dataset_name,
        uploaded_at=document.uploaded_at,
        created_at=document.created_at
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a document (blocked if used by an active job)"""
    from models.job import Job, JobDocument

    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == current_user.tenant_id,
            Document.user_id == current_user.id
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # Check if document is linked to any active (queued/running) jobs
    active_job_result = await db.execute(
        select(func.count()).select_from(JobDocument)
        .join(Job, Job.id == JobDocument.job_id)
        .where(
            JobDocument.document_id == document_id,
            Job.status.in_(["queued", "running"])
        )
    )
    active_job_count = active_job_result.scalar()

    if active_job_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete document: it is used by {active_job_count} active job(s). "
                   f"Wait for jobs to complete or cancel them first."
        )

    # Delete file from disk
    try:
        file_path = Path(document.storage_path)
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        logger.error(f"Error deleting file {document.storage_path}: {e}")

    await db.delete(document)
    await db.commit()
