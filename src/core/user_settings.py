"""统一设置的本机保存与应用；不连接云端、不自动打开麦克风。"""
from copy import deepcopy
from pathlib import Path
import yaml

from src.core.app_config import merge_config, project_path, read_yaml, validate_config
from src.core.stt_hotwords import hotwords


def settings_path(config):
    if config.get("_settings_path"):
        return Path(config["_settings_path"])
    return Path(config.get("_config_path", project_path("config.yaml"))).with_name("config.local.yaml")


def needs_setup(config):
    setup = config.get("setup", {})
    return not isinstance(setup, dict) or setup.get("completed") is not True


def save_settings(owner, changes):
    candidate = merge_config(owner.config, changes)
    validate_config(candidate)
    candidate["stt"]["hotwords"] = hotwords(candidate["stt"])
    changes = deepcopy(changes)
    changes["stt"] = candidate["stt"]
    path = settings_path(owner.config)
    local = read_yaml(path) if path.is_file() else {}
    local = merge_config(local, changes)
    local["setup"] = {"completed": True}
    temp = path.with_suffix(".tmp")
    temp.write_text(yaml.safe_dump(local, allow_unicode=True, sort_keys=False), encoding="utf8")
    temp.replace(path)
    previous = deepcopy(owner.config)
    if candidate["chat"] != owner.chat.config or candidate["chat"]["provider"] != owner.chat.provider:
        owner.stop_chat()
        owner.chat.config = deepcopy(candidate["chat"])
        owner.chat.configure(candidate["chat"]["provider"])
    voice = candidate["voice"]
    owner.tts.configure(**{name: voice[name] for name in ("enabled", "language", "provider", "auto_translate", "fallback")})
    owner.tts.volume = voice["volume"]
    owner.voice_player.output.setVolume(voice["volume"])
    owner.stt.configure(**candidate["stt"])
    window = candidate["sprite"]["window"]
    owner.set_always_on_top(window["always_on_top"])
    owner.setWindowOpacity(window["opacity"])
    owner.config.clear()
    owner.config.update(candidate)
    owner.config["setup"] = local["setup"]
    if hasattr(owner, "characters") and owner.characters.active:
        from src.core.character_settings import profile_from_config
        profile = owner.characters.get(owner.characters.active)
        updated = profile_from_config(candidate, profile["name"], profile["package"], profile["persona"])
        updated["id"] = profile["id"]
        owner.characters.save(updated)
    restart = any(previous[name] != candidate[name] for name in ("http", "websocket"))
    restart |= any(previous["voice"][name] != voice[name] for name in ("profiles", "port"))
    restart |= previous["voice"].get("qwen") != voice.get("qwen")
    restart |= previous["sprite"]["model"] != candidate["sprite"]["model"]
    restart |= previous["sprite"].get("animation", {}) != candidate["sprite"].get("animation", {})
    return restart
