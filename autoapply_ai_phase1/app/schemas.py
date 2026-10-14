from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl


class JobURLCreate(BaseModel):
    url: HttpUrl


class JobURLRead(BaseModel):
    id: int
    url: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ResumeRead(BaseModel):
    id: int
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    extracted_text_preview: str
    created_at: datetime
