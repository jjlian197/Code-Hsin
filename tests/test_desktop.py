"""验证真实 Qt 窗口、跨线程控制、本机 HTTP/WS 和退出清理。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import threading
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from aiohttp import ClientSession
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QFontMetrics
from PyQt6.QtWidgets import QApplication
import websockets

from src.core.app_config import load_config
from src.core.control_bridge import ControlBridge
from src.core.control_services import ControlServices
from src.core.sprite_window import HsinSpriteWindow


class QtWindowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = load_config()
        self.config["sprite"]["renderer"] = "placeholder"
        # 窗口测试只使用占位渲染器；仓库不分发 PMX，测试也不依赖私有模型。
        model_fixture = Path(self.temp.name) / "model.pmx"
        model_fixture.write_bytes(b"placeholder")
        self.config["sprite"]["model"]["path"] = str(model_fixture)
        self.config["runtime"]["directory"] = self.temp.name
        self.config["voice"]["profiles"] = str(Path(self.temp.name) / "untrained.json")
        self.window = HsinSpriteWindow(self.config)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.cleanup()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.003)

class DesktopTest(QtWindowTestCase):
    def test_transparency_and_independent_model_paths(self):
        self.assertTrue(self.window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(self.window.sprite_view.model_path.is_file())
        self.assertFalse(self.window.sprite_view.model_loaded)
        self.assertEqual(self.window.windowTitle(), "心 · Hsin 桌面精灵")
        self.assertTrue(QFontMetrics(self.app.font()).inFontUcs4(ord("心")))

    def test_drag_from_renderer_and_tap_are_distinct(self):
        touches = []
        self.window.touch_event.connect(lambda *args: touches.append(args))
        target = self.window.sprite_view
        self.window.move(20, 20)
        before = self.window.pos()
        start = target.mapToGlobal(QPoint(80, 80))
        self._mouse(target, QEvent.Type.MouseButtonPress, QPointF(start), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        self._mouse(target, QEvent.Type.MouseMove, QPointF(start + QPoint(70, 35)), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        self._mouse(target, QEvent.Type.MouseButtonRelease, QPointF(start + QPoint(70, 35)), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        self.assertEqual(self.window.pos(), before + QPoint(70, 35))
        self.assertEqual(touches, [])
        self._mouse(target, QEvent.Type.MouseButtonPress, QPointF(start), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        self._mouse(target, QEvent.Type.MouseButtonRelease, QPointF(start), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        self.assertEqual(touches, [("tap", "身体")])

    def _mouse(self, target, kind, global_pos, button, buttons):
        local = QPointF(target.mapFromGlobal(global_pos.toPoint()))
        event = QMouseEvent(kind, local, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(target, event)

    def test_bubble_plain_text_follow_and_timer(self):
        self.window.show_message("<b>御者</b>", 0)
        self.assertEqual(self.window.bubble_widget.message_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertTrue(self.window.bubble_widget.isVisible())
        self.window.move(200, 250)
        self.app.processEvents()
        bubble = self.window.bubble_widget
        self.assertTrue(self.window.screen().availableGeometry().contains(bubble.geometry().topLeft()))
        self.window.show_message("自动收起", 40)
        self.wait(0.08)
        self.assertFalse(bubble.isVisible())

    def test_click_through_and_tray_recovery_preserve_hidden_state(self):
        self.window._click_through_action.trigger()
        self.assertTrue(self.window.is_click_through)
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.window._click_through_action.trigger()
        self.assertFalse(self.window.is_click_through)
        self.window.hide_sprite()
        self.window.set_click_through(True)
        self.window.set_always_on_top(False)
        self.assertFalse(self.window.isVisible())
        self.window.set_click_through(False)
        self.window.show_sprite()
        self.assertTrue(self.window.isVisible())

    def test_saved_position_uses_own_runtime(self):
        self.window.move(100, 100)
        self.window.save_state()
        state = json.loads((Path(self.temp.name) / "window.json").read_text())
        self.assertEqual(state, {"x": 100, "y": 100})


class APITest(QtWindowTestCase):
    def setUp(self):
        super().setUp()
        self.bridge = ControlBridge(self.window)
        config = deepcopy(self.config)
        # 测试用临时端口，不占用真实 Hsin / 爱弥斯端口。
        config["websocket"]["port"] = 0
        config["http"]["port"] = 0
        self.services = ControlServices(self.bridge, config)
        self.services.start()
        self.window.touch_event.connect(lambda a, p: self.services.broadcast_sync("touch_event", {"action": a, "part": p}))
        self.pool = ThreadPoolExecutor(1)

    def tearDown(self):
        self.bridge.close()
        self.services.stop()
        self.pool.shutdown(wait=True)
        super().tearDown()

    def network(self, coroutine):
        future = self.pool.submit(asyncio.run, coroutine)
        deadline = time.monotonic() + 8
        while not future.done() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.003)
        return future.result(timeout=1)

    def test_websocket_status_message_move_and_bad_payloads(self):
        async def client():
            async with websockets.connect(self.services.endpoints()["websocket"]) as ws:
                await ws.send(json.dumps({"type": "window", "data": {"action": "move", "x": 123, "y": 145}, "id": "move-1"}))
                moved = json.loads(await ws.recv())
                await ws.send(json.dumps({"type": "message", "data": {"text": "心的气泡", "duration": 0}}))
                message = json.loads(await ws.recv())
                await ws.send('{"type":"get_status"}')
                status = json.loads(await ws.recv())
                await ws.send("broken JSON")
                bad = json.loads(await ws.recv())
                await ws.send('{"type":"window","data":{"action":"opacity","opacity":2}}')
                invalid = json.loads(await ws.recv())
                await ws.send('{"type":"get_status","id":NaN}')
                nonfinite = json.loads(await ws.recv())
                return moved, message, status, bad, invalid, nonfinite
        moved, message, status, bad, invalid, nonfinite = self.network(client())
        self.assertEqual(moved["id"], "move-1")
        self.assertTrue(message["success"])
        self.assertEqual(self.window.bubble_widget.message_label.text(), "心的气泡")
        self.assertEqual(status["data"]["position"], {"x": 123, "y": 145})
        self.assertEqual(status["data"]["connected_clients"], 1)
        self.assertEqual(status["data"]["state"], "model_pending")
        self.assertEqual(bad["data"]["code"], "invalid_json")
        self.assertFalse(invalid["success"])
        self.assertEqual(nonfinite["data"]["code"], "invalid_json")

    def test_http_alias_generic_health_and_unavailable_features(self):
        async def client():
            url = self.services.endpoints()["http"]
            async with ClientSession() as session:
                async with session.post(url + "/api/window", json={"action": "resize", "width": 320, "height": 480}) as r:
                    resized = await r.json()
                async with session.post(url + "/api/command", json={"type": "background", "data": {"type": "purple"}}) as r:
                    background = await r.json()
                async with session.get(url + "/health") as r:
                    status = await r.json()
                async with session.post(url + "/api/expression", json={"name": "happy"}) as r:
                    unavailable_status, unavailable = r.status, await r.json()
                async with session.post(url + "/api/command", json={"type": "window", "data": []}) as r:
                    invalid_status = r.status
                return resized, background, status, unavailable_status, unavailable, invalid_status
        resized, background, status, error_status, error, invalid = self.network(client())
        self.assertTrue(resized["success"])
        self.assertTrue(background["success"])
        self.assertEqual(status["data"]["window"]["width"], 320)
        self.assertEqual(status["data"]["window"]["background"], "purple")
        self.assertEqual(error_status, 501)
        self.assertEqual(error["data"]["code"], "renderer_unavailable")
        self.assertEqual(invalid, 400)

    def test_tts_language_alias_is_persistent_and_invalid_batch_is_atomic(self):
        async def client():
            url = self.services.endpoints()["http"]
            async with ClientSession() as session:
                async with session.post(url + "/api/tts_config", json={"language": "ja", "enabled": False}) as r:
                    changed = await r.json()
                async with session.post(url + "/api/tts_config", json={"language": "en", "enabled": True}) as r:
                    invalid = await r.json()
                async with session.get(url + "/api/status") as r:
                    status = await r.json()
                return changed, invalid, status
        changed, invalid, status = self.network(client())
        self.assertTrue(changed["success"])
        self.assertFalse(invalid["success"])
        self.assertEqual(status["data"]["tts"]["language"], "ja")
        self.assertFalse(status["data"]["tts"]["enabled"])
        self.assertEqual(json.loads(self.window.tts.state_path.read_text())["language"], "ja")
        self.assertTrue(self.window._voice_language_actions["ja"].isChecked())
        self.assertFalse(self.window._voice_language_actions["zh"].isChecked())
        self.assertFalse(self.window._voice_enabled_action.isChecked())

    def test_touch_broadcast(self):
        received = threading.Event()
        async def client():
            async with websockets.connect(self.services.endpoints()["websocket"]) as ws:
                received.set()
                return json.loads(await ws.recv())
        future = self.pool.submit(asyncio.run, client())
        self.assertTrue(received.wait(3))
        self.window.touch_event.emit("tap", "身体")
        result = future.result(timeout=3)
        self.assertEqual(result, {"type": "touch_event", "data": {"action": "tap", "part": "身体"}})

    def test_stt_http_settings_and_invalid_batch(self):
        from unittest.mock import patch
        async def client():
            url = self.services.endpoints()["http"]
            async with ClientSession() as session:
                async with session.post(url + "/api/stt_config", json={"enabled": True, "language": "ja", "provider": "whisper"}) as r:
                    changed = await r.json()
                async with session.post(url + "/api/stt_config", json={"language": "unknown", "enabled": False}) as r:
                    invalid = await r.json()
                async with session.post(url + "/api/stt_config", json={"action": "status"}) as r:
                    state = await r.json()
                async with session.post(url + "/api/stt_config", json={"action": "off"}) as r:
                    stopped = await r.json()
            return changed, invalid, state, stopped
        with patch.object(self.window.stt, "_start_capture"):
            changed, invalid, state, stopped = self.network(client())
        self.assertTrue(changed["success"])
        self.assertFalse(invalid["success"])
        self.assertTrue(state["data"]["enabled"])
        self.assertEqual(state["data"]["language"], "ja")
        self.assertFalse(stopped["data"]["enabled"])
        self.assertFalse(self.window._microphone_action.isChecked())

    def test_chat_and_playback_block_microphone(self):
        from PyQt6.QtMultimedia import QMediaPlayer
        from unittest.mock import patch
        self.window.chat.busy = True
        self.window.chat.changed.emit()
        self.assertTrue(self.window.stt.blocked)
        self.window.chat.busy = False
        self.window.chat.changed.emit()
        self.assertFalse(self.window.stt.blocked)
        with patch.object(self.window.voice_player.player, "playbackState", return_value=QMediaPlayer.PlaybackState.PlayingState):
            self.window._sync_microphone()
            self.assertTrue(self.window.stt.blocked)
        self.window._sync_microphone()
        self.assertFalse(self.window.stt.blocked)

    def test_hotwords_settings_are_persistent(self):
        from unittest.mock import patch
        import yaml
        from src.ui.microphone_dialog import MicrophoneDialog
        root = Path(self.temp.name)
        (root / "config.local.yaml").write_text("chat:\n  provider: hermes\n", encoding="utf-8")
        dialog = MicrophoneDialog(self.window)
        dialog.hotwords.setPlainText("心\n心月狐\n御者\n心")
        with patch("src.ui.microphone_dialog.PROJECT_ROOT", root):
            dialog.save()
        saved = yaml.safe_load((root / "config.local.yaml").read_text(encoding="utf-8"))
        self.assertEqual(saved["stt"]["hotwords"], ["心", "心月狐", "御者"])
        self.assertEqual(self.window.stt.config["hotwords"], ["心", "心月狐", "御者"])
        self.assertEqual(saved["chat"]["provider"], "hermes")

    def test_shutdown_releases_ports(self):
        ports = [self.services.ws.port, self.services.http.port]
        self.bridge.close()
        self.services.stop()
        self.assertFalse(self.services.thread.is_alive())
        for port in ports:
            with socket.socket() as sock:
                sock.settimeout(0.2)
                self.assertNotEqual(sock.connect_ex(("127.0.0.1", port)), 0)


class ConfigTest(unittest.TestCase):
    def test_default_ports_are_independent(self):
        config = load_config()
        self.assertEqual(config["websocket"]["port"], 18765)
        self.assertEqual(config["http"]["port"], 18766)

    def test_external_bind_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("websocket:\n  host: 0.0.0.0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "回环"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
