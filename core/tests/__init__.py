from asgiref.sync import async_to_sync


def read_streaming_body(response):
    if not response.is_async:
        return b"".join(response)

    async def collect():
        return b"".join([chunk async for chunk in response])

    return async_to_sync(collect)()
