"""实际加载界面：竖/横插画比例、加载完成隐藏及失败提示。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import traceback
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["verify_loading_artwork"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    window = HsinSpriteWindow(config)
    view = window.sprite_view
    # 暂缓真实加载完成回调，确保截图不会因机器快慢错过短暂加载界面。
    completed = []
    view.bridge.result.disconnect(view._model_result)
    view.bridge.result.connect(lambda *args: completed.append(args))
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "checks": [], "captures": [], "failures": []}

    async def gui(fn):
        return await probe.call(lambda f: f.set_result(fn()))

    async def verify():
        for width, height, name in ((400,600,"standing"),(1000,600,"lying")):
            await gui(lambda: window.set_size(width,height))
            await asyncio.sleep(.15)
            def check_art():
                image = view.loading_image.pixmap()
                original = view._loading_pixmaps[name]
                assert view.loading_image.isVisible() and view.label.isVisible()
                assert not original.isNull() and not image.isNull()
                assert abs(image.width()/image.height()-original.width()/original.height())<.01
                assert image.size().width() <= view.loading_image.width() and image.size().height() <= view.loading_image.height()
            await gui(check_art)
            report["checks"].append(name+":对应插画等比例完整显示")
            report["captures"].append(await probe.capture("loading-"+name))
        for _ in range(500):
            if completed:
                break
            await asyncio.sleep(.1)
        assert completed and completed[-1][1], completed
        await gui(lambda: view._model_result(*completed[-1]))
        assert await gui(lambda: view.model_loaded and view.loading_image.isHidden() and view.label.isHidden())
        report["checks"].append("真实 PMX 加载完成后自动收起插画")
        await gui(lambda: view.load_model(view.model_path))
        await gui(lambda: view._model_result(view._request_id,False,"验收模拟加载失败"))
        assert await gui(lambda: not view.model_loaded and view.loading_image.isVisible() and view.label.isVisible() and "暂时" in view.label.text())
        report["checks"].append("加载失败保留插画与可读提示")
        report["success"] = True

    async def run():
        try:
            await verify()
        except Exception:
            report["failures"].append(traceback.format_exc())
        finally:
            await gui(app.quit)
    QTimer.singleShot(0,lambda:pool.submit(asyncio.run,run()))
    app.exec()
    window.cleanup()
    window.hide()
    pool.shutdown(wait=True)
    temp.cleanup()
    project_path(".runtime/loading-artwork-validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
