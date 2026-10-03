"""复用 type/data 控制协议，所有窗口读写统一回到 Qt 主线程。"""
import asyncio
from concurrent.futures import Future, InvalidStateError
import math
import json
import threading

from loguru import logger
from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

from src.core.app_config import project_path

PARAMETER_RANGES = {
    "ParamAngleX": (-30, 30), "ParamAngleY": (-20, 20), "ParamAngleZ": (-15, 15),
    "ParamBodyAngleX": (-10, 10), "ParamBodyAngleY": (-10, 10),
    "ParamEyeBallX": (-1, 1), "ParamEyeBallY": (-1, 1),
    "ParamEyeLOpen": (0, 1), "ParamEyeROpen": (0, 1),
    "ParamMouthOpenY": (0, 1), "ParamMouthForm": (-1, 1),
}
BEHAVIOR_FLAGS = {"auto_blink", "breathing", "mouse_follow", "touch_reactions", "conversation_actions", "random_idle", "reset_parameters"}


class CommandError(ValueError):
    def __init__(self, message, code="invalid_command"):
        super().__init__(message)
        self.code = code


def decode_json(value):
    def invalid_constant(constant):
        raise ValueError(f"JSON 不允许 {constant}")
    return json.loads(value, parse_constant=invalid_constant)


def number(value, label, lower, upper):
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise CommandError(f"{label} 必须在 {lower}–{upper} 之间")
    return float(value)


