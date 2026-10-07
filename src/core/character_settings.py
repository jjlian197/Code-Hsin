"""角色配置只保存身份与资源绑定；连接凭据继续引用全局配置。"""
from copy import deepcopy
import json
import uuid

from src.core.app_config import DEFAULT_CONFIG, merge_config, project_path, validate_config
from src.core.character_package import load_character_package

CHAT_KEYS = ("enabled", "provider", "reply_length", "speech_scope", "speech_sentence_count", "speech_prefix_chars")
BACKEND_KEYS = {"hermes": ("profile",), "openclaw": ("agent",), "deepseek": ("model",), "ollama": ("model", "thinking", "context_length")}
VOICE_KEYS = ("enabled", "provider", "remote_voice", "language", "volume", "auto_translate", "fallback", "profiles", "qwen")


def profile_from_config(config, name="心", package="", persona=None):
    config = merge_config(DEFAULT_CONFIG, config)
    config["chat"].setdefault("enabled", True)
    if persona is None:
        persona = config["chat"].get("persona", "")
    chat = {key: deepcopy(config["chat"][key]) for key in CHAT_KEYS}
    chat.update({backend: {key: deepcopy(config["chat"][backend][key]) for key in keys}
                 for backend, keys in BACKEND_KEYS.items()})
    return {"id": uuid.uuid4().hex, "name": name, "package": package, "persona": persona,
            "chat": chat, "voice": {key: deepcopy(config["voice"][key]) for key in VOICE_KEYS}}


def profile_config(config, profile):
    if not isinstance(profile, dict) or any(not isinstance(profile.get(key), str) for key in ("id", "name", "package", "persona")):
        raise ValueError("角色配置格式无效")
    if not profile["id"] or not profile["name"].strip() or len(profile["name"]) > 64 or len(profile["persona"]) > 16000:
        raise ValueError("请填写角色名称，人设最多16000字")
    chat, voice = profile.get("chat"), profile.get("voice")
    if not isinstance(chat, dict) or not isinstance(voice, dict):
        raise ValueError("角色需要聊天和语音配置")
    if set(chat) - set(CHAT_KEYS) - set(BACKEND_KEYS) or set(voice) - set(VOICE_KEYS):
        raise ValueError("角色配置包含不支持的字段")
    for backend, keys in BACKEND_KEYS.items():
        if not isinstance(chat.get(backend, {}), dict) or set(chat.get(backend, {})) - set(keys):
            raise ValueError("角色只绑定模型或Agent；凭据在连接设置中保存")
    candidate = merge_config(config, {"chat": chat, "voice": voice})
    candidate["chat"]["persona"] = profile["persona"]
    validate_config(candidate)
    return candidate


