from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_IS_SQLITE = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _IS_SQLITE else {}
engine = create_engine(settings.database_url, connect_args=connect_args)

if _IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        """WAL 允许读写并发；busy_timeout 避免瞬时锁冲突直接抛 database is locked。"""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app.models import entities  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_columns(engine)


def ensure_columns(db_engine) -> None:
    """Lightweight migration: add new columns to pre-existing SQLite tables."""
    additions = {
        "assessments": [
            ("rectification_status", "VARCHAR(32)"),
            ("rectification_note", "TEXT"),
            ("rectification_score", "FLOAT"),
            ("rectification_analysis_json", "TEXT"),
            ("rectification_meta_json", "TEXT"),
            ("rectified_at", "DATETIME"),
            ("review_reasons_json", "TEXT"),
            ("human_review_json", "TEXT"),
            ("risk_result_json", "TEXT"),
            ("evidence_judge_json", "TEXT"),
            ("ensemble_judge_json", "TEXT"),
            ("multi_model_json", "TEXT"),
            ("disagreement_json", "TEXT"),
        ],
        "assessment_images": [("image_kind", "VARCHAR(32)")],
    }
    with db_engine.connect() as conn:
        for table, columns in additions.items():
            existing = {
                row[1]
                for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            for name, ddl in columns:
                if name not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                    )
            if table == "assessment_images" and "image_kind" in existing:
                conn.exec_driver_sql(
                    "UPDATE assessment_images SET image_kind='original' "
                    "WHERE image_kind IS NULL OR image_kind=''"
                )
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
