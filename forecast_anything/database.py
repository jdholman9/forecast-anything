from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from forecast_anything.models import Base


def _enable_sqlite_fk(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(db_path: str | Path = "forecasts.db"):
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    event.listen(engine, "connect", _enable_sqlite_fk)
    return engine


def create_tables(engine):
    Base.metadata.create_all(engine)


def get_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)
