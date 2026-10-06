"""独立配置：所有默认路径均以 Code Hsin 为基准。"""
from copy import deepcopy
from pathlib import Path
import os
import sys

import yaml
from src.core.stt_hotwords import DEFAULT_HOTWORDS

PROJECT_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))


def user_data_root():
    """便携数据随目录移动；安装版数据独立于可替换的程序目录。"""
    override = os.environ.get("HSIN_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if not getattr(sys, "frozen", False):
        return None
    if (PROJECT_ROOT / "portable.txt").is_file():
        return PROJECT_ROOT / "data"
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Hsin"
DEFAULT_CONFIG = {
    "sprite": {"name": "Hsin", "window": {"width": 400, "height": 600, "opacity": 1.0,
               "always_on_top": True, "click_through": False}, "renderer": "pmx",
               "model": {"path": "", "forms": {}},
               "animation": {"side_lying": "src/assets/motions/side_lying.fbx",
                             "transitions": {"first": "src/assets/motions/first.json", "second": "src/assets/motions/second.json"}}},
    "websocket": {"enabled": True, "host": "127.0.0.1", "port": 18765},
    "http": {"enabled": True, "host": "127.0.0.1", "port": 18766},
    "logging": {"level": "INFO", "file": ".runtime/hsin.log"},
    "runtime": {"directory": ".runtime", "model_idle_seconds": 600},
    "stt": {"provider": "qwen", "language": "zh", "device": "",
            "hotwords": list(DEFAULT_HOTWORDS),
            "silence_ms": 700, "energy_threshold": 250, "zhipu": {"api_key": ""},
            "qwen": {"python": ".runtime/local-model-tests/venv-asr/Scripts/python.exe", "model": ".runtime/local-model-tests/models/qwen3-asr", "gpu": "4080"}},
    "voice": {"manifest": "voice/hsin_zh/selection.json", "profiles": "voice/profiles.json",
              "enabled": False, "language": "zh", "volume": 0.65, "port": 19880,
              "provider": "gptsovits", "auto_translate": True, "fallback": True,
              "qwen": {"python": ".runtime/local-model-tests/venv-tts/Scripts/python.exe", "gpu": "4080",
                       "zh_model": ".runtime/qwen3-tts-training/zh/checkpoint-epoch-3", "ja_model": ".runtime/local-model-tests/models/qwen3-tts"}},
    "chat": {"provider": "hermes", "reply_length": "normal", "speech_scope": "full", "speech_sentence_count": 3, "speech_prefix_chars": 500,
             "hermes": {"home": str(Path.home() / "AppData/Local/hermes"), "url": "", "profile": "default", "token": ""},
             "openclaw": {"url": "ws://127.0.0.1:18789/ws", "agent": "hsin", "token": ""},
             "deepseek": {"model": "deepseek-v4-flash", "api_key": ""},
             "ollama": {"url": "http://127.0.0.1:11434", "model": "huihui_ai/qwen3.5-abliterated:4b",
                        "thinking": False, "context_length": 4096}},
}


def project_path(value):
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    data = user_data_root()
    if data and ((path.parts and path.parts[0] in {".runtime", "models", "inference"}) or path.as_posix() in {"config.local.yaml", "voice/profiles.json"}):
        return (data / path).resolve()
    local = (PROJECT_ROOT / path).resolve()
    resource = (RESOURCE_ROOT / path).resolve()
    return resource if not local.exists() and resource.exists() else local


def merge_config(base, overrides):
    result = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def read_yaml(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置必须是 YAML 对象：{path}")
    return data


def load_config(path=None):
    path = Path(path).resolve() if path else PROJECT_ROOT / "config.yaml"
    config = merge_config(DEFAULT_CONFIG, read_yaml(path))
    data = user_data_root()
    local = data / "config.local.yaml" if data else path.with_name("config.local.yaml")
    if data:
        data.mkdir(parents=True, exist_ok=True)
        # 从旧便携版迁移用户设置/状态，原文件保留，且不覆盖已有新目录。
        legacy = path.with_name("config.local.yaml")
        if not local.exists() and legacy.is_file() and legacy != local:
            import shutil
            shutil.copyfile(legacy, local)
        old_runtime = path.parent / ".runtime"
        target = data / ".runtime"
        if not target.exists() and old_runtime.is_dir():
            import shutil
            target.mkdir(parents=True)
            for name in ("chat.json", "voice.json", "window.json", "mood.json", "pomodoro.json", "characters.json"):
                if (old_runtime / name).is_file():
                    shutil.copyfile(old_runtime / name, target / name)
            if (old_runtime / "characters").is_dir():
                shutil.copytree(old_runtime / "characters", target / "characters")
        legacy_voice = path.parent / "voice/profiles.json"
        user_voice = data / "voice/profiles.json"
        if not user_voice.exists() and legacy_voice.is_file():
            import shutil
            user_voice.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(legacy_voice, user_voice)
    if local.exists():
        config = merge_config(config, read_yaml(local))
    if data:
        config["runtime"]["directory"] = str(data / ".runtime")
        config["logging"]["file"] = str(data / ".runtime/hsin.log")
        config["_settings_path"] = str(local)
    if config["stt"].get("provider") == "whisper":
        config["stt"]["provider"] = "qwen"
    config["stt"].pop("model_path", None)
    config["stt"].pop("fallback", None)
    validate_config(config)
    config["_config_path"] = str(path)
    return config


def validate_config(config):
    window = config["sprite"]["window"]
    for key in ("width", "height"):
        value = window[key]
        if type(value) is not int or not 160 <= value <= 1600:
            raise ValueError(f"窗口 {key} 必须是 160–1600 的整数")
    if type(window["opacity"]) not in (int, float) or not 0.1 <= window["opacity"] <= 1:
        raise ValueError("窗口 opacity 必须在 0.1–1 之间")
    for key in ("always_on_top", "click_through"):
        if type(window[key]) is not bool:
            raise ValueError(f"窗口 {key} 必须是布尔值")
    ports = []
    for name in ("websocket", "http"):
        service = config[name]
        if service["host"] not in ("127.0.0.1", "::1"):
            raise ValueError(f"{name} 只允许监听本机回环地址")
        if type(service["enabled"]) is not bool:
            raise ValueError(f"{name}.enabled 必须是布尔值")
        if type(service["port"]) is not int or not 1 <= service["port"] <= 65535:
            raise ValueError(f"{name}.port 必须是有效端口")
        if service["enabled"]:
            ports.append(service["port"])
    if len(ports) != len(set(ports)):
        raise ValueError("HTTP 与 WebSocket 需要不同端口")
    if config["sprite"]["renderer"] not in ("placeholder", "pmx"):
        raise ValueError("renderer 需要 pmx 或 placeholder")
    animation = config["sprite"].get("animation", {})
    if not isinstance(animation, dict) or type(animation.get("physics", True)) is not bool:
        raise ValueError("animation.physics 需要布尔值")
    if not isinstance(animation.get("vmd", {}), dict):
        raise ValueError("animation.vmd 需要动作组对象")
    transitions = animation.get("transitions", {})
    if not isinstance(transitions, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in transitions.items()):
        raise ValueError("animation.transitions 需要形态到本地动作文件的映射")
    if not isinstance(animation.get("side_lying", "Female Laying Pose (1).fbx"), str) or not animation.get("side_lying", "Female Laying Pose (1).fbx").strip():
        raise ValueError("animation.side_lying 需要非空本地 FBX 文件路径")
    behavior = animation.get("behavior", {})
    if not isinstance(behavior, dict) or any(k not in {"auto_blink", "breathing", "mouse_follow", "touch_reactions", "conversation_actions", "random_idle"}
            or type(v) is not bool for k, v in behavior.items()):
        raise ValueError("animation.behavior 需要受支持的布尔值设置")
    for group, files in animation.get("vmd", {}).items():
        if not isinstance(group, str) or not group or group in {"idle", "wave", "nod", "tap", "peace", "finger_heart", "crossed_arms", "side_lying", "lie_down", "get_up"}:
            raise ValueError("VMD 动作组名称不能占用基础动作名")
        if not isinstance(files, list) or not files or any(not isinstance(f, str) or not f for f in files):
            raise ValueError("VMD 动作组需要非空文件路径列表")
    voice = config["voice"]
    idle = config.get("runtime", {}).get("model_idle_seconds", 600)
    if type(idle) is not int or not 0 <= idle <= 3600:
        raise ValueError("本地语音模型闲置释放需要0–3600秒，0表示关闭")
    if not isinstance(voice, dict):
        raise ValueError("voice 需要配置对象")
    if voice.get("language", "zh") not in ("zh", "ja") or type(voice.get("enabled", False)) is not bool:
        raise ValueError("voice.language 需要 zh/ja，voice.enabled 需要布尔值")
    if voice.get("provider", "gptsovits") not in ("gptsovits", "edge", "qwen"):
        raise ValueError("voice.provider 需要 gptsovits、edge 或 qwen")
    if voice.get("provider") == "qwen":
        validate_qwen(voice.get("qwen"), ("python", "zh_model", "ja_model", "gpu"))
    if any(type(voice.get(name, True)) is not bool for name in ("auto_translate", "fallback")):
        raise ValueError("voice.auto_translate / fallback 需要布尔值")
    if type(voice.get("port", 19880)) is not int or not 1 <= voice.get("port", 19880) <= 65535 or voice.get("port", 19880) in ports:
        raise ValueError("voice.port 需要独立的有效端口")
    if type(voice.get("volume", 0.65)) not in (int, float) or not 0 <= voice.get("volume", 0.65) <= 1:
        raise ValueError("voice.volume 需要在 0–1 之间")
    if not isinstance(voice.get("profiles", "voice/profiles.json"), str) or not voice.get("profiles", "voice/profiles.json"):
        raise ValueError("voice.profiles 需要非空配置文件路径")
    validate_chat_config(config["chat"])
    from src.core.stt_manager import validate_stt
    validate_stt(config["stt"])
    return config


def validate_chat_config(chat):
    from src.core.chat_preferences import REPLY_LENGTHS, SPEECH_SCOPES
    from src.core.hermes_bridge import local_url
    if not isinstance(chat, dict) or chat.get("provider") not in ("hermes", "openclaw", "deepseek", "ollama"):
        raise ValueError("chat.provider 需要 hermes、openclaw、deepseek 或 ollama")
    if type(chat.get("enabled", True)) is not bool:
        raise ValueError("chat.enabled 需要布尔值")
    if (not isinstance(chat.get("reply_length", "normal"), str) or chat.get("reply_length", "normal") not in REPLY_LENGTHS
            or not isinstance(chat.get("speech_scope", "full"), str) or chat.get("speech_scope", "full") not in SPEECH_SCOPES):
        raise ValueError("回复长度或朗读范围无效")
    for key, default, low, high in (("speech_sentence_count", 3, 1, 30), ("speech_prefix_chars", 500, 50, 10000)):
        if type(chat.get(key, default)) is not int or not low <= chat.get(key, default) <= high:
            raise ValueError("朗读范围数量无效")
    for backend, keys in (("hermes", ("home", "url", "profile", "token")),
                          ("openclaw", ("url", "agent", "token")), ("deepseek", ("model", "api_key"))):
        if not isinstance(chat.get(backend), dict) or any(not isinstance(chat[backend].get(key), str) for key in keys):
            raise ValueError(f"{backend} 连接设置需要文字字段")
    if not chat["hermes"]["home"] or not chat["hermes"]["profile"] or not chat["openclaw"]["agent"] or not chat["deepseek"]["model"]:
        raise ValueError("Agent 名称、模型和 Hermes 目录不能为空")
    if chat["hermes"]["url"]:
        local_url(chat["hermes"]["url"])
    local_url(chat["openclaw"]["url"], ("ws", "wss"))
    local = chat.get("ollama", {})
    if not isinstance(local, dict) or any(not isinstance(local.get(key, default), str) or not local.get(key, default).strip()
            for key, default in (("url", "http://127.0.0.1:11434"), ("model", "huihui_ai/qwen3.5-abliterated:4b"))):
        raise ValueError("Ollama地址和已有模型名称不能为空")
    local_url(local.get("url", "http://127.0.0.1:11434"), ("http",))
    if type(local.get("thinking", False)) is not bool or type(local.get("context_length", 4096)) is not int or not 2048 <= local.get("context_length", 4096) <= 32768:
        raise ValueError("Ollama思考需要布尔值，上下文需要2048–32768的整数")


def validate_qwen(value, fields):
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or not value[key].strip() for key in fields):
        raise ValueError("Qwen运行环境、模型路径与设备需要非空文字字段")
