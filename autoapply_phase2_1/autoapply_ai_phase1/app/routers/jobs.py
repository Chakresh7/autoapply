from urllib.parse import urlsplit, urlunsplit
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import JobURL
from app.schemas import JobURLCreate, JobURLRead

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def normalize_url(url: str) -> str:
    parts = urlsplit(str(url))
    # Preserve path and query because they may identify a specific job. Remove fragments.
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", parts.query, ""))


@router.post("", response_model=JobURLRead, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobURLCreate, db: Session = Depends(get_db)):
    url = str(payload.url)
    if urlsplit(url).scheme not in {"http", "https"}:
        raise HTTPException(422, "Only HTTP(S) job URLs are accepted.")
    normalized = normalize_url(url)
    existing = db.scalar(select(JobURL).where(JobURL.normalized_url == normalized))
    if existing:
        raise HTTPException(409, detail={"message": "This job URL is already in your queue.", "job_id": existing.id})
    record = JobURL(url=url, normalized_url=normalized, status="queued")
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This job URL is already in your queue.")
    db.refresh(record)
    return record


@router.get("", response_model=list[JobURLRead])
def list_jobs(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
    return list(db.scalars(select(JobURL).order_by(JobURL.created_at.desc()).limit(limit)).all())
