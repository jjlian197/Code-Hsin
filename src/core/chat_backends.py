"""心的对话通道；直连仅聊天，本地 Agent 沿用各自已有的人设和工具。"""
import asyncio
import json
import os
import uuid

import aiohttp
import websockets

from src.core.hermes_bridge import HermesBridge, local_url
from src.core.chat_preferences import reply_instruction
from src.core.ollama_bridge import OllamaBridge

PROVIDERS = {"hermes": "Hermes · Hsin", "openclaw": "OpenClaw", "deepseek": "DeepSeek 直连", "ollama": "Qwen · 本机聊天（实验）"}
HSIN_PROMPT = """你是《鸣潮》的心（Hsin），在御者的桌面上陪伴他。称呼用户为御者，语气温柔从容，
偶尔俏皮，对日常小事怀有好奇心。回答自然、适合朗读。当前是文字直连，
没有本地 Agent 的工具权限。没有依据时不要声称看到了屏幕、读了文件、操作了软件或记得未知往事。
不输出动作旁白、思考过程或 Markdown。"""


async def read_sse(content, on_delta, *, on_limit=None):
    parts, lines, done = [], [], False

    async def consume():
        nonlocal done
        if not lines:
            return
        data = "\n".join(lines)
        lines.clear()
        if data == "[DONE]":
            done = True
            return
        frame = json.loads(data)
        if frame.get("error"):
            raise RuntimeError("对话服务返回错误")
        choices = frame.get("choices") or []
        if choices and choices[0].get("finish_reason") == "length" and on_limit:
            on_limit()
        delta = choices[0].get("delta", {}).get("content", "") if choices else ""
        if delta:
            if not isinstance(delta, str):
                raise RuntimeError("对话服务返回了无效文字")
            parts.append(delta)
            await on_delta(delta)

    async for raw in content:
        line = raw.decode("utf8").rstrip("\r\n")
        if not line:
            await consume()
            if done:
                break
        elif line.startswith("data:"):
            lines.append(line[5:].lstrip())
    await consume()
    if not done:
        raise RuntimeError("回复连接意外中断，请重试")
    text = "".join(parts).strip()
    if not text:
        raise RuntimeError("服务没有返回文字回复")
    return text


class DeepSeekBridge:
    def __init__(self, config):
        self.config, self.history = config, []
        self.warning = None

    async def chat(self, text, language, on_delta, *, reply_length="normal"):
        self.warning = None
        key = (os.environ.get("DEEPSEEK_API_KEY") or self.config.get("api_key") or "").strip()
        if not key:
            raise ValueError("请在连接设置中填写 DeepSeek API Key")
        locale = "请用日语回答。" if language == "ja" else "请用中文回答。"
        payload = {"model": self.config.get("model", "deepseek-v4-flash"),
            "messages": [{"role": "system", "content": (self.config.get("persona") or HSIN_PROMPT) + locale + reply_instruction(reply_length, language)}, *self.history,
                         {"role": "user", "content": text}],
            "stream": True, "thinking": {"type": "disabled"}, "max_tokens": {"short": 512, "normal": 1536, "detailed": 4096}[reply_length]}
        timeout = aiohttp.ClientTimeout(total=120, connect=10, sock_read=40)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post("https://api.deepseek.com/chat/completions", headers={"Authorization": "Bearer " + key}, json=payload) as response:
                if response.status != 200:
                    reasons = {401: "密钥无效", 402: "账户余额不足", 429: "请求过于频繁"}
                    raise RuntimeError(f"DeepSeek：{reasons.get(response.status, '服务暂不可用')}（{response.status}）")
                reply = await read_sse(response.content, on_delta,
                    on_limit=lambda: setattr(self, "warning", "回复达到模型生成上限，可能尚未说完；可选择详细回复或请求继续。"))
        self.history = (self.history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-12:]
        return reply


