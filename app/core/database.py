from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import get_settings

settings = get_settings()

# Fail promptly when the local PostgreSQL endpoint is unreachable instead of
# leaving desktop authentication waiting indefinitely for a connection.
connect_args = {"connect_timeout": 5} if settings.database_url.startswith("postgresql") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
