"""Async Redis client.

Reads REDIS_URL from .env. The client manages its own connection pool
internally; one client serves the entire application.

db/redis_client.py uses:
- db/session.py → settings.redis_url
"""

from redis.asyncio import Redis, ConnectionPool

from db.session import settings


# Connection pool — Redis client uses this under the hood to keep
# a small number of TCP connections open and reuse them across calls.

# In Python, a leading underscore is a convention meaning "this is a private implementation detail — 
# don't import or use this from other files."
_pool: ConnectionPool = ConnectionPool.from_url(
    settings.redis_url,
    decode_responses=True,   # Redis stores everything as bytes. With this, the client auto-converts to str:
    max_connections=20,      # The pool keeps at most 20 open TCP connections to Redis.
)


# Single shared Redis client. Import this anywhere you need to read/write Redis.
redis_client: Redis = Redis(connection_pool=_pool)
