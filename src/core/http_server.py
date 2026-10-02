"""兼容旧 HTTP 控制路由，补充统一 /api/command 与 /health。"""
import json
from aiohttp import web
from src.core.control_bridge import decode_json


class HTTPServer:
    def __init__(self, bridge, host="127.0.0.1", port=18766, client_count=lambda: 0):
        self.bridge = bridge
        self.host, self.port = host, port
        self.client_count = client_count
        self.runner = None
        self.app = web.Application(client_max_size=65536)
        self.app.router.add_get("/health", self._status)
        self.app.router.add_get("/api/status", self._status)
        self.app.router.add_post("/api/command", self._command)
        for name in ("window", "message", "background", "expression", "motion", "physics", "model", "speak", "tts_config", "chat", "chat_config", "look_at", "parameter", "parameter_batch", "behavior", "blink", "lip_sync", "audio"):
            self.app.router.add_post("/api/" + name, self._command)

    async def start(self):
        self.runner = web.AppRunner(self.app, shutdown_timeout=1)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        self.port = self.runner.addresses[0][1]

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()

    async def _status(self, request):
        result = await self.bridge.execute({"type": "get_status"})
        if result["success"]:
            result["data"]["connected_clients"] = self.client_count()
        return web.json_response(result, status=200 if result["success"] else 503)

    async def _command(self, request):
        try:
            payload = await request.json(loads=decode_json)
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return web.json_response(self.bridge.error("JSON 格式无效", "invalid_json"), status=400)
        if request.path != "/api/command":
            payload = {"type": request.match_info.route.resource.canonical.removeprefix("/api/"), "data": payload}
        result = await self.bridge.execute(payload)
        status = 200
        if not result["success"]:
            code = result["data"]["code"]
            status = 501 if code in ("renderer_unavailable", "tts_unavailable") else 400
            if code in ("internal_error", "ui_timeout", "shutting_down"):
                status = 503
        return web.json_response(result, status=status)
