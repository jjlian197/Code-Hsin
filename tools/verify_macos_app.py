"""从临时目录启动真实源码/.app，验证双形态、本机服务和正常退出。"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

import websockets
import yaml

from src.core.app_config import load_config, PROJECT_ROOT


def wait_status(process: subprocess.Popen, endpoint: str, timeout: float = 45) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = "服务尚未就绪"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"应用提前退出：{process.returncode}")
        try:
            with urlopen(endpoint + "/api/status", timeout=3) as response:
                payload = json.load(response)
            state = payload["data"]
            renderer = state["renderer"]
            if renderer.get("error"):
                raise RuntimeError(renderer["error"])
            if renderer["model_loaded"] and renderer["info"]["runtime"]["frames"] > 3:
                return state
        except (OSError, ValueError, KeyError) as error:
            last_error = str(error)
        time.sleep(0.1)
    raise TimeoutError(last_error)


async def send_ws_command(endpoint: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with websockets.connect(endpoint) as connection:
        request_id = uuid.uuid4().hex
        await connection.send(json.dumps({"id": request_id, "type": kind, "data": payload}))
        # TTS 状态广播可先于命令响应到达，用 ID 匹配，不能把广播当作确认。
        while True:
            reply = json.loads(await asyncio.wait_for(connection.recv(), timeout=10))
            if reply.get("id") == request_id:
                assert reply["success"], reply
                return reply


async def switch_form(endpoint: str) -> None:
    await send_ws_command(endpoint, "model", {"form": "second"})


async def request_remote_speech(endpoint: str) -> None:
    await send_ws_command(endpoint, "speak", {
        "text": "御者，这是应用包通过电脑语音桥接说出的一句话。", "translate": False})


def verify_remote_playback(process: subprocess.Popen, endpoints: dict[str, str]) -> dict[str, Any]:
    asyncio.run(request_remote_speech(endpoints["websocket"]))
    deadline = time.monotonic() + 100
    playing = False
    peak = 0.0
    mouth_peak = 0.0
    while time.monotonic() < deadline:
        assert process.poll() is None, "应用在语音验证期间退出"
        with urlopen(endpoints["http"] + "/api/status", timeout=3) as response:
            state = json.load(response)["data"]
        assert not state["stt"]["enabled"] and not state["chat"]["enabled"]
        if state["tts"]["error"]:
            raise RuntimeError(state["tts"]["error"])
        playing |= state["audio"]["state"] == "PlayingState"
        peak = max(peak, state["audio"]["peak_level"])
        mouth_peak = max(mouth_peak, state["renderer"]["info"]["runtime"]["behavior"]["mouth_open"])
        if playing and state["tts"]["stage"] == "idle":
            assert peak > 0.05 and mouth_peak > 0.05
            assert state["tts"]["actual_provider"] == "remote"
            return {"provider": "remote", "playing_observed": playing, "pcm_peak": peak, "mouth_peak": mouth_peak}
        time.sleep(0.1)
    raise TimeoutError("应用包 PC 语音未完成实际播放")


def descendants(parent_pid: int) -> set[int]:
    listing = subprocess.check_output(["ps", "-axo", "pid=,ppid="], text=True)
    parent_by_pid = {int(pid): int(parent) for pid, parent in (line.split() for line in listing.splitlines())}
    found: set[int] = set()
    pending = {parent_pid}
    while pending:
        children = {pid for pid, parent in parent_by_pid.items() if parent in pending} - found
        found.update(children)
        pending = children
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="store_true", help="验证源码启动器，默认验证 dist/Hsin.app")
    parser.add_argument("--pc-voice", action="store_true", help="额外验证实际 PC 音频播放和口型，会发声、不打开麦克风")
    parser.add_argument("--signal-exit", action="store_true", help="验证 SIGTERM 退出和隧道清理")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("此检查需要 macOS 桌面会话")
    mode = "source" if args.source else "bundle"
    output_root = PROJECT_ROOT / ".runtime"
    output_root.mkdir(exist_ok=True)
    report: dict[str, Any] = {"success": False, "mode": mode, "checks": [], "forms": [], "failures": []}
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONHOME", "PYTHONPATH", "QT_QPA_PLATFORM", "HSIN_DATA_DIR"}}
    launcher = PROJECT_ROOT / "启动心.command" if args.source else PROJECT_ROOT / "dist/Hsin.app/Contents/MacOS/Hsin"
    if not launcher.is_file():
        raise SystemExit(f"启动器不存在：{launcher}")
    process = None
    endpoints: dict[str, str] = {}
    child_pids: set[int] = set()
    report_suffix = ("-pc-voice" if args.pc_voice else "") + ("-sigterm" if args.signal_exit else "")
    log_path = output_root / f"macos-{mode}-smoke.log"
    with tempfile.TemporaryDirectory() as directory, log_path.open("w", encoding="utf8") as log:
        isolated_root = Path(directory).resolve()
        config = load_config()
        # 启动配置要求真实端口；同时占用两只临时套接字避免选到相同端口。
        with socket.socket() as ws_port_probe, socket.socket() as http_port_probe:
            ws_port_probe.bind(("127.0.0.1", 0))
            http_port_probe.bind(("127.0.0.1", 0))
            ws_port = ws_port_probe.getsockname()[1]
            http_port = http_port_probe.getsockname()[1]
        overrides = {"sprite": config["sprite"], "voice": {"enabled": False}, "chat": {"enabled": False},
                     "websocket": {"port": ws_port}, "http": {"port": http_port}}
        if args.pc_voice:
            overrides["speech_bridge"] = config["speech_bridge"]
            overrides["voice"].update(enabled=True, provider="remote", auto_translate=False, fallback=False)
            overrides["stt"] = {"provider": "remote"}
        (isolated_root / "config.local.yaml").write_text(yaml.safe_dump(overrides, allow_unicode=True), encoding="utf8")
        arguments = [str(launcher), "--data-dir", str(isolated_root), "--run-for", "150" if args.pc_voice else "90",
                     "--snapshot", str(output_root / f"macos-{mode}-preview.png")]
        try:
            process = subprocess.Popen(arguments, cwd=isolated_root, env=environment, stdout=log, stderr=log)
            registry = isolated_root / ".runtime/endpoints.json"
            deadline = time.monotonic() + 25
            while not registry.is_file():
                assert process.poll() is None, f"应用提前退出：{process.returncode}；参见 {log_path}"
                assert time.monotonic() < deadline, "服务登记超时"
                time.sleep(0.1)
            endpoints = json.loads(registry.read_text())
            for form in ("first", "second"):
                if form == "second":
                    asyncio.run(switch_form(endpoints["websocket"]))
                status = wait_status(process, endpoints["http"])
                renderer = status["renderer"]
                assert renderer["info"]["texture_errors"] == 0
                assert renderer["info"]["chest_rig_bones"] == 10
                assert status["stt"]["enabled"] is False
                assert status["chat"]["enabled"] is False
                assert renderer["info"]["runtime"]["physics_steps"] > 0
                assert Path(renderer["model_path"]).resolve() == Path(config["sprite"]["model"]["forms"][form]).resolve()
                report["forms"].append({"form": form, "texture_errors": 0,
                                        "physics_steps": renderer["info"]["runtime"]["physics_steps"]})
            report["checks"].append("从临时工作目录加载双形态、中文路径、物理和本机 HTTP/WS")
            if args.pc_voice:
                report["remote_voice"] = verify_remote_playback(process, endpoints)
                report["checks"].append("PC 新句合成、Qt 实际播放与 PMX 口型")
            duplicate = subprocess.run(arguments, cwd=isolated_root, env=environment, stdout=log, stderr=log, timeout=15)
            assert duplicate.returncode == 0 and process.poll() is None
            report["checks"].append("重复启动不新增实例")
            child_pids = descendants(process.pid)
            if args.signal_exit:
                process.terminate()
            else:
                asyncio.run(send_ws_command(endpoints["websocket"], "window", {"action": "quit"}))
            assert process.wait(timeout=15) == 0
            for endpoint in endpoints.values():
                parsed = urlparse(endpoint)
                with socket.socket() as connection:
                    connection.settimeout(0.3)
                    assert connection.connect_ex((parsed.hostname, parsed.port)) != 0, "退出后监听仍存在"
                with socket.socket() as probe:
                    # 服务使用地址复用；普通 bind 会把 TIME_WAIT 误判为仍在监听。
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind((parsed.hostname, parsed.port))
            application_log = isolated_root / ".runtime/hsin.log"
            if application_log.is_file():
                (output_root / f"macos-{mode}-exit.log").write_text(application_log.read_text())
            startup_error = isolated_root / ".runtime/startup-error.log"
            if startup_error.is_file():
                raise RuntimeError(startup_error.read_text())
            report["children_at_exit"] = subprocess.run(["ps", "-p", ",".join(map(str, child_pids)), "-o", "pid=,state=,command="], capture_output=True, text=True).stdout if child_pids else ""
            deadline = time.monotonic() + 5
            alive = child_pids
            while alive and time.monotonic() < deadline:
                living_pids = {int(pid) for pid in subprocess.check_output(["ps", "-axo", "pid="], text=True).split()}
                alive &= living_pids
                time.sleep(0.1)
            assert not alive, f"退出后仍存活的子进程：{alive}"
            report["checks"].append("正常退出释放锁、端口与渲染子进程")
            registry.unlink()
            restarted = subprocess.run([str(launcher), "--data-dir", str(isolated_root), "--run-for", "1"],
                                       cwd=isolated_root, env=environment, stdout=log, stderr=log, timeout=20)
            assert restarted.returncode == 0 and registry.is_file(), "重启未取得锁或未启动服务"
            report["checks"].append("退出后可立即重启")
            report["success"] = True
        except Exception:
            report["failures"].append(traceback.format_exc())
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    report_path = output_root / f"macos-{mode}{report_suffix}-validation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
