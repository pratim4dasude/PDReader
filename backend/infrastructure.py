from dataclasses import dataclass

import redis
from sqlalchemy import create_engine, text

from config import settings


@dataclass
class ServiceCheck:
    name: str
    ok: bool
    detail: str


def check_postgres() -> ServiceCheck:
    try:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return ServiceCheck("postgres", True, "connected")
    except Exception as exc:
        return ServiceCheck("postgres", False, str(exc))


def check_redis() -> ServiceCheck:
    try:
        client = redis.from_url(settings.redis_url)
        client.ping()
        return ServiceCheck("redis", True, "connected")
    except Exception as exc:
        return ServiceCheck("redis", False, str(exc))


def check_infrastructure() -> list[ServiceCheck]:
    return [check_postgres(), check_redis()]


if __name__ == "__main__":
    for check in check_infrastructure():
        status = "ok" if check.ok else "error"
        print(f"{check.name}: {status} - {check.detail}")
