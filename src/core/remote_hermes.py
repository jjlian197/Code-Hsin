"""Stream the PC's existing Hsin Agent through the authenticated HTTPS bridge."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable
import uuid

import aiohttp
from src.core.remote_voice import validate_remote


class RemoteHermesBridge:
    def __init__(self, configuration: dict[str, Any]) -> None:
        validate_remote(configuration)
        self.url = configuration['url'].rstrip('/')
        self.token = configuration['token']
        self.session_id = uuid.uuid4().hex

    async def chat(self, text: str, language: str,
                   on_delta: Callable[[str], Awaitable[None]], *, reply_length: str = 'normal') -> str:
        request_id = uuid.uuid4().hex
        headers = {'Authorization': 'Bearer ' + self.token}
        complete = False
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=240)) as client:
            try:
                async with client.post(self.url + '/v1/hermes', json={
                    'request_id': request_id, 'session_id': self.session_id,
                    'text': text, 'language': language, 'reply_length': reply_length}) as response:
                    if response.status != 200:
                        raise RuntimeError('PC Hermes 桥接不可用')
                    async for encoded in response.content:
                        if len(encoded) > 256 * 1024:
                            raise RuntimeError('PC Hermes 响应过大')
                        event = json.loads(encoded)
                        if event['type'] == 'delta':
                            await on_delta(event['text'])
                        elif event['type'] == 'complete':
                            complete = True
                            return event['text']
                        elif event['type'] == 'error':
                            raise RuntimeError('PC Hermes Agent 回复失败')
                    raise RuntimeError('PC Hermes 回复中断')
            finally:
                if not complete:
                    # Cancellation targets this request only; never the user's desktop Agent session.
                    try:
                        async with asyncio.timeout(3):
                            async with client.post(self.url + '/v1/cancel', json={'request_id': request_id}):
                                pass
                    except (TimeoutError, aiohttp.ClientError):
                        pass
