import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest


async def bounded_retry(send, attempts=3, base_delay=0.001):
    for attempt in range(attempts):
        try:
            return await send()
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(base_delay * 2**attempt)


@pytest.mark.asyncio
async def test_timeout_recovers_with_bounded_exponential_retry():
    send = AsyncMock(side_effect=[httpx.ReadTimeout("timeout"), httpx.ConnectError("offline"), "accepted"])
    assert await bounded_retry(send) == "accepted"
    assert send.await_count == 3


@pytest.mark.asyncio
async def test_retry_is_bounded():
    send = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
    with pytest.raises(httpx.ReadTimeout):
        await bounded_retry(send, attempts=3)
    assert send.await_count == 3
