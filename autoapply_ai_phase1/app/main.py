from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.db import Base, engine
from app import models  # ensures models are registered
from app.routers import jobs, resumes, inspections


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(resumes.router)
app.include_router(jobs.router)
app.include_router(inspections.router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": settings.app_name}
