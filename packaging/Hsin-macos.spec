"""macOS 源码开发包：仅包含公共资源，个人模型从用户配置导入。"""
from pathlib import Path
import platform
import sys

import yaml
from PIL import Image

root = Path(SPECPATH).parent
if sys.platform != "darwin":
    raise RuntimeError("此配置仅用于 macOS 构建")
staging = root / "build/macos-resources"
staging.mkdir(parents=True, exist_ok=True)
# 使用发行默认值，避免把本机绝对路径与私人配置装入 .app。
config = yaml.safe_load((root / "packaging/config.yaml").read_text(encoding="utf8"))
config["voice"]["enabled"] = False
for section, kind in (("voice", "tts"), ("stt", "asr")):
    config[section]["qwen"]["python"] = f"inference/{kind}/bin/python"
    config[section]["qwen"]["gpu"] = "cpu"
(staging / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf8")
Image.open(root / "src/assets/icons/hsin.png").convert("RGBA").resize((1024, 1024)).save(staging / "hsin.icns")

resources = [(str(staging / "config.yaml"), "."), (str(root / "LICENSE"), "."),
             (str(root / "tools/hsin_voice_server.py"), "tools"),
             (str(root / "src/core/qwen_worker.py"), "src/core"),
             (str(root / "scripts/ssh_supervisor.sh"), "scripts")]
for folder in ("icons", "loading", "motions", "character_profiles", "pmx_viewer"):
    resources.append((str(root / "src/assets" / folder), "src/assets/" + folder))
analysis = Analysis([str(root / "packaging/entry.py")], pathex=[str(root)],
                    binaries=[], datas=resources,
                    hiddenimports=["Cocoa", "objc", "webrtcvad", "_webrtcvad", "edge_tts"],
                    hookspath=[str(root / "packaging/hooks")],
                    excludes=["torch", "transformers", "tensorflow", "pytest", "PIL", "tkinter"],
                    noarchive=False)
analysis.datas = [item for item in analysis.datas
                  if Path(item[0]).name != ".DS_Store" and "__pycache__" not in Path(item[0]).parts]
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="Hsin",
                 console=False, debug=False, upx=False, argv_emulation=False,
                 target_arch=platform.machine(), codesign_identity=None)
collection = COLLECT(executable, analysis.binaries, analysis.datas, name="Hsin-macos", upx=False)
app = BUNDLE(collection, name="Hsin.app", icon=str(staging / "hsin.icns"),
             bundle_identifier="com.hsin.desktop-spirit", version="1.3.0",
             info_plist={"LSUIElement": True, "NSHighResolutionCapable": True,
                         "NSMicrophoneUsageDescription": "心使用麦克风进行语音对话，只有主动开启时才录音。"})
