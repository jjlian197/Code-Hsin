"""读取 Hsin 独立端口的手动控制客户端。"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websockets
from src.core.app_config import load_config


async def run(mode, text):
    config = load_config()["websocket"]
    host = f"[{config['host']}]" if ":" in config["host"] else config["host"]
    commands = [{"type": "get_status", "data": {}}]
    if mode in ("all", "message"):
        commands.append({"type": "message", "data": {"text": text, "duration": 4000}})
    async with websockets.connect(f"ws://{host}:{config['port']}/sprite") as ws:
        for command in commands:
            await ws.send(json.dumps(command, ensure_ascii=False))
            print(await ws.recv())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=["all", "status", "message"], default="status")
    parser.add_argument("--text", default="御者，我在这里。")
    args = parser.parse_args()
    asyncio.run(run(args.mode, args.text))