def integer(value, label, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise CommandError(f"{label} 必须是 {lower}–{upper} 的整数")
    return value


def boolean(value, label):
    if type(value) is not bool:
        raise CommandError(f"{label} 必须是布尔值")
    return value


class ControlBridge(QObject):
    command_requested = pyqtSignal(object, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._lock = threading.Lock()
        self._pending = set()
        self._closed = False
        self.command_requested.connect(self._apply, Qt.ConnectionType.QueuedConnection)

    async def execute(self, command):
        future = Future()
        with self._lock:
            if self._closed:
                return self.error("服务正在退出", "shutting_down")
            self._pending.add(future)
        self.command_requested.emit(command, future)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=5)
        except asyncio.TimeoutError:
            return self.error("界面响应超时", "ui_timeout")
        finally:
            with self._lock:
                self._pending.discard(future)

    def close(self):
        with self._lock:
            self._closed = True
            pending = list(self._pending)
        for future in pending:
            future.cancel()

    @staticmethod
    def error(message, code="invalid_command"):
        return {"type": "error", "success": False, "data": {"message": message, "code": code}}

    @pyqtSlot(object, object)
    def _apply(self, command, future):
        if future.cancelled():
            return
        try:
            result = self.dispatch(command)
        except CommandError as exc:
            result = self.error(str(exc), exc.code)
        except (ValueError, TypeError) as exc:
            result = self.error(str(exc))
        except Exception:
            logger.exception("Hsin 控制命令执行失败")
            result = self.error("命令执行失败，请查看 Hsin 日志", "internal_error")
        if isinstance(command, dict) and "id" in command:
            result["id"] = command["id"]
        try:
            future.set_result(result)
        except InvalidStateError:
            pass

    def dispatch(self, command):
        if not isinstance(command, dict) or not isinstance(command.get("type"), str):
            raise CommandError("需要包含 type 的 JSON 对象")
        kind, data = command["type"], command.get("data", {})
        if not isinstance(data, dict):
            raise CommandError("data 必须是 JSON 对象")
        window = self.window
        if kind == "get_status":
            view = window.sprite_view
            status = {"name": "Hsin", "state": "idle" if view.model_loaded else ("model_error" if getattr(view, "load_error", None) else "model_pending"),
                      "expression": view.current_expression, "position": {"x": window.x(), "y": window.y()},
                      "available_expressions": view.get_available_expressions(),
                      "total_expressions": len(view.get_available_expressions()),
                      "available_motions": view.get_available_motions() if hasattr(view, "get_available_motions") else [],
                      "window": {"visible": window.isVisible(), "width": window.width(), "height": window.height(),
                                 "opacity": window.windowOpacity(), "click_through": window.is_click_through,
                                 "always_on_top": window._always_on_top, "background": window._current_background},
                      "renderer": {"name": view.renderer_name, "model_loaded": view.model_loaded,
                                   "model_path": str(view.model_path) if view.model_path else None,
                                   "model_file_exists": bool(view.model_path and view.model_path.is_file()),
                                   "error": getattr(view, "load_error", None),
                                   "info": getattr(view, "model_info", {})},
                      "tts": window.tts.snapshot(), "audio": window.voice_player.snapshot(), "chat": window.chat.snapshot(), "stt": window.stt.snapshot(),
                      "pomodoro": window.pomodoro.snapshot(),
                      "mood": window.mood.snapshot(),
                      "voice_dataset_available": project_path(window.config["voice"]["manifest"]).is_file(),
                      "capabilities": ["message", "window", "background", "get_status", "touch_event", "speak", "tts_config", "chat", "chat_config", "stt_config", "pomodoro", "mood"]}
            if view.renderer_name == "pmx":
                status["capabilities"].append("model")
            if view.model_loaded:
                status["capabilities"].extend(["expression", "motion", "physics", "look_at", "parameter", "parameter_batch", "behavior", "blink", "lip_sync", "audio"])
                status["available_parameters"] = {key: list(limits) for key, limits in PARAMETER_RANGES.items()}
            return self.success("status", status)
        if kind == "mood":
            action = data.get("action", "status")
            allowed = {"action", "auto_expression"} if action == "configure" else {"action"}
            if set(data) - allowed:
                raise CommandError("未知心情参数")
            if action == "status":
                window._tick_mood()
            elif action == "configure":
                window.mood.configure(data.get("auto_expression"))
            elif action == "open":
                window.open_mood()
            else:
                raise CommandError("mood.action 需要 status、configure 或 open")
            return self.success("mood_status", window.mood.snapshot())
        if kind == "pomodoro":
            action = data.get("action", "status")
            allowed = {"action"} | ({"phase"} if action == "start" else set(window.pomodoro.settings) if action == "configure" else set())
            if set(data) - allowed:
                raise CommandError("未知番茄钟参数")
            if action == "status":
                window.pomodoro.tick()
            elif action == "configure":
                window.pomodoro.configure(**{key: value for key, value in data.items() if key != "action"})
            elif action == "start":
                window.pomodoro.start(data.get("phase"))
            elif action in {"pause", "resume", "reset"}:
                getattr(window.pomodoro, action)()
            elif action == "open":
                window.open_pomodoro()
            else:
                raise CommandError("pomodoro.action 需要 status、configure、start、pause、resume、reset 或 open")
            return self.success("pomodoro_status", window.pomodoro.snapshot())
        if kind == "model":
            if window.sprite_view.renderer_name != "pmx":
                raise CommandError("需要 PMX 渲染器", "renderer_unavailable")
            form = data.get("form")
            if not isinstance(form, str):
                raise CommandError("form 需要 first 或 second")
            window.set_model_form(form)
            return self.success("model_loading", {"form": form})
        if kind == "chat":
            return self.success("chat_queued", window.send_chat(data.get("text"), data.get("language")))
        if kind == "stt_config":
            if any(key not in {"action", "enabled", "provider", "language", "device", "silence_ms", "energy_threshold", "fallback", "hotwords"} for key in data):
                raise CommandError("未知 stt_config 设置")
            action = data.get("action", "set")
            if action == "devices":
                return self.success("stt_devices", {"devices": window.stt.devices()})
            if action == "status":
                return self.success("stt_config", window.stt.snapshot())
            if action not in {"set", "on", "off", "toggle"}:
                raise CommandError("stt_config.action 需要 set、status、devices、on、off 或 toggle")
            settings = {key: value for key, value in data.items() if key != "action"}
            if action in {"on", "off", "toggle"}:
                settings["enabled"] = not window.stt.enabled if action == "toggle" else action == "on"
            window._sync_microphone()
            return self.success("stt_config", window.stt.configure(**settings))
        if kind == "chat_config":
            action = data.get("action", "set")
            if action == "stop":
                window.stop_chat()
            elif action == "set":
                window.set_chat_provider(data.get("provider", window.chat.provider))
            elif action != "status":
                raise CommandError("chat_config.action 需要 set、status 或 stop")
            return self.success("chat_config", window.chat.snapshot())
        if kind == "message":
            text = data.get("text", "")
            if not isinstance(text, str) or not 1 <= len(text) <= 2000:
                raise CommandError("text 需要 1–2000 个字符")
            duration = integer(data.get("duration", 5000), "duration", 0, 600000)
            window.show_message(text, duration)
            return self.success("message_shown", {"text": text, "duration": duration})
        if kind == "window":
            action = data.get("action")
            if action == "move":
                window.set_position(integer(data.get("x", window.x()), "x", -100000, 100000),
                                    integer(data.get("y", window.y()), "y", -100000, 100000))
            elif action == "resize":
                window.set_size(integer(data.get("width"), "width", 160, 1600),
                                integer(data.get("height"), "height", 160, 1600))
            elif action == "opacity":
                window.set_opacity(number(data.get("opacity", 1.0), "opacity", 0.1, 1))
            elif action == "click_through":
                window.set_click_through(boolean(data.get("enabled"), "enabled"))
            elif action == "always_on_top":
                window.set_always_on_top(boolean(data.get("enabled"), "enabled"))
            elif action == "hide":
                window.hide_sprite()
            elif action == "show":
                window.show_sprite()
            elif action == "reset":
                window.position_bottom_right()
            elif action == "quit":
                from PyQt6.QtCore import QTimer
                # 先返回响应，再通过主应用清理退出，供启动器正常重启。
                QTimer.singleShot(250, window.quit_requested.emit)
            else:
                raise CommandError("未知的窗口 action")
            return self.success("window_updated", {"action": action})
        if kind == "background":
            bg = data.get("type", "transparent")
            if not isinstance(bg, str):
                raise CommandError("背景 type 必须是字符串")
            if bg == "image":
                if not isinstance(data.get("path"), str) or not data["path"]:
                    raise CommandError("图片背景需要本地 path")
                bg = "image:" + data["path"]
            window.set_background(bg)
            return self.success("background_set", {"type": bg})
        if kind == "physics":
            view = window.sprite_view
            if not view.model_loaded:
                raise CommandError("模型尚未加载完成", "renderer_unavailable")
            action = data.get("action")
            if action == "reset":
                window._reset_physics()
            elif action in ("on", "off"):
                window.set_physics(action == "on")
            else:
                raise CommandError("physics.action 需要 on、off 或 reset")
            return self.success("physics_updated", {"action": action})
        if kind in {"expression", "motion", "parameter", "parameter_batch", "look_at", "behavior", "blink", "lip_sync", "audio"}:
            view = window.sprite_view
            if not view.model_loaded:
                raise CommandError("模型尚未加载完成", "renderer_unavailable")
            if kind == "expression":
                name = data.get("name")
                if not isinstance(name, str) or name not in view.get_available_expressions():
                    raise CommandError("此模型不支持该表情")
                window.set_expression(name)
            elif kind == "motion":
                group = data.get("group")
                if not isinstance(group, str):
                    raise CommandError("动作 group 需要字符串")
                loading = view.trigger_motion(group, integer(data.get("index", 0), "index", 0, 1000))
                if loading:
                    return self.success("motion_loading", data)
            elif kind in {"parameter", "parameter_batch"}:
                params = data.get("params") if kind == "parameter_batch" else {data.get("id", data.get("param_id")): data.get("value")}
                if not isinstance(params, dict) or not params or len(params) > len(PARAMETER_RANGES):
                    raise CommandError("params 需要非空的受支持参数对象")
                validated = {}
                for name, value in params.items():
                    if name not in PARAMETER_RANGES:
                        raise CommandError(f"未知模型参数：{name}")
                    validated[name] = number(value, name, *PARAMETER_RANGES[name])
                view.set_parameters(validated)
            elif kind == "look_at":
                x, y = number(data.get("x"), "x", -1, 1), number(data.get("y"), "y", -1, 1)
                view.look_at(x, y)
            elif kind == "behavior":
                if not data or any(key not in BEHAVIOR_FLAGS for key in data):
                    raise CommandError("未知或空的 behavior 设置")
                settings = {key: boolean(value, key) for key, value in data.items()}
                window.set_behavior(settings)
            elif kind == "blink":
                view.blink()
            elif kind == "lip_sync":
                value = number(data.get("value"), "value", 0, 1)
                shape = data.get("shape", "a")
                if not isinstance(shape, str) or shape not in {"a", "i", "u", "e", "o"}:
                    raise CommandError("shape 需要 a、i、u、e 或 o")
                duration = integer(data.get("duration", 250), "duration", 50, 2000)
                view.set_lip_sync(value, shape, duration)
            elif kind == "audio":
                action = data.get("action")
                if action == "stop":
                    window.tts.stop()
                elif action == "play":
                    path = data.get("path")
                    if not isinstance(path, str) or not path:
                        raise CommandError("播放原声需要本地 path")
                    volume = number(data.get("volume", 0.65), "volume", 0, 1)
                    window.tts.stop()
                    window.voice_player.play(project_path(path), volume)
                else:
                    raise CommandError("audio.action 需要 play 或 stop")
            return self.success(kind + "_set", data)
        if kind == "speak":
            if not window.tts.snapshot()["configured"]:
                raise CommandError("所选语音引擎尚未就绪", "tts_unavailable")
            if not window.tts.enabled:
                raise CommandError("语音已关闭", "tts_disabled")
            language = data.get("language", window.tts.language)
            text = data.get("text")
            speed = number(data.get("speed", 1.0), "speed", 0.5, 2)
            volume = number(data.get("volume", window.tts.volume), "volume", 0, 1)
            translate = boolean(data["translate"], "translate") if "translate" in data else None
            request = window.tts.speak(text, language, speed, volume, translate=translate)
            return self.success("tts_queued", request)
        if kind == "tts_config":
            if any(key not in {"language", "enabled", "provider", "auto_translate", "fallback", "action"} for key in data):
                raise CommandError("tts_config 支持 language、enabled、provider、auto_translate、fallback、action")
            action = data.get("action", "set")
            if action not in {"set", "status", "on", "off", "toggle", "stop"}:
                raise CommandError("未知 tts_config.action")
            enabled = data.get("enabled")
            if "language" in data and data["language"] not in ("zh", "ja"):
                raise CommandError("language 需要 zh 或 ja")
            if "enabled" in data:
                enabled = boolean(enabled, "enabled")
            if action in {"on", "off", "toggle"}:
                enabled = not window.tts.enabled if action == "toggle" else action == "on"
            if action == "stop":
                window.tts.stop()
            extra = {name: data[name] for name in ("provider", "auto_translate", "fallback") if name in data}
            state = window.tts.snapshot() if action in {"status", "stop"} else window.tts.configure(data.get("language"), enabled, **extra)
            return self.success("tts_config", state)
        raise CommandError(f"未知命令：{kind}", "unknown_command")

    @staticmethod
    def success(kind, data):
        return {"type": kind, "data": data, "success": True}
