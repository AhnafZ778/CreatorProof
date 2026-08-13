from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings


class Base(DeclarativeBase):
    pass


@dataclass(slots=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    def session(self) -> Iterator[Session]:
        db = self.session_factory()
        try:
            yield db
        finally:
            db.close()


def build_database(settings: Settings) -> Database:
    connect_args = (
        {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    )
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return Database(engine=engine, session_factory=factory)
