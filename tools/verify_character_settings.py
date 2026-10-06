"""真实设置页保存/切换/重启爱弥斯，使用临时状态，不连接聊天或语音服务。"""
import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
import json
import tempfile
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMenu
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    output = project_path(".runtime/character-settings-validation")
    output.mkdir(parents=True, exist_ok=True)
    temp = tempfile.TemporaryDirectory()
    config = load_config()
    config["runtime"]["directory"] = temp.name
    config["voice"]["enabled"] = False
    config["chat"]["enabled"] = False
    config["sprite"]["animation"]["physics"] = False
    config["sprite"]["animation"]["behavior"] = {key: False for key in (
        "auto_blink", "breathing", "mouse_follow", "touch_reactions", "random_idle", "conversation_actions")}
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["character-settings-validation"])
    app.setQuitOnLastWindowClosed(False)
    window = HsinSpriteWindow(deepcopy(config))
    windows = [window]
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "checks": [], "failures": []}

    async def loaded(target):
        for _ in range(450):
            ready, error, pending = await probe.call(lambda f: f.set_result((target.sprite_view.model_loaded, target.sprite_view.load_error, target.characters.pending is not None)))
            if error:
                raise AssertionError(error)
            if ready and not pending:
                return
            await asyncio.sleep(.1)
        raise AssertionError("加载超时")

    async def verify():
        await loaded(window)
        def edit(f):
            window.open_settings(page=6)
            page = window.settings_dialog.character_page
            profile = next(item for item in window.characters.profiles if item["name"] == "爱弥斯")
            page.roles.setCurrentIndex(page.roles.findData(profile["id"]))
            page.persona.setPlainText("你是爱弥斯，在桌面上陪伴用户。")
            page.fields["chat.provider"].setCurrentIndex(page.fields["chat.provider"].findData("ollama"))
            page.fields["chat.enabled"].setChecked(False)
            page.fields["voice.enabled"].setChecked(False)
            page.fields["voice.language"].setCurrentIndex(page.fields["voice.language"].findData("ja"))
            page.save()
            assert "已保存" in page.status.text()
            window.settings_dialog.grab().save(str(output / "settings.png"))
            page.activate()
            f.set_result(profile["id"])
        identity = await probe.call(edit)
        await loaded(window)
        def check(target):
            assert target.characters.active == identity
            assert target.chat.config["persona"] == "你是爱弥斯，在桌面上陪伴用户。"
            assert target.chat.character_name == "爱弥斯"
            assert target.tts.language == "ja" and not target.tts.enabled
            assert not target.stt.enabled
            assert target.sprite_view.model_info["character"] == "爱弥斯"
            assert target.sprite_view.model_info["texture_errors"] == 0
        await probe.call(lambda f: (check(window), window.grab().save(str(output / "aemeath.png")), f.set_result(None)))
        report["checks"].append("设置页保存并启用爱弥斯：模型、人设、后端、语言、语音开关")
        def switch(f):
            default = next(item for item in window.characters.profiles if item["name"] == "心")
            menu = QMenu(window)
            window._populate_characters(menu)
            next(action for action in menu.actions() if action.text() == "心 · 完整配置").trigger()
            menu.deleteLater()
            f.set_result(default["id"])
        default_id = await probe.call(switch)
        await loaded(window)
        assert await probe.call(lambda f: f.set_result(window.characters.active == default_id and window.chat.character_name == "心"))
        await probe.call(lambda f: (window.activate_character(identity), f.set_result(None)))
        await loaded(window)
        report["checks"].append("角色菜单一键切回心并返回爱弥斯")
        def invalid_package(f):
            original = project_path(".runtime/characters/aemeath/character.json")
            package = json.loads(original.read_text(encoding="utf8"))
            package["rig"] = str(original.parent / package["rig"])
            morphs = json.loads((original.parent / package["morphs"]).read_text(encoding="utf8"))
            morphs["expressions"]["happy"] = {"不存在的表情": .5}
            morph_file = project_path(temp.name) / "bad-morphs.json"
            morph_file.write_text(json.dumps(morphs, ensure_ascii=False), encoding="utf8")
            package["morphs"] = str(morph_file)
            package_file = project_path(temp.name) / "bad-character.json"
            package_file.write_text(json.dumps(package, ensure_ascii=False), encoding="utf8")
            profile = deepcopy(window.characters.get(identity))
            profile.update(id="invalid", name="错误角色", package=str(package_file), persona="不应生效的人设")
            window.characters.save(profile)
            window.characters.activate(profile["id"])
            f.set_result(None)
        await probe.call(invalid_package)
        await loaded(window)
        await probe.call(lambda f: (check(window), f.set_result(None)))
        report["checks"].append("无效Morph包恢复爱弥斯，未提交错误角色的人设、音色或启动选择")
        def restart(f):
            window.hide_sprite()
            restored = HsinSpriteWindow(deepcopy(config))
            windows.append(restored)
            restored.show_sprite()
            f.set_result(restored)
        restored = await probe.call(restart)
        await loaded(restored)
        await probe.call(lambda f: (check(restored), restored.grab().save(str(output / "restored.png")), f.set_result(None)))
        report["checks"].append("新应用窗口从磁盘恢复爱弥斯及其配置，麦克风保持关闭")
        report["success"] = True

    def run():
        try:
            asyncio.run(verify())
        except Exception:
            report["failures"].append(traceback.format_exc())
        finally:
            probe.requested.emit(lambda f: (app.quit(), f.set_result(None)), Future())
    QTimer.singleShot(1000, lambda: pool.submit(run))
    QTimer.singleShot(120000, app.quit)
    try:
        app.exec()
    finally:
        for target in windows:
            target.cleanup()
            target.close()
        pool.shutdown(wait=True)
        temp.cleanup()
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
