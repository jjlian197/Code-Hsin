"""连接现有 Hermes 桌面服务；按登记端口发现，不修改 Agent 配置。"""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import aiohttp


def local_url(value, schemes=("http", "https")):
    url = urlparse(value)
    if url.scheme not in schemes or url.hostname not in ("localhost", "127.0.0.1", "::1") or url.username or url.password:
        raise ValueError("本地后端地址需要 localhost 或回环 IP，且不能包含账号密码")
    return value.rstrip("/")


class HermesBridge:
    def __init__(self, config):
        self.config = config
        self.stored_session = None
        self.runtime_session = None
        self.endpoint = None

    async def connect(self, session):
        base = self.config.get("url", "").strip()
        if not base:
            root = Path(self.config["home"]).expanduser()
            try:
                rows = json.loads((root / "spawn-ledger.json").read_text(encoding="utf8"))
            except (OSError, ValueError) as exc:
                raise RuntimeError("未找到 Hermes 服务，请先打开 Hermes 桌面应用，或在连接设置中填写地址") from exc
            candidates = [r for r in rows if r.get("purpose") in ("serve", "dashboard") and not r.get("isolated")
                          and r.get("host") in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "::")
                          and type(r.get("port")) is int and 1 <= r["port"] <= 65535]
            if not candidates:
                raise RuntimeError("Hermes 桌面服务尚未启动")
            row = max(candidates, key=lambda r: r.get("registered_at", 0))
            base = f"http://127.0.0.1:{row['port']}"
        base = local_url(base)
        self.endpoint = base
        async with session.get(base + "/", timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            html = await response.text()
        match = re.search(r'window\.__HERMES_SESSION_TOKEN__\s*=\s*("[^"\r\n]+")', html)
        token = self.config.get("token") or (json.loads(match[1]) if match else None)
        if not token:
            raise RuntimeError("Hermes 需要认证，请在连接设置中填写桌面会话凭据")
        # 与安装版桌面客户端使用同一握手方式，凭据只保留在内存。
        url = base.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        return await session.ws_connect(url + "/api/ws?token=" + quote(token, safe=""), max_msg_size=8 * 1024 * 1024)

    @staticmethod
    async def frames(ws):
        try:
            message = await ws.receive(timeout=20)
        except asyncio.TimeoutError:
            await ws.send_json({"jsonrpc": "2.0", "id": "heartbeat", "method": "gateway.ping", "params": {}})
            return []
        if message.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError("Hermes 连接已中断")
        return [json.loads(line) for line in message.data.splitlines() if line.strip()]

    async def request(self, ws, method, params, pending):
        request_id = method
        await ws.send_json({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = asyncio.get_running_loop().time() + 120
        while asyncio.get_running_loop().time() < deadline:
            frames = await self.frames(ws)
            for index, frame in enumerate(frames):
                if frame.get("id") == request_id:
                    pending.extend(frames[index + 1:])
                    if frame.get("error"):
                        raise RuntimeError("Hermes：" + str(frame["error"].get("message", "请求失败")))
                    return frame["result"]
                pending.append(frame)
        raise TimeoutError("Hermes 请求超时")

    async def profiles(self):
        async with aiohttp.ClientSession() as session:
            async with await self.connect(session) as ws:
                return await self.request(ws, "profiles.list", {}, [])

    async def chat(self, text, language, on_delta):
        profile = self.config.get("profile") or "default"
        async with aiohttp.ClientSession() as session:
            async with await self.connect(session) as ws:
                pending = []
                if self.stored_session:
                    result = await self.request(ws, "session.resume", {"profile": profile, "session_id": self.stored_session}, pending)
                else:
                    result = await self.request(ws, "session.create", {"profile": profile, "source": "desktop",
                        "title": "心 · 桌面对话", "close_on_disconnect": False, "follow_profile_config": True}, pending)
                sid = result["session_id"]
                self.runtime_session = sid
                self.stored_session = result.get("stored_session_id") or self.stored_session
                instruction = "请用日语简短回答，适合语音朗读。" if language == "ja" else "请用中文简短回答，适合语音朗读。"
                complete = False
                try:
                    await self.request(ws, "prompt.submit", {"profile": profile, "session_id": sid,
                        "text": text + "\n\n【桌面对话语言】" + instruction}, pending)
                    deadline = asyncio.get_running_loop().time() + 300
                    while asyncio.get_running_loop().time() < deadline:
                        frames = pending if pending else await self.frames(ws)
                        pending = []
                        for frame in frames:
                            params = frame.get("params", {})
                            if frame.get("method") != "event" or params.get("session_id") != sid:
                                continue
                            kind, payload = params.get("type"), params.get("payload") or {}
                            if kind == "message.delta":
                                await on_delta(payload.get("text", ""))
                            elif kind == "error":
                                raise RuntimeError("Hermes：" + payload.get("message", "对话失败"))
                            elif kind == "message.complete":
                                if payload.get("status") in ("error", "interrupted") or payload.get("error"):
                                    raise RuntimeError("Hermes：" + (payload.get("error") or payload.get("failure_reason") or "回复中断"))
                                reply = payload.get("text", "")
                                if not isinstance(reply, str) or not reply.strip():
                                    raise RuntimeError("Hermes 没有返回文字回复")
                                complete = True
                                return reply.strip()
                    raise TimeoutError("Hermes 回复超时")
                finally:
                    if not complete:
                        # 只关闭本客户端创建的会话；停止后不恢复未完成的旧任务。
                        try:
                            await asyncio.wait_for(self.request(ws, "session.close",
                                {"profile": profile, "session_id": sid}, []), 2)
                        except (asyncio.TimeoutError, RuntimeError, aiohttp.ClientError):
                            pass
                        finally:
                            self.stored_session = None
                    self.runtime_session = None
