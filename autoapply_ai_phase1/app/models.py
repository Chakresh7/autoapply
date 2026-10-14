from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


def utc_now():
    return datetime.now(timezone.utc)


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class JobURL(Base):
    __tablename__ = "job_urls"
    __table_args__ = (UniqueConstraint("normalized_url", name="uq_job_normalized_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(Text, index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class JobInspection(Base):
    # Separate table preserves compatibility with the existing local SQLite schema.
    __tablename__ = "job_inspections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_url_id: Mapped[int] = mapped_column(ForeignKey("job_urls.id", ondelete="CASCADE"), index=True)
    inspection_status: Mapped[str] = mapped_column(String(40), default="completed")
    page_title: Mapped[str] = mapped_column(String(500), default="")
    final_url: Mapped[str] = mapped_column(Text, default="")
    ats_platform: Mapped[str] = mapped_column(String(80), default="unknown")
    job_title: Mapped[str] = mapped_column(String(500), default="")
    company_name: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    employment_type: Mapped[str] = mapped_column(String(120), default="")
    work_mode: Mapped[str] = mapped_column(String(120), default="")
    salary_text: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    requirements_json: Mapped[str] = mapped_column(Text, default="[]")
    detected_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    error_message: Mapped[str] = mapped_column(Text, default="")
    inspected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)