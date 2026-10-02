"""aemeath-spirit 兼容的 WebSocket 消息格式，使用统一 Qt 控制桥。"""
import asyncio
import json

from websockets.legacy.server import serve
from websockets.exceptions import ConnectionClosed
from src.core.control_bridge import decode_json


class WebSocketServer:
    def __init__(self, bridge, host="127.0.0.1", port=18765):
        self.bridge = bridge
        self.host, self.port = host, port
        self.clients = set()
        self.server = None

    async def start(self):
        self.server = await serve(self._handle_client, self.host, self.port, max_size=65536,
                                  ping_interval=20, ping_timeout=10)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def _handle_client(self, websocket, path):
        if path != "/sprite":
            await websocket.close(code=1008, reason="Use /sprite")
            return
        self.clients.add(websocket)
        try:
            async for message in websocket:
                try:
                    if not isinstance(message, str):
                        raise ValueError("需要 JSON 文本消息")
                    command = decode_json(message)
                except (ValueError, UnicodeError):
                    result = self.bridge.error("JSON 格式无效", "invalid_json")
                else:
                    result = await self.bridge.execute(command)
                    if result["type"] == "status":
                        result["data"]["connected_clients"] = len(self.clients)
                await websocket.send(json.dumps(result, ensure_ascii=False, allow_nan=False))
        except (ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            self.clients.discard(websocket)

    async def broadcast(self, kind, data):
        if self.clients:
            message = json.dumps({"type": kind, "data": data}, ensure_ascii=False, allow_nan=False)
            await asyncio.gather(*(client.send(message) for client in tuple(self.clients)), return_exceptions=True)
