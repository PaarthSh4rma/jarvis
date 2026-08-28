from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def create_database_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///"):
        path = Path(database_url.removeprefix("sqlite:///"))
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, connect_args={"check_same_thread": False})
