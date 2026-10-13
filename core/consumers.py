from channels.generic.websocket import AsyncWebsocketConsumer


class EchoConsumer(AsyncWebsocketConsumer):
    async def receive(self, text_data=None, bytes_data=None):
        if text_data is not None:
            await self.send(text_data=text_data)
        elif bytes_data is not None:
            await self.send(bytes_data=bytes_data)
