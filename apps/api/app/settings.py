from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    DATABASE_URL: str = Field(...)
    OPENAI_API_KEY: str = Field(...)
    OPENAI_MODEL: str = Field(default="gpt-5-mini")

    JWT_SECRET: str = Field(...)
    JWT_EXPIRES_MINUTES: int = Field(default=60*24*7)

    CORS_ORIGINS: str = Field(default="http://localhost:3000")

    CRON_TICK_TOKEN: str = Field(default="dev_tick_token")

    INSTAGRAM_USERNAME: str | None = None
    INSTAGRAM_PASSWORD: str | None = None
    FACEBOOK_PAGE_TOKEN: str | None = None
    FACEBOOK_PAGE_ID: str | None = None

    R2_ENDPOINT: str | None = None
    R2_ACCESS_KEY_ID: str | None = None
    R2_SECRET_ACCESS_KEY: str | None = None
    R2_BUCKET: str | None = None
    R2_PUBLIC_BASE_URL: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
