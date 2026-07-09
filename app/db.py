from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine, select

from . import config
from .models import Setting

engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Simple additive migrationer for eksisterende databaser (SQLite)."""
    from sqlalchemy import text

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(itemimage)"))}
        if "shot_key" not in cols:
            conn.execute(text("ALTER TABLE itemimage ADD COLUMN shot_key VARCHAR DEFAULT ''"))
            conn.commit()


@contextmanager
def session_scope():
    with Session(engine) as session:
        yield session


def get_setting(session: Session, key: str, default: str = "") -> str:
    row = session.get(Setting, key)
    return row.value if row else default


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        row = Setting(key=key, value=value)
    session.add(row)
    session.commit()
