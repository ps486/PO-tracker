from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite:///./po_tracker.db"

    SECRET_KEY: str = "insecure-dev-key-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/auth/gmail/callback"
    GMAIL_QUERY: str = "label:po-tracker newer_than:7d"
    GMAIL_POLL_INTERVAL_SECONDS: int = 300

    GEMINI_API_KEY: str = ""
    # Configurable via the Settings screen too - update this if Google
    # retires this model id (check aistudio.google.com for current names).
    AI_MODEL: str = "gemini-2.0-flash"

    CLASSIFICATION_CONFIDENCE_THRESHOLD: float = 0.85
    MATCHING_CONFIDENCE_THRESHOLD: float = 0.90
    FIELD_CONFIDENCE_THRESHOLD: float = 0.80

    ATTACHMENT_STORAGE_DIR: str = "./data/attachments"

    ENVIRONMENT: str = "development"


settings = Settings()