class CharacterSettings:
    def __init__(self, owner):
        self.owner = owner
        self.path = project_path(owner.config["runtime"]["directory"]) / "characters.json"
        self.active, self.pending = None, None
        self.histories = {}
        self.profiles = []
        try:
            data = json.loads(self.path.read_text(encoding="utf8"))
            if data.get("version") != 1 or not isinstance(data.get("profiles"), list):
                raise ValueError("无效角色列表")
            for profile in data["profiles"]:
                if isinstance(profile, dict) and isinstance(profile.get("voice"), dict):
                    profile["voice"].setdefault("remote_voice", "hsin")
                profile_config(owner.config, profile)
                if any(item["id"] == profile["id"] for item in self.profiles):
                    raise ValueError("角色ID重复")
                self.profiles.append(profile)
            self.active = data.get("active")
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            self.profiles, self.active = [], None
        if not self.profiles:
            self.profiles = [profile_from_config(owner.config)]
            self.profiles[0]["id"] = "hsin"
            self.active = self.profiles[0]["id"]
            owner.chat.character_id = self.active
            aemeath = project_path(".runtime/characters/aemeath/character.json")
            if aemeath.is_file():
                profile = profile_from_config(owner.config, "爱弥斯", str(aemeath),
                    project_path("src/assets/character_profiles/aemeath.persona.txt").read_text(encoding="utf8"))
                profile["voice"].update(enabled=False, fallback=False, remote_voice="aemeath")
                profile["chat"].update(enabled=False, provider="ollama")
                self.profiles.append(profile)

    def get(self, identity):
        return next(item for item in self.profiles if item["id"] == identity)

    def persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"version": 1, "active": self.active, "profiles": self.profiles}, ensure_ascii=False, indent=2), encoding="utf8")
        temp.replace(self.path)

    def save(self, profile):
        profile_config(self.owner.config, profile)
        previous = deepcopy(self.profiles)
        self.profiles = [item for item in self.profiles if item["id"] != profile["id"]] + [deepcopy(profile)]
        try:
            self.persist()
        except OSError:
            self.profiles = previous
            raise

    def activate(self, identity):
        if self.pending:
            raise ValueError("角色正在加载，请稍后切换")
        owner, profile = self.owner, deepcopy(self.get(identity))
        candidate = profile_config(owner.config, profile)
        if profile["package"]:
            load_character_package(project_path(profile["package"]))
        voice = candidate["voice"]
        if voice["enabled"] and voice["provider"] in ("qwen", "gptsovits"):
            fixed_hsin = profile["id"] == "hsin" and voice["provider"] == "gptsovits" and not project_path(voice["profiles"]).is_file()
            if not fixed_hsin:
                data = json.loads(project_path(voice["profiles"]).read_text(encoding="utf8"))
                if not all(isinstance(data.get("profiles", {}).get(lang), dict) for lang in ("zh", "ja")):
                    raise ValueError("请选择有效的中日音色配置")
        owner.stop_chat()
        owner.stt.configure(enabled=False)
        self.histories[self.active] = deepcopy(owner.chat.messages)
        self.pending = (profile, candidate)
        self.previous_visual = (getattr(owner.sprite_view, "model_path", None), getattr(owner.sprite_view, "character_package", None))
        if owner.sprite_view.renderer_name != "pmx":
            if profile["package"]:
                self.pending = None
                raise ValueError("导入角色需要PMX渲染器")
            self.finish(True)
            return
        owner._model_actions_ready(False)
        try:
            if profile["package"]:
                owner.sprite_view.load_character(project_path(profile["package"]))
            else:
                model = owner.config["sprite"]["model"]
                owner.sprite_view.load_default_model(project_path(model.get("forms", {}).get("first", model["path"])), fallback=True)
        except (OSError, ValueError):
            self.pending = None
            raise

    def finish(self, success):
        if not self.pending:
            return
        profile, candidate = self.pending
        self.pending = None
        owner = self.owner
        if not success or getattr(owner.sprite_view, "character_error", None):
            owner.show_message("角色配置未切换，已保留原来的聊天和语音设置。", 6000)
            return
        # 模型确认加载后才提交其人设、音色及启动选择。
        previous = self.active
        self.active = profile["id"]
        try:
            self.persist()
        except OSError:
            self.active = previous
            path, package = self.previous_visual
            if owner.sprite_view.renderer_name == "pmx":
                if package:
                    owner.sprite_view.load_character(package["file"])
                else:
                    owner.sprite_view.load_default_model(path)
            owner.show_message("模型已加载，但角色选择未能保存，请检查配置目录权限。", 6000)
            return
        owner.chat.config = deepcopy(candidate["chat"])
        owner.chat.character_id, owner.chat.character_name = profile["id"], profile["name"]
        owner.chat.messages = deepcopy(self.histories.get(profile["id"], []))
        owner.chat.last_request = None
        owner.chat.configure(candidate["chat"]["provider"])
        owner.config["chat"] = deepcopy(candidate["chat"])
        owner.config["voice"] = deepcopy(candidate["voice"])
        owner.tts.configure_resources(candidate["voice"], presets=profile["id"] == "hsin" or (not profile["package"] and profile["name"] == "心" and not profile["persona"]))
        voice = candidate["voice"]
        owner.tts.configure(**{key: voice[key] for key in ("enabled", "provider", "language", "auto_translate", "fallback")})
        owner.tts.volume = voice["volume"]
        owner.voice_player.output.setVolume(voice["volume"])
        owner.chat.updated.emit()
        if owner.settings_dialog:
            owner.settings_dialog.reject()
        owner.show_message("已切换到" + profile["name"] + "。", 4000)

    def restore(self):
        if self.path.is_file() and self.active:
            try:
                self.activate(self.active)
            except (OSError, ValueError, StopIteration, KeyError, TypeError):
                self.owner.show_message("上次角色的资源无法恢复，请在设置 → 角色管理中重新选择。", 6000)
