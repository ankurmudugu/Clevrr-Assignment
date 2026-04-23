from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Shopify Agent API"
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    frontend_origin: str = Field(default="http://localhost:5173", alias="FRONTEND_ORIGIN")

    shopify_shop_name: str = Field(default="", alias="SHOPIFY_SHOP_NAME")
    shopify_api_version: str = Field(default="2025-04", alias="SHOPIFY_API_VERSION")
    shopify_access_token: str = Field(default="", alias="SHOPIFY_ACCESS_TOKEN")

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
