import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import JobURL, JobInspection
from app.services.job_page_inspector import inspect_job_page, UnsafeURL

router = APIRouter(prefix="/api/v1/jobs", tags=["job inspection"])


def serialize(record: JobInspection) -> dict:
    return {
        "id": record.id,
        "job_url_id": record.job_url_id,
        "inspection_status": record.inspection_status,
        "page_title": record.page_title,
        "final_url": record.final_url,
        "ats_platform": record.ats_platform,
        "job_title": record.job_title,
        "company_name": record.company_name,
        "location": record.location,
        "employment_type": record.employment_type,
        "work_mode": record.work_mode,
        "salary_text": record.salary_text,
        "description": record.description,
        "requirements": json.loads(record.requirements_json or "[]"),
        "detected_fields": json.loads(record.detected_fields_json or "[]"),
        "warnings": json.loads(record.warnings_json or "[]"),
        "error_message": record.error_message,
        "inspected_at": record.inspected_at,
    }


@router.post("/{job_id}/inspect")
async def inspect_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(JobURL, job_id)
    if not job:
        raise HTTPException(404, "Job URL not found. Add it first with POST /api/v1/jobs.")
    try:
        result = await inspect_job_page(job.url)
    except UnsafeURL as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        record = JobInspection(
            job_url_id=job.id,
            inspection_status="failed",
            final_url=job.url,
            error_message=str(exc),
            warnings_json="[]",
        )
        db.add(record)
        db.commit()
        raise HTTPException(502, str(exc))

    record = JobInspection(
        job_url_id=job.id,
        inspection_status=result["inspection_status"],
        page_title=result["page_title"],
        final_url=result["final_url"],
        ats_platform=result["ats_platform"],
        job_title=result["job_title"],
        company_name=result["company_name"],
        location=result["location"],
        employment_type=result["employment_type"],
        work_mode=result["work_mode"],
        salary_text=result["salary_text"],
        description=result["description"],
        requirements_json=json.dumps(result["requirements"], ensure_ascii=False),
        detected_fields_json=json.dumps(result["detected_fields"], ensure_ascii=False),
        warnings_json=json.dumps(result["warnings"], ensure_ascii=False),
        error_message=result["error_message"],
    )
    db.add(record)
    job.status = "inspected"
    db.commit()
    db.refresh(record)
    return serialize(record)


@router.get("/{job_id}/inspection")
def get_latest_inspection(job_id: int, db: Session = Depends(get_db)):
    job = db.get(JobURL, job_id)
    if not job:
        raise HTTPException(404, "Job URL not found.")
    record = db.scalar(
        select(JobInspection)
        .where(JobInspection.job_url_id == job_id)
        .order_by(JobInspection.inspected_at.desc(), JobInspection.id.desc())
    )
    if not record:
        raise HTTPException(404, "No inspection found. Call POST /api/v1/jobs/{job_id}/inspect first.")
    return serialize(record)
