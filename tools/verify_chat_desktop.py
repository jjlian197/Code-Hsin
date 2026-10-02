"""原生窗口验收：聊天输入、真实 Hermes 回复、中日合成、PCM 口型与停止。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import time
import traceback
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication
from src.core.app_config import load_config, project_path
from src.core.control_bridge import ControlBridge
from src.core.sprite_window import HsinSpriteWindow
from tools.verify_behavior import GuiProbe


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app=QApplication(["verify_chat_desktop"])
    app.setQuitOnLastWindowClosed(False)
    config=load_config()
    temp=tempfile.TemporaryDirectory(dir=project_path(".runtime"))
    config["runtime"]["directory"]=temp.name
    config["voice"].update(enabled=True,volume=0)
    config["chat"]["provider"]="hermes"
    window=HsinSpriteWindow(config)
    window.tts.provider.runtime=project_path(".runtime/tts")
    bridge=ControlBridge(window)
    probe=GuiProbe(window)
    window.show_sprite()
    result={"success":False,"turns":[],"failures":[]}
    pool=ThreadPoolExecutor(1)

    async def verify():
        async def command(kind,data=None):
            response=await bridge.execute({"type":kind,"data":data or {}})
            assert response["success"],response
            return response["data"]
        for _ in range(450):
            status=await command("get_status")
            if status["renderer"]["model_loaded"]: break
            assert not status["renderer"]["error"]
            await asyncio.sleep(.1)
        else: raise AssertionError("模型加载超时")
        for language,text in (("zh","连接测试。请用心的身份，向御者说一句简短问候，不要调用工具。"),
                              ("ja","御者に短い挨拶を一文で言って。ツールは使わないで。")):
            await command("tts_config",{"language":language})
            def send(future):
                window.open_chat()
                window.chat_dialog.input.setText(text)
                window.chat_dialog.send()
                future.set_result(window.chat.snapshot())
            queued=await probe.call(send)
            assert queued["busy"] and queued["provider"]=="hermes"
            saw_stream=False
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                status=await command("get_status")
                assert not status["chat"]["error"],status["chat"]
                def partial(future): future.set_result(bool(window.chat.partial))
                saw_stream |= await probe.call(partial)
                if not status["chat"]["busy"] and status["chat"]["reply"]: break
                await asyncio.sleep(.05)
            else: raise AssertionError("真实 Hermes 回复超时")
            reply=status["chat"]["reply"]
            peak,playing=0,False
            deadline=time.monotonic()+200
            while time.monotonic()<deadline:
                status=await command("get_status")
                assert not status["tts"]["error"],status["tts"]
                assert not status["audio"]["error"],status["audio"]
                path=(status["audio"]["path"] or "").replace("\\","/")
                playing |= f"cache/{language}/" in path and status["audio"]["state"]=="PlayingState"
                peak=max(peak,(await probe.state())["behavior"]["mouth_open"])
                if playing and not status["tts"]["synthesizing"] and status["audio"]["state"]=="StoppedState": break
                await asyncio.sleep(.04)
            assert playing and peak>.15,(status,peak)
            assert status["tts"]["last_request"]["language"]==language
            await asyncio.sleep(.3)
            assert (await probe.state())["behavior"]["mouth_open"]<.02
            result["turns"].append({"language":language,"reply":reply,"stream_seen":saw_stream,"mouth_peak":peak,"audio":status["audio"]["path"]})
            print(f"PASS {language}: chat dialog -> Hermes -> Hsin TTS -> PCM mouth",flush=True)
        def capture(future):
            path=project_path(".runtime/chat-preview.png")
            window.chat_dialog.grab().save(str(path))
            future.set_result(str(path))
        result["preview"]=await probe.call(capture)
        await command("chat",{"text":"请说一句晚安，不要使用工具。"})
        await command("chat_config",{"action":"stop"})
        await asyncio.sleep(.5)
        status=await command("get_status")
        assert not status["chat"]["busy"] and not status["tts"]["synthesizing"] and status["audio"]["state"]=="StoppedState"
        await command("chat_config",{"provider":"deepseek"})
        def checked(future): future.set_result(window._backend_actions["deepseek"].isChecked())
        assert await probe.call(checked)
        result["stop_and_backend_menu"]=True
        result["success"]=True

    future=pool.submit(lambda:asyncio.run(verify()))
    def watch():
        if future.done():
            try: future.result()
            except Exception: result["failures"].append(traceback.format_exc())
            app.quit()
        else: QTimer.singleShot(40,watch)
    watch()
    QTimer.singleShot(450000,app.quit)
    try: app.exec()
    finally:
        bridge.close()
        window.cleanup()
        window.hide()
        pool.shutdown(wait=True)
        temp.cleanup()
    project_path(".runtime/chat-desktop-validation.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"success":result["success"],"failures":result["failures"]}),flush=True)
    return 0 if result["success"] else 1


if __name__=="__main__":
    raise SystemExit(main())
