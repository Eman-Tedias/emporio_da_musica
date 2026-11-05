from functools import lru_cache
from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LUNA = 'gpt-5.6-luna'
FLASH_LITE = 'gemini-3.5-flash-lite'

class Settings(BaseSettings):
    gemini_api_key: SecretStr
    openai_api_key: SecretStr
    database_url_admin: str
    database_url_agent: str
    database_url_history: str
    embedding_model: str = 'text-embedding-3-small'
    judge_model: str = LUNA
    guardrail_model: str = LUNA
    guardrail_fallback_model: str = FLASH_LITE
    parser_model: str = FLASH_LITE
    parser_fallback_model: str = LUNA
    data_agent_model: str = LUNA
    data_agent_fallback_model: str = FLASH_LITE
    composer_model: str = FLASH_LITE
    composer_fallback_model: str = LUNA
    llm_timeout_seconds: float = 15
    max_tool_steps: int = 5
    max_failed_order_lookups: int = 3
    history_turns: int = 6
    max_messages_per_minute: int = 20
    session_idle_ttl_seconds: int = 3600
    trace_file: str = "logs/traces.jsonl"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    data_dir: Path = Path("data")

@lru_cache
def get_settings() -> Settings:
    return Settings()