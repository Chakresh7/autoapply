from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import inspect, text
from app.config import settings
from app.db import Base, engine
from app import models  # ensures models are registered
from app.routers import jobs, resumes, inspections


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Small additive migration for existing local SQLite databases. Never drops data.
    if engine.dialect.name == "sqlite":
        inspector = inspect(engine)
        if "job_inspections" in inspector.get_table_names():
            existing = {col["name"] for col in inspector.get_columns("job_inspections")}
            additions = {
                "salary_min": "INTEGER NULL",
                "salary_max": "INTEGER NULL",
                "salary_currency": "VARCHAR(8) NOT NULL DEFAULT ''",
                "salary_period": "VARCHAR(20) NOT NULL DEFAULT ''",
                "job_screenshot_path": "TEXT NOT NULL DEFAULT ''",
                "application_screenshot_path": "TEXT NOT NULL DEFAULT ''",
                "application_url": "TEXT NOT NULL DEFAULT ''",
                "application_fields_json": "TEXT NOT NULL DEFAULT '[]'",
            }
            with engine.begin() as conn:
                for name, definition in additions.items():
                    if name not in existing:
                        conn.execute(text(f"ALTER TABLE job_inspections ADD COLUMN {name} {definition}"))
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(resumes.router)
app.include_router(jobs.router)
app.include_router(inspections.router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": settings.app_name}
