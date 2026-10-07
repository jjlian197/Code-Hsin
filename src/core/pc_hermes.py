"""Bounded PC-owned Hermes sessions; clients cannot choose an Agent, URL or token."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from typing import Any

from src.core.hermes_bridge import HermesBridge


class PCHermesSessions:
    def __init__(self, configuration: dict[str, Any]) -> None:
        self.configuration = configuration
        self.sessions: dict[str, tuple[HermesBridge, float]] = {}
        self.active: set[str] = set()
        self.lock = threading.Lock()

    def stream(self, handler: Any, payload: dict[str, Any], job: dict[str, Any]) -> None:
        identity = payload.get('session_id', '')
        text, language = payload.get('text'), payload.get('language')
        reply_length = payload.get('reply_length', 'normal')
        if (not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity)
                or not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000
                or language not in ('zh', 'ja') or reply_length not in ('short', 'normal', 'detailed')):
            raise ValueError('Hermes 请求无效')
        with self.lock:
            now = time.monotonic()
            self.sessions = {key: entry for key, entry in self.sessions.items()
                             if key in self.active or now - entry[1] < 3600}
            if identity in self.active or (identity not in self.sessions and len(self.sessions) >= 128):
                raise ValueError('Hermes 会话忙碌或容量已满')
            if identity not in self.sessions:
                self.sessions[identity] = (HermesBridge(self.configuration), now)
            bridge = self.sessions[identity][0]
            self.active.add(identity)

        def emit(kind: str, **fields: Any) -> None:
            handler.wfile.write((json.dumps({'type': kind, **fields}, ensure_ascii=False) + '\n').encode())
            handler.wfile.flush()

        async def run() -> None:
            job['loop'], job['task'] = asyncio.get_running_loop(), asyncio.current_task()
            if job['cancelled']:
                return
            handler.send_response(200)
            handler.send_header('Content-Type', 'application/x-ndjson')
            handler.send_header('Connection', 'close')
            handler.send_header('Cache-Control', 'no-store')
            handler.end_headers()
            handler.close_connection = True
            async def delta(chunk: str) -> None:
                emit('delta', text=chunk)
            try:
                reply = await bridge.chat(text.strip(), language, delta, reply_length=reply_length)
                emit('complete', text=reply)
            except asyncio.CancelledError:
                pass
            except Exception:
                # Upstream errors may include private URLs or authentication parameters.
                try:
                    emit('error', error='PC Hermes Agent 回复失败')
                except OSError:
                    pass
        try:
            asyncio.run(run())
        finally:
            with self.lock:
                self.active.discard(identity)
                self.sessions[identity] = (bridge, time.monotonic())
