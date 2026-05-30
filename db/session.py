"""Async SQLAlchemy engine + session factory.

Reads DATABASE_URL from .env. The engine is created once at import time;
session factory hands out short-lived sessions to callers.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker, # A function that builds a factory for creating sessions.   
    create_async_engine,
)
from pydantic_settings import ( 
    BaseSettings, # Like BaseModel but can read values from environment variables and .env files automatically. 
    SettingsConfigDict, # A configuration dict you assign to model_config to tell BaseSettings how to read those env vars.
)


class Settings(BaseSettings):
    database_url: str   # Loaded from DATABASE_URL env var (or .env file)
    redis_url: str      # Loaded from REDIS_URL env var (or .env file)
    groq_api_key: str   # Loaded from GROQ_API_KEY env var (or .env file)

    model_config = SettingsConfigDict(
        env_file=".env",           # Read .env at project root
        env_file_encoding="utf-8", # Text encoding of the .env file (UTF-8 is universal default).
        extra="ignore",            # Ignore env vars we don't declare here
    )

 
# This creates ONE instance, settings. At this line, .env 
# file is read and settings.database_url gets populated.
settings = Settings()  

# The engine is the long-lived connection pool. Created once at module import.
# pool of TCP connections to Postgres so we don't open a new socket on every query.
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,           # Set True to log every SQL query — useful for debugging
    pool_pre_ping=True,   # Verifies the connection is alive before reusing from pool
)

# Session factory. async_sessionmaker returns a callable — when you call SessionLocal(),
# you get a fresh AsyncSession. This pattern is called a factory.
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession, # When you create a session, use the async variant.
    expire_on_commit=False,   # After commit, loaded objects stay accessible with their values intact. No surprise refetches.
)
