"""临时原生预览离线重定向，用连续关键阶段截图检查网格，不连接语音/服务。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import traceback
from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["preview_cmu"])
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    config["voice"]["enabled"] = False
    temp = tempfile.TemporaryDirectory()
    config["runtime"]["directory"] = temp.name
    window = HsinSpriteWindow(config)
    window.set_size(1000, 900)
    window.show_sprite()
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"captures": [], "failures": []}

    async def verify():
        for form in ("first", "second"):
            await probe.call(lambda f: (window.set_model_form(form), f.set_result(None)))
            for _ in range(500):
                if await probe.call(lambda f: f.set_result(window.sprite_view.model_loaded)):
                    break
                await asyncio.sleep(.1)
            await probe.call(lambda f: (window.sprite_view.frame_timer.stop(), f.set_result(None)))
            url = QUrl.fromLocalFile(str(project_path(f"motions/hsin/{form}.json"))).toString(QUrl.ComponentFormattingOption.FullyEncoded)
            for name, times in (("lie_down", [0, 1, 2, 3, 4, 5, 6, 7]), ("get_up", [0, 1, 2, 3, 4, 5, 6, 7.7])):
                for time in times:
                    await probe.evaluate(f"window.__previewPromise=window.HsinPmxDebug.previewTransition({json.dumps(url)},{json.dumps(name)},{time}).then(v=>window.__previewResult=JSON.stringify(v));")
                    for _ in range(80):
                        value = await probe.evaluate("window.__previewResult;")
                        if value:
                            break
                        await asyncio.sleep(.05)
                    await probe.evaluate("window.__previewResult=null;")
                    await asyncio.sleep(.15)
                    path = await probe.capture(f"cmu-{form}-{name}-{time}")
                    report["captures"].append({"form": form, "motion": name, "time": time, "path": path, "state": json.loads(value)})
            print("PREVIEW:", form, flush=True)

    future = pool.submit(lambda: asyncio.run(verify()))
    def watch():
        if future.done():
            try:
                future.result()
            except Exception:
                report["failures"].append(traceback.format_exc())
            app.quit()
        else:
            QTimer.singleShot(30, watch)
    watch()
    app.exec()
    window.cleanup()
    window.hide()
    pool.shutdown(wait=True)
    temp.cleanup()
    project_path(".runtime/cmu-preview.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(report["failures"], flush=True)


if __name__ == "__main__":
    main()
