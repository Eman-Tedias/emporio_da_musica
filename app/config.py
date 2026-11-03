from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: SecretStr
    openai_api_key: SecretStr
    database_url_admin: str
    database_url_agente: str
    database_url_historico: str
    chat_model: str = 'gemini-3.5-flash-lite'
    embedding_model: str = 'text-embedding-3-small'
    judge_model: str = 'gpt-5.6-luna'
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()