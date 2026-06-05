from __future__ import annotations

import pytest

from content_factory.core import database


@pytest.fixture
def db_session(tmp_path):
    """Fresh file-backed SQLite session with the full schema migrated."""
    url = f"sqlite:///{(tmp_path / 'cf_test.sqlite').as_posix()}"
    database.init_database(url)
    database.create_all_tables()
    database.migrate_missing_columns()
    assert database._SessionLocal is not None  # initialized by init_database
    session = database._SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
