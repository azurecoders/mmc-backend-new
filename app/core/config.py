from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "MMC Hospital Management System"
    API_V1_STR: str = "/api/v1"
    
    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "mdreader"
    POSTGRES_PASSWORD: str = "mdreader"
    POSTGRES_DB: str = "hospital_db"
    DATABASE_URL: Optional[str] = None

    # JWT Authentication
    JWT_SECRET_KEY: str = "super-secret-jwt-key-for-hospital-management-system-2026-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Google AI Studio / Gemini Config
    GOOGLE_AI_API_KEY: Optional[str] = None
    AI_RECOMMENDER_MODEL: str = "gemma-4-26b-a4b-it"

    # OpenAI Config (Token-efficient GPT-4o-mini for Prescription Explanation)
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Initial Superadmin Seed
    FIRST_SUPERADMIN_EMAIL: str = "admin@hospital.com"
    FIRST_SUPERADMIN_PASSWORD: str = "Admin@123456"
    FIRST_SUPERADMIN_NAME: str = "System Super Admin"

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["*"]

    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="allow",
    )

settings = Settings()
