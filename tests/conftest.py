import sqlite3
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.database import initialize_database
from src.main import app
from src.runtime import LocalRuntime
from src.vision.adapters.mock import MockVisionEngine


@pytest.fixture(autouse=True)
def preserve_application_database():
    """Run against the real SQLite schema without leaving test records behind."""
    database_path = initialize_database()
    snapshot = sqlite3.connect(":memory:")
    with sqlite3.connect(database_path) as source:
        source.backup(snapshot)
        source.execute("UPDATE cameras SET is_active = 0, vision_enabled = 0")
        source.commit()
    try:
        yield
    finally:
        with sqlite3.connect(database_path) as destination:
            snapshot.backup(destination)
        snapshot.close()


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
