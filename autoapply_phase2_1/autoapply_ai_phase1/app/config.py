from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AutoApply AI"
    database_url: str = "sqlite:///./autoapply.db"
    upload_dir: Path = Path("./data/resumes")
    max_upload_mb: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
