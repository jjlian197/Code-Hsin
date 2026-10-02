"""同一后台 asyncio 线程运行本地接口；退出时释放两个监听端口。"""
import asyncio
import threading

from loguru import logger

from src.core.http_server import HTTPServer
from src.core.websocket_server import WebSocketServer


class ControlServices:
    def __init__(self, bridge, config):
        ws, http = config["websocket"], config["http"]
        self.ws = WebSocketServer(bridge, ws["host"], ws["port"]) if ws["enabled"] else None
        self.http = HTTPServer(bridge, http["host"], http["port"],
                               lambda: len(self.ws.clients) if self.ws else 0) if http["enabled"] else None
        self.thread = None
        self.loop = None
        self._stop_event = None
        self._ready = threading.Event()
        self._error = None
        self._broadcast_tasks = set()

    def start(self):
        self.thread = threading.Thread(target=self._run, name="HsinControl", daemon=True)
        self.thread.start()
        if not self._ready.wait(10):
            self.stop()
            raise RuntimeError("Hsin 控制服务启动超时")
        if self._error:
            raise RuntimeError(f"Hsin 控制服务启动失败：{self._error}") from self._error
        logger.info("Hsin 本地接口已启动：{}", self.endpoints())

    def endpoints(self):
        def host(value):
            return f"[{value}]" if ":" in value else value
        return {"websocket": f"ws://{host(self.ws.host)}:{self.ws.port}/sprite" if self.ws else None,
                "http": f"http://{host(self.http.host)}:{self.http.port}" if self.http else None}

    def _run(self):
        async def run():
            self.loop = asyncio.get_running_loop()
            self._stop_event = asyncio.Event()
            try:
                if self.ws:
                    await self.ws.start()
                if self.http:
                    await self.http.start()
                self._ready.set()
                await self._stop_event.wait()
            except Exception as exc:
                self._error = exc
                self._ready.set()
            finally:
                for task in tuple(self._broadcast_tasks):
                    task.cancel()
                if self.http:
                    await self.http.stop()
                if self.ws:
                    await self.ws.stop()
        asyncio.run(run())

    def broadcast_sync(self, kind, data):
        if self.loop and self.ws and self.thread.is_alive():
            def schedule():
                if not self._stop_event.is_set():
                    task = self.loop.create_task(self.ws.broadcast(kind, data))
                    self._broadcast_tasks.add(task)
                    task.add_done_callback(self._broadcast_tasks.discard)
            try:
                self.loop.call_soon_threadsafe(schedule)
            except RuntimeError:
                pass

    def stop(self):
        if self.loop and self._stop_event and self.thread.is_alive():
            try:
                self.loop.call_soon_threadsafe(self._stop_event.set)
            except RuntimeError:
                pass
            self.thread.join(timeout=7)
            if self.thread.is_alive():
                logger.error("Hsin 控制服务未能及时退出")
