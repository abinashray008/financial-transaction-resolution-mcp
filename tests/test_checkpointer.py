"""SQLite checkpointer path isolation for the demo HITL workflow."""

from src.app.container import build_container_from_engine
from src.config.settings import PROJECT_ROOT, Settings
from src.repositories.session import build_engine
from src.workflows.checkpointer import checkpoint_path_for_engine


def test_file_engine_keeps_checkpoints_beside_the_dataset(tmp_path):
    database = tmp_path / "dataset.db"
    engine = build_engine(f"sqlite+pysqlite:///{database}")

    assert checkpoint_path_for_engine(engine) == str(tmp_path / "dataset.checkpoints.db")


def test_memory_engine_uses_an_in_memory_checkpointer():
    engine = build_engine("sqlite+pysqlite:///:memory:")

    assert checkpoint_path_for_engine(engine) == ":memory:"


def test_settings_resolve_checkpoint_path_relative_to_the_project(tmp_path):
    app_settings = Settings(_env_file=None, checkpoint_path="data/checkpoints.db")
    memory = Settings(_env_file=None, checkpoint_path=":memory:")
    absolute = Settings(_env_file=None, checkpoint_path=str(tmp_path / "paused.db"))

    assert app_settings.resolved_checkpoint_path == str(PROJECT_ROOT / "data" / "checkpoints.db")
    assert memory.resolved_checkpoint_path == ":memory:"
    assert absolute.resolved_checkpoint_path == str(tmp_path / "paused.db")


def test_container_creates_the_sqlite_checkpoint_file(engine, tmp_path):
    checkpoints = tmp_path / "paused.db"

    build_container_from_engine(engine, checkpoint_path=str(checkpoints))

    assert checkpoints.is_file()