class OpenClawBridge:
    def __init__(self, config):
        self.config = config
        self.session_key = f"agent:{config.get('agent', 'hsin')}:desktop-{uuid.uuid4().hex}"

    async def _socket(self, url):
        # 仅连接已有网关，不启动或管理 OpenClaw / WSL 服务。
        try:
            return await websockets.connect(url, max_size=8 * 1024 * 1024, open_timeout=10)
        except (OSError, asyncio.TimeoutError) as error:
            raise RuntimeError("OpenClaw 本地网关未启动，请检查连接设置") from error

    async def chat(self, text, language, on_delta, *, reply_length="normal"):
        url = local_url(self.config.get("url", "ws://127.0.0.1:18789/ws"), ("ws", "wss"))
        token = os.environ.get("OPENCLAW_GATEWAY_TOKEN") or self.config.get("token")
        if not token:
            raise ValueError("请在连接设置中填写 OpenClaw 网关凭据")
        ws = await self._socket(url)
        try:
            await asyncio.wait_for(ws.recv(), 15)
            async def request(method, params, pending):
                await ws.send(json.dumps({"type": "req", "id": method, "method": method, "params": params}))
                deadline = asyncio.get_running_loop().time() + 30
                while asyncio.get_running_loop().time() < deadline:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), 15))
                    if frame.get("id") == method and frame.get("type") == "res":
                        if not frame.get("ok"):
                            error = frame.get("error") or {}
                            reason = error.get("message", "请检查网关和 Agent 配置") if isinstance(error, dict) else "请求被拒绝"
                            raise RuntimeError("OpenClaw：" + reason)
                        return frame.get("payload", {})
                    pending.append(frame)
                raise TimeoutError("OpenClaw 请求超时")
            pending = []
            await request("connect", {"client": {"id": "gateway-client", "mode": "backend", "version": "1.0.0", "platform": "python"},
                "auth": {"token": token}, "scopes": ["operator.read", "operator.write", "operator.talk.secrets"],
                "minProtocol": 3, "maxProtocol": 4}, pending)
            await request("sessions.messages.subscribe", {"key": self.session_key}, pending)
            locale = ("请用日语回答，适合朗读。" if language == "ja" else "请用中文回答，适合朗读。") + reply_instruction(reply_length, language)
            complete = False
            try:
                await request("chat.send", {"sessionKey": self.session_key, "message": text + "\n\n【桌面对话语言】" + locale,
                    "idempotencyKey": uuid.uuid4().hex}, pending)
                last = ""
                deadline = asyncio.get_running_loop().time() + 300
                while asyncio.get_running_loop().time() < deadline:
                    frame = pending.pop(0) if pending else json.loads(await asyncio.wait_for(ws.recv(), 60))
                    if frame.get("type") != "event":
                        continue
                    data = frame.get("payload", {})
                    if data.get("sessionKey") != self.session_key:
                        continue
                    if frame.get("event") == "agent" and data.get("stream") == "assistant":
                        full = self.clean(data.get("data", {}).get("text", ""))
                        if full.startswith(last):
                            await on_delta(full[len(last):])
                        last = full
                    elif frame.get("event") == "agent" and data.get("stream") == "lifecycle" and data.get("data", {}).get("phase") == "error":
                        raise RuntimeError("OpenClaw Agent 回复失败，请检查 Agent 配置")
                    elif frame.get("event") == "chat":
                        if data.get("state") in ("error", "aborted"):
                            raise RuntimeError("OpenClaw 回复失败或已停止")
                        if data.get("state") == "final":
                            content = (data.get("message") or {}).get("content", [])
                            reply = "".join(p.get("text", "") for p in content if isinstance(p, dict)) or last
                            if not reply.strip():
                                raise RuntimeError("OpenClaw 没有返回文字回复")
                            complete = True
                            return self.clean(reply)
                raise TimeoutError("OpenClaw 回复超时")
            finally:
                if not complete:
                    await ws.send(json.dumps({"type": "req", "id": "abort", "method": "chat.abort",
                                              "params": {"sessionKey": self.session_key}}))
        finally:
            await ws.close()

    @staticmethod
    def clean(text):
        import re
        text = re.sub(r"<think[^>]*>.*?</think\s*>", "", text, flags=re.S)
        text = re.sub(r"<think[^>]*>.*", "", text, flags=re.S)
        return re.sub(r"</?final>", "", text).strip()


def make_backend(provider, config):
    return {"hermes": HermesBridge, "openclaw": OpenClawBridge, "deepseek": DeepSeekBridge, "ollama": OllamaBridge}[provider](config)
