from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

# pool_size muss die erwartete Anzahl gleichzeitiger sync Endpoints übersteigen
# (Dashboard feuert 12+ parallele Requests). pool_timeout wird gesenkt, damit
# Pool-Contention schnell fehlschlägt statt den Event-Loop 30s zu blockieren.
# SQLite nutzt SingletonThreadPool und akzeptiert keine QueuePool-Parameter,
# daher werden diese nur für produktive Engines (PostgreSQL etc.) gesetzt.
_is_sqlite = settings.database_url.startswith("sqlite")

_pool_kwargs = (
    {}
    if _is_sqlite
    else {
        "pool_size": 20,
        "max_overflow": 10,
        "pool_timeout": 10,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
)

engine = create_engine(settings.database_url, **_pool_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
