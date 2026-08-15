from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.database import database_connection, initialize_database
from src.main import app
from src.runtime import LocalRuntime
from src.vision.adapters.mock import MockVisionEngine


@pytest.fixture(autouse=True)
def preserve_application_database(tmp_path_factory, monkeypatch):
    """Give every test an isolated database; never open the user's application DB."""
    database_path = tmp_path_factory.mktemp("application-db") / "application.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("METRICS_COLLECTION_ENABLED", "false")
    get_settings.cache_clear()
    initialize_database()
    with database_connection() as connection:
        connection.execute("UPDATE cameras SET is_active = 0, vision_enabled = 0")
    try:
        yield database_path
    finally:
        get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(preserve_application_database, monkeypatch):
    """Async API client with native AI isolated at the application boundary."""
    monkeypatch.setattr(
        "src.main.LocalRuntime",
        lambda event_dispatcher, mock_event_frame_ids: LocalRuntime(
            vision_engine=MockVisionEngine(),
            event_dispatcher=event_dispatcher,
        ),
    )
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
def mock_llm():
    """Mock LLM to avoid calling OpenAI during tests.

    Usage in test:
        def test_something(mock_llm):
            # LLM calls will return mock response instead of hitting OpenAI
            ...
    """
    mock = AsyncMock()
    mock.ainvoke.return_value = AsyncMock(content="Mocked LLM response")
    return mock
