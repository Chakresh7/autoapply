import hashlib
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.models import Resume
from app.schemas import ResumeRead
from app.services.resume_parser import extract_text

router = APIRouter(prefix="/api/v1/resumes", tags=["resumes"])
ALLOWED_EXTENSIONS = {".pdf", ".docx"}


@router.post("", response_model=ResumeRead, status_code=status.HTTP_201_CREATED)
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    original = Path(file.filename or "resume").name
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "Only PDF and DOCX resumes are supported.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if not content:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(content) > max_bytes:
        raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB limit.")

    # Extension is checked, but file content is also parsed; MIME headers alone aren't trusted.
    try:
        extracted = extract_text(original, content)
    except Exception as exc:
        raise HTTPException(422, "Could not parse this file. Try a valid PDF or DOCX.") from exc

    if not extracted:
        raise HTTPException(422, "No selectable text found. OCR support can be added in a later phase.")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    stored = f"{uuid.uuid4().hex}{suffix}"
    destination = settings.upload_dir / stored
    destination.write_bytes(content)

    record = Resume(
        original_filename=original[:255],
        stored_filename=stored,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        sha256=digest,
        extracted_text=extracted,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return ResumeRead(
        id=record.id,
        original_filename=record.original_filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        extracted_text_preview=record.extracted_text[:1200],
        created_at=record.created_at,
    )


@router.get("/{resume_id}", response_model=ResumeRead)
def get_resume(resume_id: int, db: Session = Depends(get_db)):
    record = db.get(Resume, resume_id)
    if not record:
        raise HTTPException(404, "Resume not found.")
    return ResumeRead(
        id=record.id,
        original_filename=record.original_filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        extracted_text_preview=record.extracted_text[:1200],
        created_at=record.created_at,
    )
