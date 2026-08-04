import sqlite3
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.database import initialize_database
from src.main import app


@pytest.fixture(autouse=True)
def preserve_application_database():
    """Run against the real SQLite schema without leaving test records behind."""
    database_path = initialize_database()
    snapshot = sqlite3.connect(":memory:")
    with sqlite3.connect(database_path) as source:
        source.backup(snapshot)
    try:
        yield
    finally:
        with sqlite3.connect(database_path) as destination:
            snapshot.backup(destination)
        snapshot.close()


@pytest_asyncio.fixture
async def client(preserve_application_database):
    """Async HTTP client for testing API endpoints."""
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
