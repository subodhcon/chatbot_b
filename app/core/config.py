import os
from typing import List, Union
from pydantic import AnyHttpUrl, BeforeValidator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Annotated

def parse_cors(v: Union[str, List[str]]) -> List[str]:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, (list, str)):
        return v
    raise ValueError(v)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )
    
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "AI Chatbot SaaS API"
    
    # Mode Settings
    ENVIRONMENT: str = "development"

    # CORS origins
    BACKEND_CORS_ORIGINS: Annotated[
        Union[List[str], str], BeforeValidator(parse_cors)
    ] = ["http://localhost:3000"]

    # Database Settings
    DATABASE_URL: str = "sqlite:///./chatbot.db"
    
    @property
    def async_database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return url

    # Redis Settings
    REDIS_URL: str = "redis://localhost:6379/0"

    # MongoDB Settings
    MONGODB_URL: str = ""

    @field_validator("MONGODB_URL", mode="before")
    @classmethod
    def assemble_mongodb_url(cls, v: str) -> str:
        if v:
            return v
        import os
        for env_name in ["MONGODB_URI", "MONGO_URL", "MONGODB_URL"]:
            val = os.environ.get(env_name)
            if val:
                return val
        return "mongodb://localhost:27017"

    # Security & JWT Token Secrets
    JWT_SECRET_KEY: str = "supersecretchangeinproduction"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Rate Limiting (public widget message spam prevention)
    RATE_LIMIT_MAX_MESSAGES: int = 10   # max messages allowed per window
    RATE_LIMIT_WINDOW_MINUTES: int = 1  # sliding window in minutes

    # OpenAI API configuration placeholders
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    GEMINI_API_KEY: str = ""

    # Upload Directory Configuration
    UPLOAD_DIR: str = "uploads"

    # Centralized Logging Settings
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    LOG_FILE_NAME: str = "app.log"
    ERROR_LOG_FILE_NAME: str = "errors.log"
    LOG_ROTATION_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_ROTATION_BACKUP_COUNT: int = 5

settings = Settings()
