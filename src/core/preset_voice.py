"""可随发行版携带的中日固定台词，无训练资源也可离线播放。"""
import hashlib
import json
from src.core.app_config import project_path


def preset_key(text, language):
    return hashlib.sha256(json.dumps([language, text.strip()], ensure_ascii=False).encode()).hexdigest()


class PresetVoice:
    def __init__(self):
        self.path = project_path("voice/presets/manifest.json")
        try:
            self.entries = json.loads(self.path.read_text(encoding="utf8"))["entries"]
        except (OSError, ValueError, KeyError):
            self.entries = {}

    def find(self, text, language, speed=1):
        if speed != 1:
            return None
        entry = self.entries.get(preset_key(text, language))
        if not entry or entry.get("text") != text.strip() or entry.get("language") != language:
            return None
        path = (self.path.parent / entry["file"]).resolve()
        if not path.is_relative_to(self.path.parent.resolve()) or not path.is_file():
            return None
        return path

    def available(self):
        return any(self.find(entry["text"], entry["language"]) for entry in self.entries.values())
