from functools import lru_cache
from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: SecretStr
    openai_api_key: SecretStr
    database_url_admin: str
    database_url_agent: str
    database_url_history: str
    chat_model: str = 'gemini-3.5-flash-lite'
    embedding_model: str = 'text-embedding-3-small'
    judge_model: str = 'gpt-5.6-luna'
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = Path("data")

@lru_cache
def get_settings() -> Settings:
    return Settings()