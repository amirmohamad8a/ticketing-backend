from django.db import connections

import pytest
from asgiref.sync import sync_to_async


@pytest.fixture(autouse=True)
async def _close_db_connections():
    yield
    await sync_to_async(connections.close_all, thread_sensitive=True)()
