from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    gmail_credentials_file: str = "credentials/credentials.json"
    gmail_token_file: str = "credentials/token.json"
    gmail_scopes: list[str] = [
        "https://www.googleapis.com/auth/gmail.modify",
    ]
    max_unread_fetch: int = 20
    api_base_url: str = "http://localhost:8000"


settings = Settings()
BASE_DIR = Path(__file__).parent
