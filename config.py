from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    gmail_credentials_file: str = "credentials/credentials.json"
    gmail_token_file: str = "credentials/token.json"
    gmail_scopes: list[str] = [
        "https://www.googleapis.com/auth/gmail.modify",
    ]
    max_unread_fetch: int = 20
    api_base_url: str = "http://localhost:8000"


settings = Settings()
BASE_DIR = Path(__file__).parent
